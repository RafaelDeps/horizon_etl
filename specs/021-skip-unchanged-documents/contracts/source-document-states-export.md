# Contract: `source_document_states_canonical.json`

Written by `export_canonical` into the output directory (`data/exports/` by
default), next to the spec 020 files, and therefore included in
`exports_canonical.zip` by the existing walk. **No existing export file
changes** (FR-016).

```json
{
  "rule_version": 1,
  "generated_at": "2026-11-07T04:12:09Z",
  "documents": [
    {
      "source_system": "cnpq_group",
      "document_key": "4439471564090237",
      "status": "active",
      "last_seen_at": "2026-11-07T03:10:44Z",
      "processed_at": "2026-10-31T03:12:02Z"
    },
    {
      "source_system": "lattes_projects",
      "document_key": "9860697624155451",
      "status": "inactive",
      "last_seen_at": "2026-10-24T02:58:11Z",
      "processed_at": "2026-10-24T02:58:11Z"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `source_system` | `lattes_projects`, `lattes_advisorships`, `cnpq_group`, `sigpesq_project`, `sigpesq_advisorship`, `sigpesq_group` (no `sigpesq_pj`: the enrichment phase is out of this spec) |
| `document_key` | Source-native key: `lattes_id`, CNPq group id (16 digits), SigPesq project/workplan/group key. All already published in other exports |
| `status` | `active`: present in its source's last complete listing. `inactive`: absent from it; its data is still in the database and in the other exports |
| `last_seen_at` | ISO-8601 UTC of the last run whose complete listing contained the document |
| `processed_at` | ISO-8601 UTC of the last successful processing; `null` if never processed successfully (for example a CV that has always been unreadable) |

Rows are sorted by `source_system`, then `document_key`, so two exports of the
same state are identical apart from `generated_at` and the dates.

**How a consumer uses it**: to tell current data from data no longer confirmed
by its source, join `document_key` to the entity's source id (for example
`lattes_id` in `horizon_ids_canonical.json`'s `person:lattes:<id>`, or
`group:cnpq:<id>`).

**Not exported**: `content_hash`, `dependency_fingerprint`, references, item
links and failure details. They are internal bookkeeping; the failures are in
`data/reports/source_document_states_report.json`.

**Privacy**: keys, statuses and dates only. No name, CPF, phone or e-mail
(FR-017).

**Parquet**: `src/scripts/export_parquet.py` converts it with `documents` as
the row list and no integer id column.

**Spec 023**: the file gains the field `downloaded_at` (the date of the
download a document's data comes from); see
[`specs/023-rotating-raw-downloads/contracts/states-export-v2.md`](../../023-rotating-raw-downloads/contracts/states-export-v2.md).
