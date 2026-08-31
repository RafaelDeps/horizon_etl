# Data Model: Advisorship Canonical Values

Phase 1 output of `/speckit.plan`. Defines the domain entities, their fields, the
relationships used by this feature, and the data flow. The canonical export shape is
the contract documented in `contracts/advisorships-canonical.md`.

## Entities (domain-owned, from `research_domain`)

### Advisorship (existing — `research_domain/domain/entities/advisorship.py`)

Joined-table inheritance over `Initiative` (`advisorships` inherits `initiatives`).

| Column | Type | Meaning | This feature |
|--------|------|---------|--------------|
| `id` | Integer PK (FK initiatives.id) | canonical advisorship id | used as export `id` |
| `fellowship_id` | Integer FK fellowships.id | linked funding award | source of fallback name/sponsor |
| `type` | Enum(AdvisorshipType), nullable | academic level (Scientific Initiation, PhD Thesis, ...) | untouched (still NULL) |
| `program` | String(500), nullable | **program / category** (Pibic, Picti, Pivic, ...) | **FR-007: populated on new SigPesq ingestion**; read by export |
| `defense_date` | Date, nullable | dissertation defense date | untouched |
| `cancelled` / `cancellation_date` | Boolean / Date | cancellation state | untouched |

Provider deliberately has **no dedicated column**: the funding agency is already
captured by the linked `Fellowship.sponsor_id → Organization` when a fellowship
exists, and by the SigPesq payload `AgFinanciadora` otherwise. Exposing provider on
export is a read-time resolution, not a column addition (avoids schema change and
duplicated symbol).

### Fellowship (existing)

| Column | Meaning |
|--------|---------|
| `name` | UPPERCASE program display name (e.g., `PIBIC`) — distinct convention from report `Programa` |
| `sponsor_id` | FK organizations.id → provider (`Fapes`, `Ifes`, `Cnpq`, `Voluntário`) |

Only 506/3,199 advisorship rows link a fellowship; the export therefore cannot rely on
it (research.md §1).

### SourceRecord + EntityMatch (existing, schema of the ETL core)

- `source_records(id, source_system, source_entity_type='advisorship', source_path, raw_payload_json, ...)`
  - SigPesq payload keys read: `Programa`, `AgFinanciadora`, `Ano`, `Id` (all non-PII; payloads
    already LGPD-masked on write: emails/phones/CPF are `LGPD-...`/`@anon.lgpd`).
  - Lattes payload keys read: `year` (falls back to `end_year`/`start_year`).
  - `source_path` regex used for the report/directory year: `advisorships/(\d{4})/`.
- `entity_matches(canonical_entity_type='advisorship', canonical_entity_id=<a.id>, source_record_id, ...)`
  — joins source records to advisorship entities (3,808 records / 701 sigpesq + 3,107 lattes).

## Data flow

```text
SigPesq report row (Programa, AgFinanciadora, Ano)
   │  writing  (existing)                       └→ source_records.raw_payload_json  (LGPD-masked)
   │  NEW FR-007                                └→ advisorship.program  (fresh ingestions)
   ▼
advisorships_canonical.json  ←  CanonicalDataExporter.export_advisorships
       NEW: per advisorship → year | program | provider
   resolve: payload "Programa" → advisorship.program → fellowship.name  → null
            payload "AgFinanciadora" → fellowship sponsor → null
            dir-year (tie-break Ano; Lattes: year field)   → null
```

## Field rules (canonical advisorship object)

| New field | Type | Rule |
|-----------|------|------|
| `year` | int \| null | SigPesq: report/directory year (Ano tie-break); Lattes: payload year; else null |
| `program` | string \| null | report `Programa` trimmed (report spelling); Lattes/unknown → null |
| `provider` | string \| null | report `AgFinanciadora` trimmed; fellowship sponsor fallback; Lattes/unknown → null |

Determinism: when an advisorship has several SigPesq source records, the resolved
record is the one with `dir_year == payload Ano`, then latest `dir_year`; ties broken
by lowest `source_record.id`. Pure function over the loaded rows → unit-testable.

## Validation rules (from spec)

- Every `advisorships` row must appear in the export (parity, FR-004).
- If `program`/`provider`/`year` present in the source payload, the export must not
  emit null for SigPesq rows (SC-001..SC-003).
- No PII key may be read or emitted (FR-006).
- Additive fields only; existing keys unchanged (FR-005).