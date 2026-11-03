# Spec 024 validation: stop downloading when a portal blocks

**Date**: 2026-10-30 | **Branch**: `027-portal-early-stop` | **Spec**: `specs/024-portal-early-stop/`

## 1. Why

In CI run [40966298828](https://github.com/RafaelDeps/horizon_etl/actions/runs/40966298828)
(2026-10-29) the CNPq portal hung:

- Every page attempt took about 95 s, which is the library's 3 navigations
  of 30 s each.
- The phase hit its 10,800 s limit before its writer reached the stored
  pages, so it wrote nothing.
- The whole run took 3 h 40 min.

Spec 024 gives a portal up and finishes from the stored copies of spec 023.

**CNPq** stops when either of these happens:
- 8 failed attempts in a row;
- 45 min of downloads.

**Lattes** stops after 5 requests in a row that fail or return the access
check page.

## 2. Defaults checked against the CI logs

| Evidence | Value |
|---|---|
| Run 40966298828: 8th failed CNPq attempt | +4 min 49 s into the phase |
| Run 40966298828: 8th page with all its retries failed | +27 min (why the rule counts attempts) |
| 7 healthy runs (2026-10-28 and 2026-10-29): failed CNPq attempts | 1 in 2,224 |
| 7 healthy runs: Lattes download failures | at most 1 per run |
| Healthy CNPq full download (350 pages) | 15 min 22 s and 24 min 50 s |
| Run 40966298828: Lattes access check pages | 23 of 109, interleaved with the 86 successes |

None of the defaults triggers on a healthy run. On run 40966298828 the
Lattes rule would most likely not have triggered either: 23 rejections
interleaved with 86 successes give about a 3% chance of 5 in a row. That is
intended, because the portal was limiting, not blocking (research R3).

## 3. Tests

Full suite, `.venv/bin/pytest -q`:

| | Passed | Failed |
|---|---:|---:|
| Before (baseline) | 675 | 6 |
| After | 733 | 6 |

The same 6 tests fail before and after, for reasons that predate this spec:
- `test_download_lattes_flow.py` ×3: the chromedriver fakes;
- `test_loader_mapping.py`;
- `test_sigpesq_adapter.py` (HTTP 429);
- `test_weekly_etl_workflow.py`: the cron string.

New tests (58):

| File | Covers |
|---|---|
| `test_portal_stop.py` (25) | the rule, its settings and the switch; thread safety |
| `test_portal_stops_report.py` (6) | the report file |
| `test_cnpq_early_stop.py` (10) | the fetch and the phase: down, recovering, budget, stored pages, healthy result identical with the stop off |
| `test_lattes_early_stop.py` (9) | blocking, 3 workers, block from the 4th request, interleaved, shared count, next rotation, off, custom limit, healthy result identical |
| `test_weekly_orchestrator.py` (+4) | the summary and Telegram lines, a stale report cleared, the exit code kept |
| `test_weekly_etl_workflow.py` (+2) | the workflow inputs and the Makefile variables |
| `test_raw_rotation.py` (+2) | the `stopped` counts |

One existing test changed: `test_cnpq_rotation.py::test_a_failed_fetch_uses_the_stored_page`.
It simulates a portal that is down for all 8 pages and checks that each page
falls back to its stored copy. It now sets `HORIZON_PORTAL_EARLY_STOP=0`,
since with the stop on not every page would be tried. Every other spec 017
and spec 023 test passes unchanged.

## 4. Local replay on the database of run 40966298828

The CI artifact of run 40966298828 (database plus 347 stored pages) was
downloaded into the scratchpad. The real `db/horizon.db` and `data/` were not
touched.

**A) Hung portal (fake):** every attempt waits 3 s and returns nothing. This
is accelerated from the real 95 s.

| | Value |
|---|---|
| Portal given up | after 9 s, at 8 failed attempts (`failures_in_a_row`) |
| Phase time | **24 s** |
| Counts | `refreshed=0 reused=339 failed=8 reused_after_failure=8 stopped=79` |
| Documents | `processed=0 skipped=350 failed=0`: every group kept its data |
| Database | identical apart from the usual `last_seen_at` of the skipped documents and one `ingestion_runs` row; `downloaded_at` kept the stored pages' date (2026-10-29) |
| `portal_stops.json` | written with the reason, limit and counts |

At the real 95 s per attempt, the same sequence matches the CI timeline of
section 2: the stop comes at about 5 min, and the phase ends in about 8 to
10 min. Without spec 024 it ran 3 h and wrote nothing.

**B) Real portal with a 30 s budget** (`HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN=0.5`):

| | Value |
|---|---|
| Portal given up | at 32.6 s (`time_budget`), after 10 successes |
| Requests | 13; the attempts in flight finished |
| Phase time | 58 s |
| Counts | `refreshed=13 reused=334 stopped=74 failed=0` |
| Documents | `skipped=350`, nothing failed |

The run found one thing to fix: two groups share a CNPq URL, so a page not
tried was counted twice in the `not_tried` log value. It now counts each id
once, as the `stopped` count already did.

## 5. Fork runs (quickstart.md §3)

**A) Healthy, defaults:** run
[41057537912](https://github.com/RafaelDeps/horizon_etl/actions/runs/41057537912)
(2026-10-30, `9cdd8ce`), success in 1 h 44 min. It was the branch's first
run, so it had no previous run to restore and rebuilt from scratch.

| | CNPq | Lattes |
|---|---|---|
| Portal given up | no | no |
| Counts | `new=347 failed=0` | `new=391 refreshed=4 reused=9 failed=31` |
| Phase time | 21 min | 28 min |

- No `portal given up` line and no `⚠` line in the summary.
- The 31 Lattes failures were access check pages, 7% of 426 requests. They
  came between 13:10 and 13:35, with successes between them, never 5 in a
  row. So the rule did not trigger, as intended (research R3).
- Those 31 curricula had no stored copy yet, so they have no data in this
  run. The next run takes them first as new (spec 023).
- Every phase ended with exit 0.
- `SQLite finalize: database is locked` also appears in runs 40959876147 and
  40934866237. It predates this spec.

**B) Forced, `cnpq_budget_min=1` and `lattes_stop_after=1`:** run
[41082380552](https://github.com/RafaelDeps/horizon_etl/actions/runs/41082380552)
(2026-10-30), success in 29 min. It restored the database, `data/raw` and
`cache/` from run A, so it was a normal rotation.

| | CNPq | Lattes |
|---|---|---|
| Portal given up | `time_budget`, limit 60 s, at 60.8 s; 24 successes, 0 failures | `failures_in_a_row`, limit 1, at 9.1 s; 1 access check page |
| Counts | `refreshed=27 reused=320 failed=0 stopped=60` | `new=1 refreshed=0 reused=404 failed=2 stopped=129` |
| Not tried | 60, processed from their stored pages | 129 (28 new, 101 refreshes), taken first by the next run |
| Phase time | 1 min 13 s | 1 min 56 s |

The weekly summary showed:

```
⚠ cnpq: portal given up (time_budget, 1 min) after 61 s; 60 not tried, 320 from stored copies, 0 failed
⚠ lattes: portal given up (failures_in_a_row, limit 1) after 9 s; 129 not tried, 404 from stored copies, 2 failed
```

- The weekly did not fail: every phase ended with exit 0.
- Lattes `failed=2` and `new=1` with a limit of 1: with 3 workers, the 2 other
  requests were already in flight at the stop and finished (one failed, one
  succeeded). This is within the 3-worker test bound.
- The `⚠` lines are read from `portal_stops.json`, so the file was written.
- **Not checked:** the Telegram message. The Telegram variables are empty in
  the fork, so only the tests cover the Portuguese line.

## 6. Residual risk

A navigation that hangs past the library's own timeout would still hold the
phase until the 10,800 s limit. No log shows one so far. It is recorded as
TD-030 in `docs/backlog.md`.
