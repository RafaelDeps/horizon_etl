# Research: Anonimização de Dados Pessoais (LGPD)

**Branch**: `001-lgpd-pii-anonymization` | **Date**: 2026-05-16

**Updated**: 2026-09-21 — **Security review**: Decision 3 substituída (HMAC-SHA256 com chave secreta no lugar de SHA-256 + salt público); adicionada Decision 8 (gestão da chave secreta).

## Decision 1: Ponto de aplicação da anonimização

**Decision**: Aplicar anonimização na **camada de loader/strategy** (`src/core/logic/`), imediatamente antes de passar dados ao controller do domínio.

**Rationale**: 
- Segue a arquitetura ports & adapters: lógica pura em `core/logic/`, sem tocar em `adapters/`
- `researcher_creation.py` é o ponto de entrada central para `identification_id` — centraliza a mudança
- `_ensure_person_emails()` em `researcher_creation.py` é o único ponto de escrita em `person_emails.email`
- `external_research_groups.contact_email` escrito via exporter — tratar separadamente

**Alternatives considered**:
- Adapter de banco — rejeitado: acoplaria a lógica de negócio ao adapter
- Export layer only — rejeitado: dados ficam em claro no banco (risco de acesso direto)

## Decision 2: Anonimização determinística não quebra deduplicação

**Decision**: Hash determinístico em `identification_id` é **compatível com a lógica de deduplicação existente**.

**Rationale**:
- `duplicate_auditor.py`, `person_matcher.py` e `person_consolidator.py` usam `identification_id` para identificar a mesma pessoa
- Com hash determinístico: mesmo CPF → mesmo hash → deduplicação por hash ainda funciona
- Dois registros com o mesmo CPF terão o mesmo `identification_id` anonimizado → sistema continua identificando corretamente

**Implications**: Nenhuma mudança necessária no código de deduplicação.

## Decision 3: Algoritmo de anonimização (REVISED 2026-09-21)

**Decision (original, 2026-05-16)**: `SHA-256(value.encode("utf-8") + b":horizon-lgpd-v1")`, primeiros 16 chars do hexdigest — **SUPERSEDED** pela revisão de segurança abaixo.

**Decision (security review, 2026-09-21)**: **HMAC-SHA256 keyed** — `hmac.new(subchave, value.encode(), hashlib.sha256).hexdigest()`, truncado para o token de exibição, com separação de domínio por tipo de campo (CPF/e-mail/telefone/texto-livre).

**Rationale**:
- O salt fixo anterior era **público no repositório** — qualquer leitor reconstruía o mapeamento por brute-force (CPF ~10¹¹ combinações; e-mail via dicionários/breaches). Segurança por obscuridade, não criptografia.
- HMAC com **chave secreta de ambiente** (`HORIZON_PII_HMAC_KEY`): sem a chave, o atacante não consegue verificar candidatos nem pré-computar rainbow tables, mesmo conhecendo o algoritmo, o formato e o domínio dos valores (princípio de Kerckhoffs).
- Determinístico com a mesma chave → deduplicação (Decision 2) e idempotência dos guards (`LGPD-` / `@anon.lgpd`) preservadas.
- Sem dependências externas: `hmac` + `hashlib` são stdlib do Python.

**Construction**:
- Chave maestra única: `HORIZON_PII_HMAC_KEY` (gerada com `secrets.token_urlsafe(32)`; ≥ 32 bytes de entropia).
- Subchaves por domínio via HKDF-SHA256 com labels `"cpf"`, `"email"`, `"phone"`, `"free_text"` → o mesmo valor string em campos distintos não gera o mesmo token (substitui os salts distintos por campo, preservando o comportamento atual de `PHONE_SALT`).
- Formatos persistidos (inalterados):
  - CPF (`identification_id`): `LGPD-{hmac[:16]}`
  - E-mail (`email`, `contact_email`): `{hmac[:12]}@anon.lgpd`
  - Telefone (texto-livre/scrub): `LGPD-PHONE-{hmac[:16]}`
- Ausência da chave → falha explícita (exceção), nunca fallback sem chave.

**Alternatives considered**:
- Manter SHA-256 + salt público — REJEITADO: reversível por qualquer leitor do repo; viola o objetivo de tratamento de PII (LGPD art. 5)
- bcrypt/argon2 — rejeitado: projetados para serem lentos (backfill lento) e não precisamos de trabalho extra quando a chave é secreta
- Format-preserving encryption (FPE) — rejeitado: requer biblioteca externa e manutenção de chave de reversão
- RSA determinístico (textbook) — rejeitado: saída longa, esquema determinístico desencorajado, e sem ganho sobre HMAC para tokenização determinística com reversão restrita a quem detém a chave

## Decision 4: Escopo de tabelas via schema discovery

**Decision**: Descoberta automática via `PRAGMA table_info()` filtrando colunas com nomes em lista fixa de PII column names.

**PII column names conhecidos** (confirmado por análise do schema):
- `identification_id` → tipo CPF
- `email` → tipo e-mail
- `contact_email` → tipo e-mail

**Rationale**: Schema discovery garante que novas tabelas adicionadas no futuro sejam cobertas automaticamente pelo backfill, sem alterar o código.

**Tables currently in scope**:
- `persons.identification_id`
- `person_emails.email`
- `external_research_groups.contact_email`

## Decision 5: Backfill como Prefect flow

**Decision**: `src/flows/maintenance/anonymize_backfill.py` — Prefect flow com Telegram hook.

**Rationale**:
- Segue constitution III (Prefect Flow Orchestration NON-NEGOTIABLE)
- Telegram hook notifica conclusão/falha automaticamente
- Flow é idempotente: registros já anonimizados (prefixo `LGPD-` / sufixo `@anon.lgpd`) são pulados
- Exposto via `make anonymize-backfill`

## Decision 6: Idempotência do backfill

**Decision**: Backfill verifica se valor já está anonimizado antes de processar.

**Check**: 
- `identification_id` → começa com `LGPD-` → pular
- `email`/`contact_email` → termina com `@anon.lgpd` → pular

**Rationale**: Permite re-executar backfill com segurança sem duplicar processamento ou corromper dados já conformes.

## Decision 7: Telefone fora do escopo atual

**Decision**: Telefone não existe como coluna no banco atual — escopo confirmado como CPF + e-mail.

**Rationale**: Análise do schema `PRAGMA table_info()` em todas as 40 tabelas não encontrou coluna `phone` ou `telefone`. O campo telefone não é persistido no banco Horizon ETL atual.

**Follow-up**: Se telefone for adicionado ao schema no futuro, adicionar `phone`/`telefone` à lista de PII column names no anonymizer.

## Decision 8: Gestão da chave secreta (adicionada 2026-09-21)

**Decision**: A chave de anonimização (`HORIZON_PII_HMAC_KEY`) é **variável secreta de ambiente** — provisionada localmente em `.env` (ignorado pelo git) ou em secret manager; um placeholder documentado fica em `.env.example` sem valor real.

**Rationale**:
- A segurança do esquema HMAC repousa integralmente no segredo (Kerckhoffs); versionar a chave no repo anularia a mudança
- `python-dotenv` já é usado pelo projeto — carregar a chave no boot é consistente com o padrão atual
- Fraco/omitida → falha explícita: melhor um sistema que pare do que um que "anonimiza" com material público

**Provisioning**:
- Geração: `python -c "import secrets; print(secrets.token_urlsafe(32))"` (ou `openssl rand -base64 32`)
- Armazenamento: `.env` local / secret manager (cópia segura — perda da chave impede recomputar tokens e re-anonimizar dados legados)
- Checagem no boot/core: `_load_hmac_key()` lê `os.environ["HORIZON_PII_HMAC_KEY"]`; ausente → `RuntimeError` explícito

**Rotation**:
- HMAC keyed: trocar a chave altera TODOS os tokens persistidos e quebra o determinismo histórico (valores antigos não correspondem aos novos)
- Política: chave de **longa duração**, rotacionada somente de forma coordenada (janela de manutenção, re-anonimização completa e consistente) e com registro no log de auditoria
- Não há versionamento de chave previsto no MVP; se rotação frequente for exigida no futuro, adotar `HORIZON_PII_HMAC_KEY_{version}` + verificação dupla na validação de `is_anonymized_*`
