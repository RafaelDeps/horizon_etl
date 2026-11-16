# Data Model: PII-Safe Exports and Deduplicated Articles

No new tables, no rule-version change.

## Encrypted state bundle

File `weekly_state.bundle` in the run artifact.

| Part | Size | Content |
|---|---|---|
| Magic | 8 bytes | `HZSTATE1`; also the associated data |
| Nonce | 12 bytes | Random for each bundle |
| Ciphertext and tag | Rest | AES-256-GCM of a `tar.gz` |

Tar roots allowed: `db/horizon.db`, `data/raw/`, `cache/`. Files are byte-identical to the runner's copies. Any part may be absent.

States: `sealed`, `skipped: no key`, `failed` (over the size limit or an I/O error). None of them fails the run or uploads plain data.

## Restore outcome

`data/reports/restore_outcome.json` gains:

| Field | Values |
|---|---|
| `format` | `bundle`, `legacy`, or null when rebuilt with nothing placed |

New `reason` values: `state bundle: no key`, `state bundle: failed authentication`, `state bundle: unsafe member`, `database built with another key`.

## Archive manifest

`export_manifest.json` in the archive:

```json
{"official": true, "key_fingerprint": "16 hex characters"}
```

No `generated_at`, so it adds no change of its own. Rule: `official` is true only in GitHub Actions.

## `horizon_meta`

New key `pii_key_fingerprint`. Absent: accepted once, then stamped by the backfill. Different: the database is not restored.

## Reports

Counts only, never values. All go to `data/reports/`.

| File | Fields |
|---|---|
| `export_scan_report.json` | `files_scanned`, `seconds`, `matches: {file: {email, phone, cpf, known_field}}`, `left_out: [file]` |
| `database_verify_report.json` | `columns: [{table, column, kind, count}]`, `file_bytes_hits: {email, phone, cpf}`, `freelist_pages`, `vacuumed` |
| `article_consolidation_report.json` | `groups`, `rows_merged`, `skipped_conflicting_doi`, `ids_aliased` |
| `artifact_stage_report.json` | `state: sealed|skipped|failed`, `bundle_bytes`, `public_files`, `public_left_out: [file]` |

## Values changed in existing tables

Only rows holding plain data, one pass.

| Column | Change | Linked value |
|---|---|---|
| `initiatives.description` and other `description` columns | Scrubbed | None |
| `attribute_assertions.value_json` | Scrubbed | `value_hash = stable_hash(scrubbed)` |
| `entity_change_logs.before_json`, `after_json` | Scrubbed | None |
| `source_records.raw_payload_json` | Known fields tokenized | `payload_hash` unchanged, from the original payload by design |

Never changed: `source_document_states.content_hash`, `dependency_fingerprint`, `rule_version`.

## Published hashes

| Field | In the database | In the archive |
|---|---|---|
| `payload_hash` | Unkeyed, unchanged | HMAC of the stored hash |
| `value_hash` | Unkeyed, of the scrubbed value | HMAC of the stored hash |
| `content_hash` | Unkeyed, unchanged | Not published |

## Article

**Match** (ingest and consolidation):

1. Same `normalize_doi`, whatever the title.
2. Otherwise the same `normalize_text(title)`, non-blank, the same year, and DOIs not both present and different.

**Merge**: Survivor has the best `id_priority` of its id without suffix, then the lowest row id. Survivor's empty fields are filled, never overwritten.

**Repointed from the loser**: `article_authors`; `entity_matches`, `attribute_assertions`, `entity_change_logs` where `canonical_entity_type = 'article'`; `source_document_items` of types `article` and `article_author`.

**Permanent ids**:

| Old id | After |
|---|---|
| Survivor, no suffix | Unchanged |
| Survivor `X~a` | Survivor becomes `X`; `X~a` is a `merge` alias |
| Loser, any form | `merge` alias of the survivor |
| Article not in a merge | Unchanged |
| A suffixed id as a merge pool candidate | Never chosen as permanent |

## Secrets

| Secret | Purpose | Steps that receive it |
|---|---|---|
| `HORIZON_PII_HMAC_KEY` | Tokens, keyed hashes; unchanged | Job level, as today |
| `HORIZON_STATE_KEY` | Bundle; 32 random bytes in base64url | Restore and seal only |
| `HORIZON_STATE_KEY_PREVIOUS` | Optional, during rotation | Restore only |
