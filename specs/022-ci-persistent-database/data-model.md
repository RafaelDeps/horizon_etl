# Data Model: Persistent Database Between GitHub Actions Weekly Runs

No database table or export file changes. The entities below exist only in
the restore step and in its outcome file.

## Weekly run (read from GitHub)

| Field | Source | Use |
|---|---|---|
| `id` | `gh run list --json databaseId` | the run to download from |
| `created_at` | `createdAt` | reported; orders the candidates (newest first) |
| `head_sha` | `headSha` | reported: the code that wrote the database |
| `event` | `event` | reported (`schedule` or `workflow_dispatch`) |
| conclusion | `--status success` filter | only `success` is a candidate (FR-002) |
| branch | `--branch $GITHUB_REF_NAME` | only the run's own branch |

## Run artifact `weekly-etl-artifacts`

| Content | Restored? | Notes |
|---|---|---|
| `db/horizon.db` | yes | checked with `PRAGMA quick_check` before use |
| `data/raw/**` | yes | files are never compressed (after this spec); `X.zip` holding only `X` is extracted (older artifacts) |
| `cache/**` | yes | added to the upload by this spec |
| `data/exports/**`, `data/reports/**`, `data/lattes_json/**`, other `data/` folders | no | produced again by the run |

Expiry: `expired` flag of the artifacts API; retention 90 days after this
spec (30 before).

## Restore outcome (`data/reports/restore_outcome.json`)

```json
{
  "outcome": "restored",
  "reason": null,
  "source_run": {
    "id": 40856179199,
    "created_at": "2026-10-29T10:15:56Z",
    "head_sha": "4d93988...",
    "event": "workflow_dispatch"
  },
  "restored": {"db_bytes": 333447168, "data_raw_bytes": 233832448, "cache_bytes": 69206016},
  "checked_at": "2026-11-07T02:03:11Z"
}
```

| Field | Values |
|---|---|
| `outcome` | `restored`, `rebuilt` |
| `reason` | `null` when restored; otherwise one of `restore disabled`, `no successful run`, `artifact expired`, `download failed: <message>`, `database missing`, `database check failed: <message>` |
| `source_run` | the run restored from, or the run tried last when the restore failed after choosing one; `null` when none was found |
| `restored` | byte sizes of what was placed; zeros when rebuilt |
| `checked_at` | ISO-8601 UTC |

## States of one run's start

```text
fresh_database=true ──────────────────────────────► rebuilt (restore disabled)
find newest successful run with a live artifact
  ├─ none found ──────────────────────────────────► rebuilt (no successful run | artifact expired)
  └─ found ─► download
              ├─ fails ───────────────────────────► rebuilt (download failed)
              └─ ok ─► unzip compressed raw files
                       ─► check db
                          ├─ missing ─────────────► data/raw + cache placed, db rebuilt (database missing)
                          ├─ fails ───────────────► data/raw + cache placed, db rebuilt (database check failed)
                          └─ ok ──────────────────► restored (db + data/raw + cache placed)
then make weekly-flows: db-ensure (create if missing, else migrate)
                        → rule-version guard (spec 021) → phases
```

"Rebuilt" never fails the step: the step always exits 0 unless the module
itself crashes on a programming error, and even then the workflow step is
marked `continue-on-error` (contract workflow-steps.md).
