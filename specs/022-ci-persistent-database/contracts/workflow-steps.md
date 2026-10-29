# Contract: changes to `.github/workflows/weekly-etl.yml`

Order of the job's steps after this spec (new or changed ones marked):

| # | Step | Change |
|---|---|---|
| 1 | Checkout repository | — |
| 2 | Set up Python | — |
| 3 | Create virtual environment and install dependencies | — |
| 4 | Install Playwright Chromium | — |
| 5 | Install Chromium for Lattes (Selenium) | — |
| 6 | Validate required secrets | — |
| 7 | **Restore previous weekly run** | new: `make restore-weekly`, with `GH_TOKEN: ${{ github.token }}`, `continue-on-error: true`; runs `--disabled` when `inputs.fresh_database` is true |
| 8 | Run weekly flows (`make weekly-flows`) | — (its `db-ensure` creates the database when the restore placed none) |
| 9 | Compress large export files | changed: `find data/ -type f -size +10M ! -name '*.zip' ! -path 'data/raw/*' ...` |
| 10 | Commit exports_canonical.zip if changed | — |
| 11 | Upload ETL artifacts | changed: `cache` added to `path`; `retention-days: 90` |
| 12 | Show Prefect logs on failure / Stop Prefect server | — |

## New dispatch input

```yaml
fresh_database:
  description: "Ignore the previous run's database and rebuild from scratch."
  required: false
  default: false
  type: boolean
```

Scheduled runs have no inputs, so they always restore.

## Step 7

```yaml
- name: Restore previous weekly run
  continue-on-error: true
  env:
    GH_TOKEN: ${{ github.token }}
    FRESH_DATABASE: ${{ github.event.inputs.fresh_database }}
  run: make restore-weekly
```

`make restore-weekly` runs the module with `--github`, or `--disabled` when
`FRESH_DATABASE` is `true`.

## Unchanged

- `permissions` (`contents: write`, `actions: write`), the concurrency group
  per ref (two runs of one branch never overlap), `timeout-minutes: 300`, the
  secrets, and the commit of `exports_canonical.zip`.
- What the artifact holds besides `cache/`: the whole `data/` (minus the zip)
  and `db/horizon.db`.
