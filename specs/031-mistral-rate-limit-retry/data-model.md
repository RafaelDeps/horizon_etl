# Data Model: Paced Retry for Project PDFs Refused by the Rate Limit

No database table changes. The feature only adds in-memory values, extraction
counts, and one key in an existing report file.

## ExtractionPacingSettings (core, frozen)

| Field | Type | Default | Rule |
|---|---|---|---|
| `retries` | int ≥ 0 | 3 | retry calls after the first one, per document; 0 turns the retry off |
| `pause_s` | float ≥ 0 | 2.0 | minimum gap between the end of one call and the start of the next |
| `first_wait_s` | float ≥ 0 | 30.0 | wait before the first retry; it doubles on each later retry |
| `wait_budget_s` | float ≥ 0 | 1200.0 | total backoff wait allowed in one run (env value in minutes) |

The settings are read by `extraction_pacing_settings(env)`. A blank value
means the default; an invalid value is logged and replaced by the default.
It never raises.

## Try outcome (per call)

| Outcome | When | Next step |
|---|---|---|
| `ok` | the library returned a `Projeto` | write the JSON; if it took a retry, count it as recovered |
| `rate_limit` | `is_rate_limit(exc)` | retry if both the tries and the budget allow it, otherwise `failed_rate_limit` |
| `other` | any other exception | `failed_other`, no retry (as today) |

## Document lifecycle in one run

```text
present (JSON on disk) ──────────────────────────────▶ counted "present", no call
pending ─▶ restored from the archive ────────────────▶ counted "reused", no call
pending ─▶ to extract ─▶ try 1 ─ ok ─────────────────▶ "extracted"
                          │
                          ├─ other ──────────────────▶ "failed_other"
                          └─ rate_limit ─▶ wait (budget) ─▶ try n ─ ok ─▶ "extracted" + "recovered"
                                         │                  └─ …
                                         ├─ tries exhausted ─▶ "failed_rate_limit"
                                         └─ budget exhausted ─▶ "failed_rate_limit";
                                                               the rest of the queue is "left"
```

## WaitBudget (core)

- `total_s` and `spent_s`.
- `allows(wait_s)` is true when `spent_s + wait_s <= total_s`.
- `spend(wait_s)` adds `wait_s` to `spent_s`.

Only backoff waits count, never the pauses between calls.

## Extraction counts (returned by `extract_json`)

| Key | Meaning |
|---|---|
| `pdfs` | PDFs considered (after `limit`) |
| `present` | had a JSON on disk before the run |
| `skipped` | same value as `present`, kept for older readers |
| `reused` | restored from `exports_canonical.zip` (feature 013) |
| `to_extract` | pending after the restore pass, the documents that may call the service |
| `extracted` | JSON written in this run |
| `recovered` | of `extracted`, those that needed at least one retry |
| `retried` | documents with at least one retry |
| `retries` | total retry calls |
| `failed_rate_limit` | ended on a rate limit (tries or budget exhausted) |
| `failed_other` | ended on any other error |
| `errors` | `failed_rate_limit + failed_other` (kept) |
| `left` | not sent because the budget ran out |
| `waited_s` | total backoff wait |

Invariants:
- `present + reused + to_extract = pdfs`;
- `extracted + failed_rate_limit + failed_other + left = to_extract`;
- `recovered <= retried <= to_extract`.

## Report entry (`data/reports/portal_stops.json`)

The entry goes under the new key `extractions`, with source
`sigpesq_project_files`:

```json
{
  "to_extract": 25, "extracted": 24, "recovered": 23, "retried": 24,
  "retries": 31, "failed_rate_limit": 1, "failed_other": 0, "left": 0,
  "reused": 296, "present": 0, "waited_s": 372.0,
  "settings": {"retries": 3, "pause_s": 2.0, "first_wait_s": 30.0, "wait_budget_s": 1200.0}
}
```

- It is written by the flow after the extraction stage, and only when the
  stage ran.
- The other keys of the file (`stops`, `retries`, `version`) are kept.
- It is read by `read_extractions()`. A missing or unreadable file gives `{}`.
