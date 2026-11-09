# Research: Paced Retry for Project PDFs Refused by the Rate Limit

## Evidence (fork runs of 2026-11-09)

| Run | PDFs | Present | Restored | Extracted | Errors | Stage time |
|---|---|---|---|---|---|---|
| 42616860871 (from scratch) | 321 | 0 | 296 | 0 | 25 | 39 s |
| 42634852240 (restored) | 322 | 0 | 296 | 1 | 25 | 45 s |

- All 25 errors in both runs had the same text: `API error occurred: Status
  429 ... "message":"Rate limit exceeded","type":"rate_limited"`. They were
  the same documents both times: PJ_2101, 2123, 2127, 2128, 2130, 2131, 2163,
  2166, 2187, 2192, 2207, 2208, 2262, 2274, 2284, 2369, 2389, 2804, 2855,
  3636, 5434, 5583, 5624, 5684 and 9194.
- Locally, all 322 documents exist. The local `exports_canonical.zip` held
  322; the committed one held 297. The difference is exactly these 25.
- "Present" is 0 in CI because the JSON folder is not part of the weekly
  state bundle. Every document comes from the archive or from Mistral. That
  is out of scope here.
- The 26 calls happened within about 40 s, so the limit is per short period,
  not a daily quota.

## R1 — Where the retry lives

- **Decision**: in horizon_etl, around `extractor.extract_project(pdf)` in
  `SigPesqProjectFilesAdapter.extract_json`. The decisions go in a new pure
  module, `src/core/logic/extraction_pacing.py`.
- **Rationale**: the maintainer rules out changing agent_sigpesq or mistralai.
  `ProjectExtractor` builds its own `Mistral` client, so the SDK's
  `retry_config` cannot be passed without reaching into the library's
  internals. A loop around the public call keeps the library as is. It
  mirrors spec 025's `access_check_retry.py`: pure settings and decisions in
  core, I/O in the adapter.
- **Alternatives considered**:
  - Replace `extractor.client` with a `Mistral(retry_config=…)`. Rejected:
    it depends on a private attribute and on the SDK's retry codes, and it
    hides the retries from our counts.
  - A retry inside agent_sigpesq. Rejected: third-party library.

## R2 — How a rate limit is recognised

- **Decision**: `is_rate_limit(exc)` is true when the exception, or one in
  its `__cause__`/`__context__` chain, has `status_code == 429`, or has a
  `raw_response` whose `status_code` is 429.
- **Rationale**: mistralai 1.12 raises `SDKError`, a subclass of
  `MistralError`, which carries `status_code`, `headers` and
  `raw_response`. Duck typing keeps the core free of the optional
  dependency, and still works if the library wraps the error.
- **Alternatives considered**: matching the text `Status 429`. Kept only as
  a fallback, for when no status attribute is found. The text format is the
  SDK's (`SDKError.__init__`), so it is a weaker signal.

## R3 — How long to wait

- **Decision**: the wait for retry `n` (1-based) is
  `max(first_wait_s × 2^(n-1), retry_after_s)`, capped at `MAX_WAIT_S` (300
  s). `retry_after_s` is read from the error's `Retry-After` header, as
  seconds or as an HTTP date. A missing, invalid or negative value is
  ignored.
- **Defaults**:
  - `first_wait_s` = 30, so waits of 30, 60 and 120 s;
  - `retries` = 3;
  - `pause_s` = 2;
  - `wait_budget_min` = 20.
- **Rationale**: the limit is per short period (R0). A few tens of seconds
  is enough for a per-minute window, and doubling covers a slower one. Three
  retries cost at most 210 s for one document, which fits the budget. The
  service's own `Retry-After` is the best signal when sent, but the 300 s
  cap keeps a wrong header from stalling the phase.
- **Alternatives considered**:
  - A fixed wait. Rejected: it either wastes time or is too short.
  - Unlimited tries. Rejected: it breaks the phase limit.

## R4 — Pause between calls

- **Decision**: before every call except the first of the run, wait until
  `pause_s` has passed since the end of the previous call (a monotonic clock
  is injected). A retry waits for its backoff instead of the pause.
- **Rationale**: the 25 failures come from bursts, so spacing the calls
  lowers the chance of a 429 at all. Measuring from the end of the previous
  call adds no wait after a slow OCR.
- **Alternatives considered**: a token bucket. Rejected: there is a single
  sequential caller, so a pause is enough.

## R5 — The wait budget

- **Decision**: a `WaitBudget(total_s)` counts the backoff waits of the
  stage; pauses do not count. Before a backoff wait, if the wait would
  exceed what is left:
  - the current document counts as `failed_rate_limit`;
  - every document not yet sent counts as `left`;
  - the loop stops.

  With a budget of 0, the first 429 of the run stops it.
- **Rationale**: the budget is there to bound a long outage, and outages show
  up as repeated 429s. Pauses are small and fixed (about 26 × 2 s), so they
  do not need the budget. Stopping the whole stage, instead of trying each
  later document once, avoids a burst of failing calls against a service
  that is refusing.
- **Alternatives considered**:
  - Count the pauses too. Rejected: then `pause_s` and the budget depend on
    each other.
  - Keep sending after the budget, without waits. Rejected: it hits the
    limit again for nothing.

## R6 — Counts and log lines

- **Decision**: `extract_json` returns:
  - `pdfs`;
  - `present`, which replaces `skipped` (kept as an alias with the same
    value, for the flow's existing reader);
  - `reused`;
  - `extracted`;
  - `recovered`, the subset of `extracted` that needed a retry;
  - `retried`, documents with at least one retry;
  - `retries`, total retry calls;
  - `failed_rate_limit` and `failed_other`;
  - `errors`, equal to `failed_rate_limit + failed_other`, kept for
    compatibility;
  - `left`;
  - `waited_s`.

  The opening line becomes `N PDFs | P already present | R pending`. After
  the archive pass a second line says `X restored from the archive | Y to
  extract`. The end line prints every count.
- **Rationale**: the current `0 already extracted | 322 to extract` makes
  every week look like a full extraction (spec context).
- **Alternatives considered**: keep the old line and only add the end line.
  Rejected: the opening line is what misled.

## R7 — Run summary

- **Decision**: the flow writes one entry to `data/reports/portal_stops.json`
  under a new key, `extractions`, with source `sigpesq_project_files` and the
  counts and settings. It is written only when the extraction stage ran. The
  weekly orchestrator adds one line to its log summary and to Telegram when
  the entry has calls or failures, for example:

  `✎ sigpesq_project_files: 25 to extract; 24 extracted (23 after a retry), 1 failed (rate limit), 0 left; waited 6 min`

  The file is already cleared at the start of each weekly, and no phase
  reads it.
- **Rationale**: the same channel as spec 024 and spec 025. The maintainer
  reads one summary, not the phase log.
- **Alternatives considered**: a new report file. Rejected: one more file to
  clear, stage and scan.

## R8 — Settings and their wiring

- **Decision**:

  | Env var | Makefile | Dispatch input | Default | Off / invalid |
  |---|---|---|---|---|
  | `HORIZON_EXTRACT_RETRIES` | `EXTRACT_RETRIES` | `extract_retries` | 3 | 0 = no retry |
  | `HORIZON_EXTRACT_PAUSE_S` | `EXTRACT_PAUSE_S` | `extract_pause_s` | 2 | 0 = no pause |
  | `HORIZON_EXTRACT_FIRST_WAIT_S` | `EXTRACT_FIRST_WAIT_S` | `extract_first_wait_s` | 30 | — |
  | `HORIZON_EXTRACT_WAIT_BUDGET_MIN` | `EXTRACT_WAIT_BUDGET_MIN` | `extract_wait_budget_min` | 20 | 0 = stop at the first 429 |

  A blank value means the default. A negative, non-numeric or non-finite
  value is logged and replaced by the default, as `_read` does in
  `access_check_retry.py`. The Makefile passes each variable only when set,
  in a new `EXTRACT_ENV` used by `weekly-flows` and `extract-project-files`.
  The workflow maps the 4 inputs to env, which makes 15 inputs (GitHub
  allows 25).
- **Rationale**: the same pattern as `REFRESH_SHARE` and
  `LATTES_RETRY_PAUSE_MIN`.
- **Alternatives considered**: fewer inputs (only retries and the budget).
  Rejected: the spec asks for every knob to be configurable in a dispatch.
