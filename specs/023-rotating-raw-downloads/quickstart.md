# Quickstart: Download Only What Is New Plus a Rotating Share

## 1. Tests

```bash
.venv/bin/python -m pytest -q tests/test_raw_rotation.py tests/test_raw_store.py \
  tests/test_lattes_rotation.py tests/test_cnpq_rotation.py
```

## 2. Local check on frozen inputs

Use a scratch copy of `cache/`, `data/raw` and a database copy; never the real
`db/horizon.db` without the backup rule.

1. **First run.** Every CNPq group is new: about 350 pages are fetched and
   stored in `data/raw/cnpq/`. For Lattes, the cached curricula are undated,
   so a quarter of them (109) is refreshed by id order and dated.
2. **Second run.** CNPq fetches about 88 pages, the oldest quarter, and reuses
   the rest. Expect `downloads cnpq: new=0 refreshed=88 reused=262`, and the
   phase takes a fraction of the first run's time. Lattes refreshes the next
   109 undated curricula.
3. **Failed refresh.** Simulate it with a fake downloader that fails: the
   cache file and the date stay, and the count `reused_after_failure` goes up.
4. **Full refresh.** `HORIZON_FULL_REFRESH=1` downloads everything again.
5. **Provenance.** `source_document_states_canonical.json` has a
   `downloaded_at` for every document read in the run.

## 3. CI

Dispatch the weekly on the fork:

- **Runs 1 and 2.** Restored database (spec 022). The CNPq phase falls from
  about 16 min to about 5 min from the second run on.
- **Optional run.** `full_refresh: true` downloads everything once.

Measure with four consecutive runs that every curriculum and page got a new
date (SC-001).
