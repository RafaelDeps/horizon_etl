# Research: Stop Downloading When a Portal Blocks

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-30

Evidence comes from the logs of the fork's weekly runs, read with
`gh run view <id> --log`:

- run 40966298828: the CNPq outage;
- seven healthy runs: 40681064165, 40856179199, 40882304674, 40914744437,
  40934866237, 40952053776 and 40959876147.

## R1. What counts as a CNPq failure: an attempt, not a page

**Decision**: the failures-in-a-row count goes up by one for each failed ETL
attempt (`fetch_with_retries`, one call to `get_group_data`), and down to zero
on any successful attempt. It does not count whole pages after all their
retries.

**Rationale**: in run 40966298828 every attempt took about 95 s: the library's
3 navigations with a 30 s timeout each. A page failed its 3 ETL attempts
after about 6.8 min, counting the 30 s and 90 s back-offs. With the gate at 2
slots, the timeline was:

| Moment (phase start 22:33:32) | Failed attempts | Failed pages |
|---|---:|---:|
| 22:35:12 (+1 min 40 s) | 4 | 0 |
| 22:36:47 (+3 min 15 s) | 7 | 0 |
| 22:38:21 (+4 min 49 s) | **8** | 0 |
| 22:44:40 (+11 min) | 15 | 2 |
| 23:00:24 (+27 min) | 30 | **8** |

- **8 failed attempts:** downloading stops about 5 min into the phase. The
  attempts in flight end within about 95 s, and the 87 groups are then read
  from storage. A rotation with 87 stored pages took 3.5 min end to end in
  run 40959876147. The phase therefore ends in about 8 to 10 min, inside
  SC-001's 15 min.
- **8 failed pages:** the stop would come at 27 min, against SC-001.

**Healthy runs**: across the seven runs there were 2,224 attempts and one
failure. Run 40934866237 had one retried page; no run had more. Eight
failures in a row never happened.

**Alternatives considered**:
- **Whole pages after their retries:** too slow; see the table.
- **Failures within a time window, like the gate's burst rule:** it does not
  tell "the portal is down" from "a burst of resets". The gate already
  handles bursts by lowering the concurrency. "In a row with no success" says
  the portal answers nothing.
- **Counting the library's internal navigations:** not visible from the ETL;
  the adapter swallows them. The library stays unchanged.

## R2. The time budget: 45 min of downloads per phase

**Decision**: a deadline of `HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN` (default 45)
minutes. It starts when the first page download starts, and is checked
before every attempt and at the end of every back-off. Past the deadline,
no attempt starts, and the attempts in flight end as they would.

**Rationale**: the CNPq download windows in the healthy runs were:

| Run | Pages downloaded | First to last request |
|---|---:|---:|
| 40959876147 (rotation) | 87 | 3 min 28 s |
| 40914744437 (full, spec 022) | 350 | 15 min 22 s |
| 40934866237 (full, first spec 023 run) | 350 | 24 min 50 s |

Even the slowest full download has 1.8× margin. A portal that answers, but
slowly enough to pass 45 min, is degraded; the stored pages are the better
data then. The deadline covers what R1 does not: failures mixed with
occasional successes, or attempts that end slowly.

**Alternatives considered**:
- **No budget:** a slow portal with a few successes could still use the
  whole 3 h.
- **A budget per page:** the library's 30 s navigation timeout already
  bounds each attempt.
- **Lowering the orchestrator's 10,800 s phase timeout:** a killed phase
  writes nothing, which is the problem this spec solves; the timeout stays
  as the last guard.

## R3. Lattes: 5 failures in a row, counted across new and refreshed curricula

**Decision**: one counter per run, shared by the download of new curricula
(`prefetch_lattes_cache`) and the refresh (`refresh_lattes_cache`). A request
that raises, or that returns the access check page, counts as a failure; a
cached or kept curriculum page resets the counter. At
`HORIZON_LATTES_STOP_AFTER_FAILURES` (default 5), no further request starts.

**Rationale**:
- **Healthy runs:** at most one Lattes failure per run; none would trigger.
- **Run 40966298828:** 23 of 109 refreshes returned the access check page,
  between 01:33:48 and 01:40:42. They were interleaved with the 86 successes,
  which the log does not time, so the exact run lengths are unknown. At a
  21% rejection rate, the chance of 5 in a row somewhere in 109 requests is
  about 3%. The rule most likely would not have fired, and that is the wanted
  outcome: the portal was limiting, not blocking, and 86 curricula did
  refresh.
- **A portal that blocks fully** returns only the access check page; the rule
  stops it after 5 requests plus the 2 others in flight (3 workers).

**Alternatives considered**:
- **A share of failures (e.g. 50% of the last 10):** it would stop the
  partial limiting of run 40966298828 and lose good refreshes.
- **Separate counters for new and refreshed curricula:** they hit the same
  portal; a block shows in both.

## R4. How the stop reaches the running downloads

**Decision**:
- **One object per run and source.** A `PortalStop` in
  `src/core/logic/portal_stop.py`, pure and thread safe, holds the counter,
  the limit, the deadline, and the stop with its reason and moment. A
  `threading.Event` wakes the back-off waits.
- **CNPq.** `fetch_with_retries` asks it before each attempt and after
  acquiring a gate slot, records each attempt's outcome, and waits out its
  back-off on the event instead of `time.sleep`. When stopped, the task
  returns at once with `stopped=True` and the attempts it made.
- **Lattes.** Each download task asks it before calling the downloader, and
  records success or failure afterwards.

**Rationale**:
- **No cancelled futures.** The writer keeps reading outcomes in order with
  `batch.outcome(i)`, and a stopped task returns a normal `FetchOutcome`,
  so no `CancelledError` is handled.
- **Prompt stop.** The back-off wait on the event ends at once, so a stop
  never waits out a 90 s back-off.
- **Bounded wait.** The attempts in flight end within the library's own
  timeouts, about 95 s, which the logs of the outage confirm. This is the
  bounded wait of FR-003.

**Alternatives considered**:
- **`executor.shutdown(cancel_futures=True)`:** it only cancels tasks that
  have not started. The started ones sit in back-off sleeps or in gate waits.
- **Killing the browser of an in-flight attempt:** that would reach into
  dgp_cnpq_lib.
- **Leaving the threads behind:** they keep the interpreter from exiting.

**Residual risk**: a navigation that hangs past the library's timeout would
still hold the phase until the orchestrator's 10,800 s limit. No log so far
shows one. Fixing it would mean changing the library, which is out of scope.

## R5. The counts and the report

**Decision**:
- **Counts.** `download_counts` gains a `stopped` list: the items that were
  never tried, or whose retries were cut by the stop. They are counted apart
  from `failed`.
  - A CNPq group never tried with a stored page is processed from it, like a
    reused group, and no failure is recorded for it.
  - A group that failed at least one attempt is a failed download, as today:
    the stored page is used if it exists, and the failure is recorded.
  - A Lattes curriculum not tried keeps its cached copy and its date. Its
    date is the oldest, so the next rotation takes it first.
  - A new curriculum not tried stays missing, so it is new again next run.
- **Report.** When a source stops, its phase writes an entry to
  `data/reports/portal_stops.json`, keyed by source. The entry holds the
  reason (`failures_in_a_row` or `time_budget`), the limit, `stopped_at`, the
  seconds since the downloads started, and the counts.
- **Log.** The same facts appear as a WARNING line, `portal given up: ...`.
- **Weekly summary.** The orchestrator deletes the file at the start of the
  weekly. At the end it adds one line per entry to the summary log and to
  the Telegram summary.
- **Phase exit.** A stop never changes the phase's exit code.

**Rationale**:
- **One small file.** It reaches the orchestrator, which runs every phase in
  its own subprocess, without touching the phase outputs.
- **No double entry.** The CNPq counts already go to the phase report
  (`skip.downloads`); the stop entry adds only the stop.
- **Not counted as failures.** Counting untried items as failed would mix "the
  portal refused" with "we chose not to ask".

**Alternatives considered**:
- **Only the phase report:** the Lattes download phase writes no such report.
- **An exit code for "partial":** the orchestrator would show the phase as ✗,
  which this spec forbids.

## R6. Settings

**Decision**: environment variables, read in core by `portal_stop_settings()`,
in the style of `refresh_settings()`. An invalid value is logged and replaced
by the default. A limit of 0 turns that one rule off.

| Variable | Default | Makefile | Workflow input |
|---|---|---|---|
| `HORIZON_PORTAL_EARLY_STOP` | on (`0`/`false`/`no` turn it off) | `EARLY_STOP` | `early_stop` (boolean, default true) |
| `HORIZON_CNPQ_STOP_AFTER_FAILURES` | 8 | `CNPQ_STOP_AFTER` | `cnpq_stop_after` (blank = default) |
| `HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN` | 45 | `CNPQ_BUDGET_MIN` | `cnpq_budget_min` (blank = default) |
| `HORIZON_LATTES_STOP_AFTER_FAILURES` | 5 | `LATTES_STOP_AFTER` | `lattes_stop_after` (blank = default) |

**Rationale**:
- **Scheduled runs.** They pass no inputs, so every variable is blank and the
  defaults apply.
- **Input limit.** The workflow goes from 5 to 9 dispatch inputs, under
  GitHub's limit.
- **One switch.** A single variable turns the whole feature off for
  diagnosis (spec US4).

**Alternatives considered**:
- **A single input with a compact syntax:** harder to read in the dispatch
  form.
- **Values in a config file:** the rotation share set the precedent of
  environment variables.

## R7. Tests

**Decision**: fake portals, no network, with injected clocks and waits:

- **`test_portal_stop.py`** (unit): the counter, the reset on success, the
  deadline, a limit of 0, disabled, settings parsing, and thread safety.
- **`test_cnpq_early_stop.py`:** `fetch_all` and `_sync_cnpq_groups` against
  fake adapters that are healthy, always fail, hang (a slow fake with a fake
  clock), or recover after 3 failures. It checks:
  - no attempt after the stop;
  - the stored pages are used with their dates;
  - groups without a stored page fail;
  - the database is unchanged;
  - the report entry is written;
  - a healthy run equals today's.
- **`test_lattes_early_stop.py`:** `rotate_lattes_downloads` with a fake
  downloader that serves the access check page always, from the k-th
  request, or interleaved at 1 in 5. It checks:
  - the stop after 5 in a row;
  - no stop when interleaved;
  - cached copies and dates kept;
  - new curricula still missing;
  - the next rotation picks the untried first.
- **Orchestrator test:** it reads `portal_stops.json` into the summary, and
  the exit code does not change.
- **Existing tests:** the spec 017 and spec 023 tests keep passing unchanged.
  That is the "identical when healthy" check (FR-008, SC-004).
