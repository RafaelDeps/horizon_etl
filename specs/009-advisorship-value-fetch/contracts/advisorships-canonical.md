# Contract: `advisorships_canonical.json` — advisorship entry

External interface consumed by the PH dashboards. Scope of feature
`009-advisorship-value-fetch` is limited to this artifact (decision Q3=C).

File: `data/exports/advisorships_canonical.json`
Shape: array of **project** groups; each group holds an `advisorships` array of the
objects documented here. A synthetic *"Sem Projeto Associado"* group collects orphans.

## Advisorship object

| Field | Type | Change | Meaning |
|-------|------|--------|---------|
| `id` | int | — | advisorship entity id |
| `name` | string | — | initiative title |
| `status` | string | — | `Active` / `Concluded` / `Cancelled` |
| `description` | string | — | e.g. `Programa: Pibic` (unchanged, legacy) |
| `start_date` / `end_date` | string\|null | — | ISO dates |
| `type` | string\|null | — | `advisorships.type` (academic level; currently always null) |
| `initiative_type` | string | — | `Advisorship` |
| `person_id` / `person_name` | int\|null / string\|null | — | student resolver output |
| `supervisor_id` / `supervisor_name` | int\|null / string\|null | — | supervisor |
| `campus` | string\|null | — | campus resolution |
| `fellowship` | object\|null | — | `{id, name, description, value, sponsor_name}` when linked |
| **`year`** | int\|null | **NEW** | report/directory year (SigPesq); payload year (Lattes); else null |
| **`program`** | string\|null | **NEW** | report `Programa` (e.g. `Pibic`, `Picti`, `Pivic`); Lattes → null |
| **`provider`** | string\|null | **NEW** | report `AgFinanciadora` (e.g. `Fapes`, `Ifes`, `Cnpq`, `Voluntário`); fellowship sponsor fallback; Lattes → null |

### Null semantics

`null` means the value is **absent from the source / not reported** (e.g. Lattes CVs
carry no program or funding agency — FR-008). It is never `"N/A"` and never a re-cased
value; report spelling is preserved (FR-001, SC-001).

### Additive change

Only `year`/`program`/`provider` are added (FR-005). All pre-existing keys keep
semantics and order; consumers that ignore unknown keys are unaffected.

### Determinism

When several SigPesq source records resolve to one advisorship, the winning record is
the one whose directory year equals its payload `Ano`, else the latest directory year;
ties broken by lowest `source_record.id`.

## Provenance (SC-004 / FR-004)

Every non-null `program`/`provider` value is backed by exactly one SigPesq source
record; `year` is attributed to that record's report directory.

- **Authority:** the per-row, per-year copy of the SigPesq report row stored in
  `source_records.raw_payload_json`, linked to the advisorship entity through
  `entity_matches` (`canonical_entity_type='advisorship'`,
  `source_entity_type='advisorship'`).
- **Trace path:** `advisorship.id` → `entity_matches` → `source_records` → the row's
  `Programa` (`program`), `AgFinanciadora` (`provider`) and report-directory year
  `source_path` → `.../advisorships/YYYY/...` (`year`, payload `Ano` as tie-break).
  Lattes-sourced records carry no program/provider (→ `null`); their `year` comes from
  the CV's own year field.
- **How to verify:** for each advisorship in the artifact with non-null `program` or
  `provider`, the backing `source_records` row must exist, belong to the
  `sigpesq_advisorships` system, have `source_entity_type='advisorship'`, a report
  directory matching `advisorships/(\d{4})/`, and a payload `Ano`. No non-null category
  may exist without such a record. `src/scripts/audit_advisorship_category_provenance.py`
  automates this check (non-zero exit on findings).
- **Determinism note:** the winning source record is fixed (see Determinism above); the
  resolver also exposes `source_record_id` programmatically for auditing, though the
  artifact itself only carries the resolved `year`/`program`/`provider`.

## Minimal example

```json
{
  "id": 86,
  "name": "Pivic Análise de dados para detecção de evasão",
  "status": "Concluded",
  "description": "Programa: Pivic",
  "start_date": "2016-08-01",
  "end_date": "2017-07-31",
  "type": null,
  "initiative_type": "Advisorship",
  "person_id": 123,
  "person_name": "LGPD-MASKED",
  "supervisor_id": 45,
  "supervisor_name": "Karin Satie Komati",
  "campus": "Serra",
  "fellowship": { "id": 3, "name": "PIVIC", "description": "Programa: Pivic", "value": 400.0, "sponsor_name": "Voluntário" },
  "year": 2016,
  "program": "Pivic",
  "provider": "Voluntário"
}
```

## LGPD (FR-006)

The three new fields are non-PII (`Programa`, `AgFinanciadora`, advisory year). Raw
payloads used to resolve them are already masked on write; no email/phone/CPF key is
read from or written to this artifact.