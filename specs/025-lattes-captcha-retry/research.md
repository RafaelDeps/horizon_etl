# Research: Second Try for Lattes Access Check Pages

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

The spec has no `NEEDS CLARIFICATION` marker. These notes settle the design
choices the spec leaves open and record the evidence behind the defaults.

## R1. Telling an access check page apart from other failures

**Decision**: a new exception, `AccessCheckPage`, a subclass of
`ScriptLattesRuntimeError`, in `src/flows/lattes/download.py`. Both places
that reject the page raise it:
- `_download_lattes_to_cache`, for a new curriculum;
- `refresh_one` inside `refresh_lattes_cache`, for a refresh.

Both functions also get an optional output list, `access_checked`, that
collects the ids rejected this way. It works like the `not_tried` list of
spec 024.

**Rationale**:
- The page is already detected in exactly these two places, by
  `is_curriculum_page` (spec 023).
- A subclass keeps every existing `except Exception` and every test that
  expects `ScriptLattesRuntimeError` working unchanged.
- The message stays the same ("... (access check page)"), so the logs read
  as today.
- An output list leaves the return values of `prefetch_lattes_cache` and
  `refresh_lattes_cache` unchanged for their callers and tests.

**Timeouts and connection errors** keep their retry inside
`bounded_baixa_cv_lattes`: 2 attempts and a 30 s sleep. When that retry
returns the access check page, the check after the download raises
`AccessCheckPage`, so the curriculum joins the second pass (spec, Edge
Cases). No extra code is needed for that.

**Alternatives considered**:
- **Parsing the message:** fragile, and it couples the second pass to log
  text.
- **Returning a status per id:** it changes two public functions and their
  tests for no gain over an output list.

## R2. Where the second pass runs

**Decision**: at the end of `rotate_lattes_downloads`, after the new
curricula and the refresh share. It reuses `prefetch_lattes_cache` for the
rejected new curricula and `refresh_lattes_cache` for the rejected
refreshes, in that order, with the second-pass worker count and the same
`PortalStop`.

**Rationale**:
- Both functions already apply the caching rules of FR-004:
  - a new curriculum is cached only when the real page arrives;
  - a refresh goes to `cache/.refresh/` and replaces the cached copy only
    when the real page arrives.
- The manifest is written once, at the end, with the successes of both
  passes, as today.
- `download_lattes_flow` builds the scriptLattes list from what is in
  `cache/` after `rotate_lattes_downloads` returns. A recovered curriculum is
  therefore included and processed in this run with no change there.
- A rejected new curriculum has no file in `cache/` (it was deleted on
  rejection), so `prefetch_lattes_cache` sees it as missing again.

**Alternatives considered**:
- **Retrying each curriculum right away inside its own task:** that is a
  third attempt with no pause. It keeps the request rate up while the portal
  is checking access, which is what the pause is meant to avoid.
- **A separate flow or phase:** it would need its own list, manifest pass
  and orchestrator entry, for a few dozen requests.

## R3. Defaults for the pause and the workers

**Decision**: a pause of 5 min and 1 worker.

**Evidence** (local run from scratch, 2026-11-03,
`logs/weekly_2026-11-03_from_scratch.log`):
- 435 requests with 3 workers, at a steady 17 to 22 successes per minute
  (about 9 s per request and worker).
- 38 access check pages, spread from 16:02 to 16:23, 1 to 5 per minute, with
  no rise towards the end.
- 35 of the 38 had a real copy from earlier runs, and only 3 of the 27
  rejected on 2026-10-21 were rejected again.

**Rationale**:
- The pages look random per request. A second request then succeeds about
  91% of the time whatever the pause.
- If they depend on the request rate of one IP, a pause and a slower pace
  are the cheapest lever that does not touch the CAPTCHA.
- 1 worker for about 38 requests costs about 6 min, and 3 workers about
  2 min. Either is small next to the 25 min first pass.
- One worker is the gentlest choice. It can be raised once a run shows the
  recovered count.

**The wait**: when a `PortalStop` exists, `stop.wait(pause)`; otherwise an
injected `sleep` (default `time.sleep`), so the tests take no real time.
Nothing can trigger the Lattes stop during the pause, because no request
runs then and Lattes has no time budget. `stop.wait` is used only for
uniformity with the CNPq back-off.

**Alternatives considered**:
- **No pause:** it would retry while the portal is still checking access.
- **A pause per curriculum:** it multiplies the cost by the number rejected.
- **Several rounds:** more pressure for little gain, since next week's run
  tries again anyway (spec, Assumptions).

## R4. The second pass and the spec 024 stop

**Decision**: one `PortalStop` for both passes, as today for new curricula
and refreshes.
- **No pause and no second pass** when `stop.stopped` is true after the
  first pass (FR-005).
- **The count goes on:** a failure in the second pass continues the count
  of failures in a row left by the first. Only a success resets it.
- **Curricula not tried** because the stop triggered during the second pass
  go to the same `not_tried` list:
  - a new one is neither new nor failed (spec 024 counts);
  - a refresh is reused from its cached copy.
- `record_portal_stop("lattes", ...)` runs after both passes, so its counts
  include the second pass.

**Rationale**:
- The stop exists to protect the portal. A second pass outside it would
  undo spec 024.
- The count of failures in a row was built to see blocking across all
  Lattes requests of a run (spec 024, research R3). Resetting it at the
  pause would hide a portal that kept blocking.

**Alternatives considered**:
- **A fresh stop for the second pass:** up to 5 more rejected requests
  against a portal that was already blocking.

## R5. Counts and run summary

**Decision**:
- **Counts.** `download_counts` is unchanged. A recovered curriculum is
  simply not in `failed`. `rotate_lattes_downloads` adds `retried` and
  `recovered` (and `retried_ids`) only when a second pass ran, and
  `counts_line` appends ` retried=N recovered=M` only then:

  ```text
  downloads lattes: new=432 refreshed=0 reused=0 failed=3 reused_after_failure=0 retried=38 recovered=35
  ```

- **Report file.** The second pass writes an entry to the spec 024 report
  file, `data/reports/portal_stops.json`, under a new top-level key
  `retries` (data-model.md). The file keeps version 1, because the new key is
  additive and `read_portal_stops` reads only `stops`.
- **Summary lines.** The weekly orchestrator reads `retries` and adds one
  line to the summary log and to the Telegram message, after the stop lines.

**Rationale**:
- A healthy run has no `retried` key, no line and no `retries` entry, so its
  output is identical to today's (FR-006).
- The orchestrator already clears this file at the start of the weekly and
  reads it at the end. A second file would need its own clear and read.
- `record_portal_stop` must keep the keys it does not own. Today it rewrites
  the file from `stops` only, so it changes to keep `retries` (contract).

**Alternatives considered**:
- **A new `data/reports/lattes_retries.json`:** the same information, plus
  another file to clear, upload and read.
- **Counting `recovered` as a separate category in `download_counts`:** it
  would change the spec 023 counts of every run that has a second pass, and
  the counts would no longer add up to the list.

## R6. Settings, Makefile and workflow inputs

**Decision**:

| Variable | Default | Makefile | Workflow input |
|---|---|---|---|
| `HORIZON_LATTES_RETRY_WORKERS` | 1; 0 turns the second pass off | `LATTES_RETRY_WORKERS` | `lattes_retry_workers` (blank = default) |
| `HORIZON_LATTES_RETRY_PAUSE_MIN` | 5 (minutes, decimals allowed); 0 = no wait | `LATTES_RETRY_PAUSE_MIN` | `lattes_retry_pause_min` (blank = default) |

- They are read by `access_check_retry_settings(env)` in the new
  `src/core/logic/access_check_retry.py`, in the style of
  `portal_stop_settings` and `refresh_settings`.
- An invalid value (not a number, negative, not finite) is logged as a
  WARNING and the default is used. The function never raises.
- `HORIZON_PORTAL_EARLY_STOP=0` does not turn the second pass off. They are
  separate features; the second pass simply runs without a stop, as the
  first pass does then.

**Input limit**: the workflow goes from 9 to 11 dispatch inputs. GitHub
raised the `workflow_dispatch` limit from 10 to 25 on 2025-12-04 (GitHub
changelog, "Actions workflow dispatch workflows now support 25 inputs").
The spec 024 test that asserts `len(inputs) <= 10` changes to `<= 25`, with
that reason in a comment. The fork dispatch of the validation confirms that
GitHub accepts the file.

**Alternatives considered**:
- **A single compact input** (`"1,5"`): it fits the old limit, but it was
  already rejected in spec 024, research R6, as hard to read.
- **Minutes or seconds for the pause:** minutes, like `cnpq_budget_min`,
  with decimals for short tests (`0.1`).
- **One on/off switch plus the two values:** 0 workers already turns it off
  (spec, Assumptions), and a third input adds nothing.

## R7. Tests

**Decision**: new tests in `tests/test_lattes_access_check_retry.py`, with
the `Portal` fake of `tests/test_lattes_early_stop.py` extended to answer
per id and per attempt, and an injected `sleep` that records the pause.

**Cases**:
- rejected on the first request, then served: new and refresh;
- rejected twice;
- no rejection: no pause, no second pass, counts identical;
- turned off (0 workers);
- stop in the first pass: no second pass;
- stop during the second pass;
- count of failures in a row carried over the pause;
- one second try per id, even with duplicates in the list;
- a timeout retried, then rejected, joins the second pass;
- worker count of the second pass;
- the manifest dates;
- the `counts_line` text.

**Other new tests**:
- `tests/test_access_check_retry.py` for the settings;
- the report key and the summary lines, in `test_portal_stops_report.py` and
  `test_weekly_orchestrator.py`;
- the two dispatch inputs and the Makefile variables, in
  `test_weekly_etl_workflow.py`.

**Existing tests**: the spec 023 and spec 024 Lattes tests describe today's
behaviour. Some of them serve access check pages, so with the second pass
on, their request counts would change. `tests/conftest.py` therefore sets
`HORIZON_LATTES_RETRY_WORKERS=0` for every test through an autouse fixture,
and the new tests turn the second pass on themselves. No existing test file
changes, apart from the input-limit assertion of R6.

**Alternatives considered**:
- **Editing each older test:** it hides whether "off" really means today's
  behaviour, which FR-006 requires.

## R8. Time cost and the phase limit

- **The cost of a second pass:** the pause, plus about 9 to 10 s per retried
  curriculum divided by the workers.
  - For the 38 of 2026-11-03: 5 min + about 6 min = about 11 min (SC-002).
  - For a CI rotation, with about 100 refreshes and 7 to 9% rejected: 5 min
    + about 1.5 min.
- **The limit:** `lattes_download` keeps its limit of 5,400 s (90 min). A
  run from scratch used 25 min for the first pass plus about 2 min of
  scriptLattes.
- **A high but interleaved rate,** for example 30% of 435 requests, never 5
  in a row: about 130 retries, 5 min + about 22 min. The phase still ends
  in about 55 min.
- **A portal that blocks in a row** triggers the stop, and then there is no
  second pass.

No change to the phase limit is needed.
