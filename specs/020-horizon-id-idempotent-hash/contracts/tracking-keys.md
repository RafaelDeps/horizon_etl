# Contract: tracking keys and payload hash

`source_records` keeps its columns and its unique index
(`source_system`, `source_entity_type`, `source_record_id`, `payload_hash`).
Only the values of `source_record_id` and `payload_hash` change, for every
tracked type, as below. A key never contains a database id (FR-018).

## Keys

`n(x)` = `normalize_text(x)`; parts joined with `|`. `<cv>` = the 16-digit
`lattes_id` from the CV file name. `<cnpq>` = the CNPq group id from the
`espelhogrupo` URL.

| source_system / type | `source_record_id` |
|---|---|
| `cnpq_sync` / `cnpq_group_payload` | `cnpq:<cnpq>` |
| `cnpq_sync` / `cnpq_group_member` | `cnpq:<cnpq>\|n(name)\|n(role)\|n(data_inicio)\|n(data_fim)` |
| `cnpq_sync` / `cnpq_research_line` | `cnpq:<cnpq>\|n(line name)` |
| `lattes_projects` / `researcher_profile` | `<cv>` (unchanged) |
| `lattes_projects` / `academic_education` | `lattes:<cv>\|n(course)\|n(degree)\|n(start)\|n(end)\|n(institution)` |
| `lattes_projects` / `article` | `lattes:<cv>\|` + (DOI, or `n(title)\|year`) + `\|n(type)\|n(venue)\|n(volume)\|n(pages)` |
| `lattes_projects` / `initiative` | `lattes:<cv>\|<current identity key>` |
| `lattes_advisorships` / `advisorship` | `lattes:<cv>\|<current identity key>\|n(type)\|n(institution)` |
| `sigpesq_*` / all | unchanged (SigPesq codes, normalized group name) |
| `sigpesq_project_files` / `initiative` | unchanged (`PJ <code>`) |

## Same-document duplicates (FR-020)

Within one document (one CV, one CNPq page, one SigPesq report), items of the
same type with the same key are reduced to the one with the smallest
canonical payload hash before being processed. The run log counts them
(22 expected on the 2026-10-24 inputs).

## Payload hash (FR-021)

`payload_hash = sha256(json.dumps(canonical(payload), sort_keys=True, ensure_ascii=False))`

`canonical`: `None`, NaN, `"nan"`, `"NaN"`, `"None"`, `""` → `None`; integral
float → int; every scalar → `str(v).strip()`; applied recursively to dicts and
lists. `600`, `600.0` and `"600"` hash the same. The hash is still taken from
the payload before PII scrubbing (as today), so it stays stable when the
scrubber changes, and only the stored JSON is scrubbed.

## Idempotency

For identical inputs on a populated database, a second run must produce:

| Table | New rows | Changed rows |
|---|---:|---:|
| `source_records` | 0 | 0 |
| `entity_matches` | 0 | 0 |
| `attribute_assertions` | 0 | 0 |
| `entity_change_logs` | 0 | — |
| `team_members` | 0 | 0 |
| every core entity table | 0 | 0 |

Only `ingestion_runs` gains its run row.
