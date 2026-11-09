# Contract: Paced Retry of the Project PDF Extraction

## Core API (`src/core/logic/extraction_pacing.py`)

The module is pure: no file, network or clock access of its own.

```python
RETRIES_ENV = "HORIZON_EXTRACT_RETRIES"            # default 3
PAUSE_ENV = "HORIZON_EXTRACT_PAUSE_S"              # default 2
FIRST_WAIT_ENV = "HORIZON_EXTRACT_FIRST_WAIT_S"    # default 30
BUDGET_ENV = "HORIZON_EXTRACT_WAIT_BUDGET_MIN"     # default 20
MAX_WAIT_S = 300.0

@dataclass(frozen=True)
class ExtractionPacingSettings:
    retries: int = 3
    pause_s: float = 2.0
    first_wait_s: float = 30.0
    wait_budget_s: float = 1200.0

def extraction_pacing_settings(env: Optional[Mapping[str, str]] = None) -> ExtractionPacingSettings
def is_rate_limit(exc: BaseException) -> bool
def retry_after_s(exc: BaseException, now: Optional[datetime] = None) -> Optional[float]
def backoff_s(retry: int, settings: ExtractionPacingSettings, retry_after: Optional[float]) -> float

class WaitBudget:
    def __init__(self, total_s: float): ...
    spent_s: float
    def allows(self, wait_s: float) -> bool
    def spend(self, wait_s: float) -> None
```

### Rules

| # | Rule |
|---|---|
| C1 | `extraction_pacing_settings` never raises. A blank value gives the default; a negative, non-numeric or non-finite value is logged once and replaced by the default. `retries` is an integer; the others are floats. |
| C2 | `is_rate_limit(exc)` is true when `exc`, or any exception in its `__cause__`/`__context__` chain (at most 5 deep), has `status_code == 429` or `raw_response.status_code == 429`. With no such attribute anywhere, it is true only when `str(exc)` contains `Status 429`. |
| C3 | `retry_after_s` reads the `Retry-After` header from `exc.headers` (or `exc.raw_response.headers`), as delta-seconds or an HTTP date. It returns `None` when the header is absent, unparsable or negative. |
| C4 | `backoff_s(n, s, ra) = min(MAX_WAIT_S, max(s.first_wait_s * 2**(n-1), ra or 0))` for retry `n ≥ 1`. |
| C5 | `WaitBudget.allows(w)` is `spent_s + w <= total_s`; `spend(w)` adds `w`. |

## Adapter behaviour (`SigPesqProjectFilesAdapter.extract_json`)

The signature is unchanged: `extract_json(force=False, limit=None) -> dict`.
New keyword-only parameters exist for tests:

- `settings: Optional[ExtractionPacingSettings] = None`, read from the
  environment when `None`;
- `sleep: Callable[[float], None] = time.sleep`;
- `clock: Callable[[], float] = time.monotonic`.

| # | Rule |
|---|---|
| A1 | The order is kept: present documents are skipped, then the archive restores what it can (unless `force`), and only then is the extractor built. When nothing is left to extract, the extractor is never built and `sleep` is never called. |
| A2 | Before every call except the first of the run, wait until `pause_s` has passed since the previous call ended. A retry waits for its backoff instead. |
| A3 | A call that raises a rate limit error (C2) is retried after `backoff_s(n)`, at most `retries` times, while the budget allows the wait. Each backoff is spent from the budget. |
| A4 | A call that raises any other exception is not retried: it is logged at WARNING as today and counted in `failed_other`. |
| A5 | When the budget does not allow the next backoff, the current document counts as `failed_rate_limit`, every document not yet sent counts as `left`, and the loop ends. |
| A6 | A JSON is written only on success, with the same `model_dump(by_alias=True)` content and indentation as today. |
| A7 | The method never raises because of an extraction failure, and returns the counts of data-model.md, invariants included. |
| A8 | With `retries=0` and `pause_s=0`, calls, written files and the `errors` value are identical to today's. Only the log lines and the extra count keys differ. |

## Log lines (INFO unless noted)

```text
<pdfs> PDFs | <present> already present | <pending> pending
<reused> restored from the archive | <to_extract> to extract      (after the restore pass)
[<i>/<n>] PJ_X rate limited (try <t>/<1+retries>); waiting <w> s  (WARNING)
[<i>/<n>] PJ_X -> PJ_X.json (after <t> tries)                     (when recovered)
[<i>/<n>] PJ_X FAILED: <error>                                    (WARNING, as today)
Wait budget of <m> min used up; <left> PDF(s) left for the next run   (WARNING)
Extraction finished: {<all counts>}
```

## Report (`src/flows/portal_stops.py`)

```python
def record_extraction(source: str, entry: Mapping[str, object], path=None) -> None  # never raises
def read_extractions(path=None) -> dict                                            # {} when missing
```

- The flow `extract_project_files_flow` calls
  `record_extraction("sigpesq_project_files", …)` after the extraction stage
  has run. It does not call it when `skip_extract` is set.
- The weekly orchestrator reads `read_extractions()` and, for each entry
  with `to_extract > 0`, adds one line to its log summary and to Telegram:

```text
✎ sigpesq_project_files: <to_extract> to extract; <extracted> extracted (<recovered> after a retry), <failed> failed (<rl> rate limit, <other> other), <left> left; waited <min> min
✎ sigpesq_project_files: <to_extract> para extrair; <extracted> extraídos (<recovered> após nova tentativa), <failed> falharam (<rl> limite, <other> outros), <left> para a próxima; espera <min> min
```

A broken entry is logged and skipped. It never changes the run outcome.

## Wiring

| Place | Change |
|---|---|
| `Makefile` | A new `EXTRACT_ENV` passes `HORIZON_EXTRACT_*` only when `EXTRACT_RETRIES`, `EXTRACT_PAUSE_S`, `EXTRACT_FIRST_WAIT_S` or `EXTRACT_WAIT_BUDGET_MIN` is set. It is used by `weekly-flows` and `extract-project-files`, and the help text is updated. |
| `.github/workflows/weekly-etl.yml` | 4 `workflow_dispatch` string inputs (blank default), mapped to `HORIZON_EXTRACT_*` in the `make weekly-flows` step. That makes 15 inputs in total. |
| `docs/flows-and-entrypoints.md` | The retry, its settings and the summary line are described. |
