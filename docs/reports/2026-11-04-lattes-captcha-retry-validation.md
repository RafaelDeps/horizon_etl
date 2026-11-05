# Spec 025 validation: ask again for the Lattes access check pages

**Date**: 2026-11-04 | **Branch**: `028-lattes-captcha-retry` | **Spec**: `specs/025-lattes-captcha-retry/`

## 1. Why

Lattes sometimes serves its reCAPTCHA access check page instead of the
curriculum. Before this spec, such a curriculum was handled like this:

- a new one was not cached;
- a refresh kept its cached copy.

In both cases it was asked again only in the next weekly run, one week later.

The pages look random per request, not per person (research R3):

| Evidence | Value |
|---|---|
| Local run from scratch, 2026-11-03 | 38 of 435 requests (about 9%), spread from 16:02 to 16:23, 1 to 5 per minute, no rise towards the end |
| Curricula rejected on 2026-10-21 and asked again | only 3 of 27 rejected again |
| CI run 41057537912 (2026-10-30) | 31 of 426, with successes between them |

So a second request a few minutes later should mostly succeed. Spec 025 adds
that second request to the same run:
- it asks only for the curricula that got the access check page;
- it waits a pause first (5 min by default);
- it uses 1 worker by default;
- it counts towards the spec 024 stop;
- it never runs after a stop.

The CAPTCHA is never answered or bypassed.

## 2. Settings

| Setting | Environment | Makefile | Workflow input | Default |
|---|---|---|---|---|
| Workers of the second pass | `HORIZON_LATTES_RETRY_WORKERS` | `LATTES_RETRY_WORKERS` | `lattes_retry_workers` | 1 (0 = off) |
| Pause before it | `HORIZON_LATTES_RETRY_PAUSE_MIN` | `LATTES_RETRY_PAUSE_MIN` | `lattes_retry_pause_min` | 5 min |

- The first pass keeps 3 workers.
- A blank or invalid value gives the default and logs a warning.
- The workflow now has 11 inputs. GitHub's limit is 25 since 2025-12-04
  (research R6).

## 3. Tests

Full suite, `.venv/bin/python -m pytest -q` (2026-11-04):

| | Passed | Failed | Skipped |
|---|---:|---:|---:|
| After | 770 | 6 | 1 |

The same 6 tests fail before and after, for reasons that predate this spec:
- `test_download_lattes_flow.py` ×3: the chromedriver fakes;
- `test_loader_mapping.py`;
- `test_sigpesq_adapter.py` (HTTP 429);
- `test_weekly_etl_workflow.py`: the cron string.

New tests (38):

| File | Covers |
|---|---|
| `test_access_check_retry.py` (11) | defaults, blank, off, decimal minutes, invalid values, the given mapping |
| `test_lattes_access_check_retry.py` (18) | access check page told apart from other failures; new and refresh retried; caching and download date only on success; no second pass after a stop; shared stop count; pause and workers; the environment read when no settings are given |
| `test_portal_stops_report.py` (+4) | the `retries` key next to `stops`; missing or unreadable file; write errors logged; `retried_ids` kept out of a stop entry |
| `test_raw_rotation.py` (+1) | ` retried=N recovered=M` only when a second pass ran |
| `test_weekly_etl_workflow.py` (+2) | the two inputs and their mapping; the Makefile forwards them only when set |
| `test_weekly_orchestrator.py` (+2) | the `↻` line and the exit code kept; no line without a second pass |

`tests/conftest.py` sets `HORIZON_LATTES_RETRY_WORKERS=0` for every test, so
the spec 023 and spec 024 tests describe the download without the second pass
and pass unchanged (research R7). The spec 024 assertion on the number of
workflow inputs changed from `<= 10` to `<= 25`.

## 4. Local runs

**A) Lattes download, 2026-11-03** (T027,
`logs/lattes_download_2026-11-03_spec025_t027.log`). It ran with
`LATTES_RETRY_PAUSE_MIN=1` on a cache with some curricula missing. A backup
was made first, in `data/_backup_2026-11-03_pre_spec025_t027/`.

| | Value |
|---|---|
| First pass | 38 new and 100 refreshes; 6 access check pages (3 new, 3 refreshes), never 5 in a row |
| Second pass | 1 min pause, 1 worker, `6 of 6 recovered`, 111.9 s from the start of the pause |
| Downloads line | `new=38 refreshed=100 reused=297 failed=0 reused_after_failure=0 retried=6 recovered=6` |
| `portal_stops.json` | `retries.lattes` written, `stops` empty |
| Cache | all 435 curricula in `cache/` and in the manifest, 435 JSON files, none `Nome-nao-identificado` |

**B) Full weekly run, 2026-11-04** (`make weekly-flows`, run by the
maintainer):
- every phase ended with exit 0;
- the summary showed
  `↻ lattes: 7 access check pages asked again after 5 min; 7 recovered, 0 still missing`.

## 5. Fork runs (quickstart.md §3)

**A) First run of the branch, defaults:** run
[41729360132](https://github.com/RafaelDeps/horizon_etl/actions/runs/41729360132)
(2026-11-03, `da21d11`), success in 47 min. It rebuilt from scratch, with no
stored pages and only the 16 curricula tracked in `cache/`.

- GitHub accepted the 11 inputs.
- Both portals were blocking the runner:

| | CNPq | Lattes |
|---|---|---|
| Portal given up | timeouts, at 803 s | 8 access check pages in the first 11 requests, at 42 s |
| Counts | `new=105 failed=7 stopped=235` | `new=5 reused=13 failed=8 stopped=413` |

- No second pass, as FR-005 requires after a stop in the first pass, so no `↻` line.

**B) Defaults, normal rotation:** run
[41739712881](https://github.com/RafaelDeps/horizon_etl/actions/runs/41739712881)
(2026-11-03), success in 1 h 46 min, every phase exit 0. It restored the
database, `data/raw` and `cache/` from run A.

| | CNPq | Lattes |
|---|---|---|
| Portal given up | no | no |
| First pass | `new=242 refreshed=27 reused=78 failed=0` | 417 new asked with 3 workers; 69 access check pages (about 17%) |
| Second pass | — | 69 asked after 5 min with 1 worker; **55 recovered**, about 19 min including the pause |
| Downloads line | | `new=403 refreshed=5 reused=13 failed=14 reused_after_failure=0 retried=69 recovered=55` |

The summary showed:

```
↻ lattes: 69 access check pages asked again after 5 min; 55 recovered, 14 still missing
```

Without the second pass, those 55 curricula would have waited one week.

**C) Second pass off, `lattes_retry_workers=0`:** run
[41754550238](https://github.com/RafaelDeps/horizon_etl/actions/runs/41754550238)
(2026-11-04), success in 37 min, all 22 phases exit 0. It restored from run B.

- The job had `HORIZON_LATTES_RETRY_WORKERS: 0`.
- CNPq: `new=0 refreshed=87 reused=260 failed=0`.
- Lattes asked for the 14 still missing, then the refresh share. 24 came back
  as the access check page.
- No `Retrying …` line.
- The downloads line had the same format as before spec 025:
  `new=10 refreshed=86 reused=315 failed=24 reused_after_failure=20`, with no
  `retried=`/`recovered=`.
- No `↻` and no `⚠` line.

The 24 rejections of run C are the cost of having the pass off:
- 4 new curricula stayed missing;
- 20 refreshes kept their old copy until the next run.

**Not checked:** the Telegram message. The Telegram variables are empty in the
fork, so only the tests cover the Portuguese `🔁` line.

## 6. Other findings

- Every fork run committed its export zip to the branch: `bea2664`, `481024f`
  and `eeeda3c`. The zip of run B is 50.8 MB, over GitHub's recommended
  50 MB. GitHub only warned.
- `SQLite finalize failed: database is locked` appears at the end of every run
  in this report, locally and in CI, and before this spec too.
  - The data is complete: no `horizon.db-wal` was left behind, and
    `PRAGMA quick_check` returns `ok`.
  - The database stays in `wal` mode, though.
  - A connection is still open when the step runs. This is to be investigated
    next.

## 7. Residual risk

If the access check depends on the rate of requests from one IP, rather than
on chance, the second pass recovers fewer curricula. The CI runner's IP is
shared and limited more often:
- 17% of requests rejected in run B, against 9% locally;
- 55 of 69 recovered in run B, against 6 of 6 locally.

Even then, a curriculum that fails twice behaves exactly as before this spec:
- a new curriculum is not cached;
- a refresh keeps its copy;
- the next run takes them first (spec 023).

A portal that blocks in a row still triggers the spec 024 stop, and then there
is no second pass.
