# Data Model: Download Only What Is New Plus a Rotating Share

## Lattes download manifest — `data/raw/lattes/download_manifest.json`

```json
{
  "version": 1,
  "downloads": {
    "0059221043399777": "2026-11-05T02:41:10Z",
    "0061058205075393": "2026-10-29T13:52:03Z"
  }
}
```

| Rule | |
|---|---|
| Key | 16-digit Lattes id |
| Value | ISO-8601 UTC of the last **successful** download of `cache/<id>` |
| Missing key | the cached curriculum is undated (counts as the oldest) |
| Unreadable file | every cached curriculum is undated; the file is rebuilt at the end of the run |
| Write | atomic (temporary file + `os.replace`) after each refresh batch and at the end |
| Removed ids | kept (their cache file stays; spec 021 marks the documents inactive) |

## Stored CNPq page — `data/raw/cnpq/<CNPq group id>.json`

```json
{
  "group_id": "4439471564090237",
  "url": "http://dgp.cnpq.br/dgp/espelhogrupo/4439471564090237",
  "downloaded_at": "2026-11-05T02:12:44Z",
  "page": { "...": "the payload dgp_cnpq_lib returned" }
}
```

| Rule | |
|---|---|
| Name | the 16-digit id from the mirror URL (the spec 021 document key without `cnpq:`) |
| Written | only after a fetch returned data; atomic replace |
| Invalid / empty `page` | treated as no stored page |
| Groups without a valid mirror URL | never fetched (spec 017) and never stored |

## Rotation (`src/core/logic/raw_rotation.py`)

Input: listed ids (in source order), `dates` (`id -> date | None` for stored
ids), `share` in (0, 1], `full` bool.

| Output | Rule |
|---|---|
| `new` | listed ids with no stored copy |
| `refresh` | `full`: every stored listed id; else the `ceil(share × n_stored)` stored listed ids sorted by `(date is not None, date, id)` |
| `reuse` | stored listed ids not in `refresh` |

The output is deterministic and is processed in the listed order (the writer
loop's order is unchanged).

## `source_document_states.downloaded_at` (migration `0012`)

| Column | Type | Rule |
|---|---|---|
| `downloaded_at` | TEXT, NULL | ISO-8601 UTC of the content the document was last read from: the Lattes manifest date, the CNPq page date, or the SigPesq report file time. NULL until the first run after this spec reads the document. |

Updates:

| Outcome | `downloaded_at` |
|---|---|
| processed | written with the state |
| skipped | updated only if the date differs (a refreshed unchanged item) |
| failed | unchanged |
| reused unchanged item | same date → nothing written |

## Download counts (log and phase report)

| Field | Meaning |
|---|---|
| `new` | downloaded for the first time |
| `refreshed` | stored copy replaced by a successful new download |
| `reused` | stored copy used without a download |
| `failed` | download attempted and failed |
| `reused_after_failure` | of `failed`, the ones processed from their stored copy |
| `failed_ids` | ids of `failed` |
