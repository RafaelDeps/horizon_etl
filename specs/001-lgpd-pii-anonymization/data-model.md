# Data Model: Anonimização de Dados Pessoais (LGPD)

**Branch**: `001-lgpd-pii-anonymization` | **Date**: 2026-05-16

**Updated**: 2026-09-21 — **Security review**: salt público fixo substituído por chave secreta de ambiente (`HORIZON_PII_HMAC_KEY`) via HMAC-SHA256 keyed. Formatos de token inalterados.

## Tabelas afetadas (existentes — sem alteração de schema)

### `persons`

| Coluna | Tipo | PII | Tratamento |
|--------|------|-----|-----------|
| `id` | INTEGER PK | Não | Inalterado |
| `name` | TEXT | Não | Inalterado |
| `identification_id` | TEXT | **CPF** | Anonimizado → `LGPD-{hmac[:16]}` |
| outros campos | — | Não | Inalterados |

**Deduplication behavior**: `identification_id` continua sendo usado para deduplicação. Hash determinístico preserva a propriedade de unicidade por titular.

---

### `person_emails`

| Coluna | Tipo | PII | Tratamento |
|--------|------|-----|-----------|
| `id` | INTEGER PK | Não | Inalterado |
| `person_id` | INTEGER FK | Não | Inalterado |
| `email` | TEXT | **E-mail** | Anonimizado → `{hmac[:12]}@anon.lgpd` |

---

### `external_research_groups`

| Coluna | Tipo | PII | Tratamento |
|--------|------|-----|-----------|
| `id` | INTEGER PK | Não | Inalterado |
| `contact_email` | TEXT | **E-mail** | Anonimizado → `{hmac[:12]}@anon.lgpd` |
| outros campos | — | Não | Inalterados |

---

## Entidade nova: `pii_anonymizer` (módulo, não tabela)

Localização: `src/core/logic/pii_anonymizer.py`

### Funções

```python
# Chave secreta — variável de ambiente, NUNCA versionada.
# (implementação: _load_hmac_key() lê os.environ["HORIZON_PII_HMAC_KEY"],
#  falha explicitamente se ausente; subchaves por domínio via HKDF-SHA256)
HMAC_KEY_ENV = "HORIZON_PII_HMAC_KEY"
DOMAIN_LABELS = {"cpf", "email", "phone", "free_text"}

def anonymize_cpf(value: str | None) -> str | None:
    """HMAC-SHA256 keyed determinístico. None/empty → None."""

def anonymize_email(value: str | None) -> str | None:
    """HMAC-SHA256 keyed determinístico. None/empty → None."""

def anonymize_phone(value: str | None) -> str | None:
    """HMAC-SHA256 keyed determinístico. None/empty → None."""

def anonymize_field(value: str | None, field_type: str) -> str | None:
    """Dispatcher: field_type in {'cpf', 'email', 'phone', 'free_text'}."""

def is_anonymized_cpf(value: str | None) -> bool:
    """True se começa com 'LGPD-'."""

def is_anonymized_email(value: str | None) -> bool:
    """True se termina com '@anon.lgpd'."""
```

### Invariantes

- `anonymize_cpf(x) == anonymize_cpf(x)` para qualquer `x` (determinismo com a MESMA chave)
- `anonymize_cpf(None) is None`
- `anonymize_cpf("")` retorna `None`
- Resultado de `anonymize_cpf` sempre começa com `"LGPD-"`
- Resultado de `anonymize_email` sempre termina com `"@anon.lgpd"`
- Nenhuma função é reversível sem a **chave secreta** (`HORIZON_PII_HMAC_KEY`); quem detém a chave consegue reproduzir o mapeamento
- Chave ausente → falha explícita (exceção), nunca fallback para hash sem chave

### Gestão da chave secreta (2026-09-21)

- **Geração**: `secrets.token_urlsafe(32)` (≥ 32 bytes) ou `openssl rand -base64 32`
- **Armazenamento**: `.env` local / secret manager; `.env.example` recebe apenas placeholder documentado
- **Rotação**: trocar a chave altera todos os tokens persistidos — política de longa duração, rotação coordenada e auditada (ver research.md Decision 8)
- **Perda**: sem a chave não é possível recomputar tokens nem re-anonimizar dados legados — manter cópia segura no secret manager

---

## Entidade nova: Log de Auditoria do Backfill (arquivo, não tabela)

Localização: `data/reports/lgpd_backfill_{timestamp}.json`

### Estrutura

```json
{
  "started_at": "2026-05-16T10:00:00Z",
  "completed_at": "2026-05-16T10:05:00Z",
  "status": "success",
  "tables": [
    {
      "table": "persons",
      "column": "identification_id",
      "field_type": "cpf",
      "total_rows": 1500,
      "already_anonymized": 0,
      "anonymized": 1500,
      "skipped_null": 23,
      "errors": 0
    },
    {
      "table": "person_emails",
      "column": "email",
      "field_type": "email",
      "total_rows": 3200,
      "already_anonymized": 0,
      "anonymized": 3200,
      "skipped_null": 0,
      "errors": 0
    }
  ],
  "total_anonymized": 4700,
  "total_errors": 0
}
```

---

## PII Column Registry (configuração interna)

Usado pelo backfill para schema discovery:

```python
PII_COLUMN_REGISTRY = {
    "identification_id": "cpf",
    "email": "email",
    "contact_email": "email",
}
```

Novas colunas PII são adicionadas aqui para cobertura automática no backfill.
