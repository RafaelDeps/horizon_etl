# Implementation Plan: Anonimização de Dados Pessoais (LGPD)

**Branch**: `001-lgpd-pii-anonymization` | **Date**: 2026-05-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-lgpd-pii-anonymization/spec.md`

## Summary

Aplicar anonimização determinística de CPF (`identification_id`) e e-mail
(`email`, `contact_email`) na camada de persistência do Horizon ETL, via **HMAC-SHA256
com chave secreta de ambiente** (`HORIZON_PII_HMAC_KEY` — padrão private-key/public-key;
a chave privada é variável secreta). Revisão de segurança 2026-09-21 substitui o
SHA-256 com salt fixo público (reversível por brute-force para qualquer leitor do repo).
Novos registros são anonimizados no loader/creator layer antes de serem escritos no banco.
Registros existentes são cobertos por um Prefect flow de backfill com schema discovery automático.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: hmac + hashlib (stdlib), loguru, Prefect 3, SQLite (sqlite3 stdlib), python-dotenv (carregar `HORIZON_PII_HMAC_KEY` de `.env`)

**Storage**: SQLite (`db/horizon.db`) — tabelas `persons`, `person_emails`, `external_research_groups`

**Testing**: pytest — `tests/test_pii_anonymizer.py`, `tests/test_anonymize_backfill.py`

**Target Platform**: ETL pipeline local (Linux/macOS server)

**Project Type**: ETL pipeline / CLI

**Performance Goals**: Backfill de 10.000 registros em ≤ 10 minutos (SC-003)

**Constraints**: Anonimização computacionalmente irreversível sem a chave secreta, determinística (com a mesma chave), sem dependências externas além de stdlib; chave secreta via variável de ambiente (nunca versionada)

**Scale/Scope**: 3 tabelas / 3 colunas PII confirmadas no schema atual; schema discovery cobre futuras adições

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | ✅ PASS | `pii_anonymizer.py` em `core/logic/`; nenhum adapter importado em `core/` |
| II. Domain-First | ✅ PASS | Sem redefinição de entidades de domínio; `persons` de `research-domain` inalterado |
| III. Prefect Flow | ✅ PASS | Backfill como Prefect flow com Telegram hook; persistência-layer não é flow, é lógica pura |
| IV. Audit-Driven | ✅ PASS | Backfill produz log JSON em `data/reports/lgpd_backfill_{ts}.json` |
| V. LGPD Compliance | ✅ PASS | Esta feature é a implementação do princípio V |

**No violations. Gate PASSED.**

## Project Structure

### Documentation (this feature)

```text
specs/001-lgpd-pii-anonymization/
├── plan.md              # Este arquivo
├── research.md          # Decisões técnicas (Phase 0)
├── data-model.md        # Entidades e colunas PII (Phase 1)
└── tasks.md             # Gerado por /speckit-tasks
```

### Source Code (repository root)

```text
src/
├── core/
│   └── logic/
│       └── pii_anonymizer.py          # NOVO: funções puras de anonimização
├── flows/
│   └── maintenance/
│       ├── __init__.py                # NOVO: diretório de flows de manutenção
│       └── anonymize_backfill.py      # NOVO: Prefect flow de backfill

# Modificados (não criados):
# src/core/logic/researcher_creation.py  → aplicar anonymize_cpf/email no save
# src/core/logic/research_group_loader.py → aplicar anonymize_email no ensure_researcher
# Makefile → adicionar targets anonymize-backfill e anonymize-check

tests/
├── test_pii_anonymizer.py             # NOVO
└── test_anonymize_backfill.py         # NOVO
```

**Structure Decision**: Single project. Anonymizer em `core/logic/` (lógica pura). Flow de backfill em `flows/maintenance/` (novo subdiretório para flows operacionais/manutenção).

## Phase 0: Research — Completed

Ver [research.md](research.md). Todas as decisões técnicas resolvidas:

- Ponto de aplicação: loader/creator layer (`researcher_creation.py`, `research_group_loader.py`)
- Algoritmo (2026-09-21): **HMAC-SHA256 com chave secreta** `HORIZON_PII_HMAC_KEY` (subchaves por domínio via HKDF), primeiros 16 chars do hexdigest — substitui SHA-256 + salt público (revisão de segurança)
- Formato: CPF → `LGPD-{hmac[:16]}`, email → `{hmac[:12]}@anon.lgpd` (inalterados)
- Deduplicação: inalterada (HMAC determinístico com a mesma chave preserva unicidade por titular)
- Backfill: Prefect flow com schema discovery via `PRAGMA table_info()`
- Telefone: não existe coluna no schema atual — fora do escopo prático
- Idempotência: backfill pula registros já anonimizados (`LGPD-` / `@anon.lgpd`)
- Secret provisioning: `HORIZON_PII_HMAC_KEY` em `.env` / secret manager (≥ 32 bytes, `secrets.token_urlsafe(32)`); placeholder documentado em `.env.example`; ausente → falha explícita

## Phase 1: Design — Completed

Ver [data-model.md](data-model.md).

### Interface de anonimização (`pii_anonymizer.py`)

```python
# src/core/logic/pii_anonymizer.py

import hmac
import hashlib
import os

# Chave secreta — variável de ambiente, NUNCA versionada.
# _load_hmac_key() falha explicitamente se ausente; subchaves por domínio via
# HKDF-SHA256(labels "cpf"/"email"/"phone"/"free_text") para separação de campos.
HMAC_KEY_ENV = "HORIZON_PII_HMAC_KEY"

# PII columns discovered in schema — add here when new PII columns are created
PII_COLUMN_REGISTRY = {
    "identification_id": "cpf",
    "email": "email",
    "contact_email": "email",
}

def _hmac_hex(domain: str, value: str) -> str:
    key = os.environ[HMAC_KEY_ENV]          # hard-fail se ausente
    subkey = hkdf_sha256(key.encode(), domain)  # domínio → subchave
    return hmac.new(subkey, value.encode("utf-8"), hashlib.sha256).hexdigest()

def anonymize_cpf(value: str | None) -> str | None: ...   # "LGPD-{hmac[:16]}"
def anonymize_email(value: str | None) -> str | None: ... # "{hmac[:12]}@anon.lgpd"
def anonymize_field(value: str | None, field_type: str) -> str | None: ...
def is_anonymized_cpf(value: str | None) -> bool: ...
def is_anonymized_email(value: str | None) -> bool: ...
```

A chave é provisionada localmente em `.env` (`HORIZON_PII_HMAC_KEY=<secrets.token_urlsafe(32)>`) e documentada como placeholder em `.env.example`. Ver research.md Decision 8 para rotação/backup.

### Pontos de aplicação no código existente

**`src/core/logic/researcher_creation.py`**:
```python
from src.core.logic.pii_anonymizer import anonymize_cpf, anonymize_email

# Em create_researcher_with_resume_fallback():
identification_id = anonymize_cpf(identification_id)
emails = [anonymize_email(e) for e in (emails or [])] or None

# Em _ensure_person_emails():
email = anonymize_email(email)  # antes do INSERT
```

**`src/core/logic/research_group_loader.py`**:
```python
from src.core.logic.pii_anonymizer import anonymize_email

# Em ensure_researcher():
email = anonymize_email(email)
```

**`src/core/logic/research_group_exporter.py`** (se `contact_email` é escrito aqui):
- Verificar ponto de escrita de `external_research_groups.contact_email`
- Aplicar `anonymize_email` antes do persist

### Backfill Flow (`anonymize_backfill.py`)

```python
# src/flows/maintenance/anonymize_backfill.py

@flow(name="lgpd-anonymize-backfill")
def anonymize_backfill_flow(db_path: str = "db/horizon.db") -> dict:
    """
    Descobre todas as tabelas/colunas PII via PRAGMA table_info().
    Aplica anonimização determinística em registros não-anonimizados.
    Produz relatório JSON em data/reports/lgpd_backfill_{ts}.json.
    """
    ...
```

Exposto via:
```makefile
anonymize-backfill: ## Anonymize PII in existing DB records (LGPD backfill)
    $(FLOW_PYTHON) app.py anonymize_backfill

anonymize-check: ## Audit DB for unmasked PII fields
    $(PYTHON) -c "from src.flows.maintenance.anonymize_backfill import audit_pii; audit_pii()"
```

### Makefile entry em `app.py`

```python
elif command == "anonymize_backfill":
    from src.flows.maintenance.anonymize_backfill import anonymize_backfill_flow
    anonymize_backfill_flow()
```

## Complexity Tracking

> Nenhuma violação da constituição detectada.
