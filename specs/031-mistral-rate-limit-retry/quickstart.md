# Quickstart: Validating the Paced Extraction Retry

Every step that calls Mistral costs money, and every weekly or dispatch
needs the maintainer's go-ahead first. Steps 1 and 2 call nothing.

## 1. Unit tests (no network, no waits)

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_extraction_pacing.py tests/test_project_files_rate_limit.py tests/test_project_files_zip_reuse.py tests/test_portal_stops_report.py tests/test_weekly_orchestrator.py tests/test_weekly_etl_workflow.py
```

They cover:

- settings (blank, valid, invalid, zero);
- telling a 429 apart (status attribute, raw response, cause chain, text
  fallback);
- `Retry-After` given in seconds or as a date;
- growing waits and the 300 s cap;
- the wait budget;
- recovery after one or two refusals;
- exhausted tries;
- other errors not retried;
- the budget leaving the rest of the queue;
- the pause between calls, with the injected clock;
- retries off reproducing today's calls and files;
- the archive restore still happening before any call;
- the report entry and the summary lines.

Then the full suite:

```bash
make ci-check
```

## 2. Local run with nothing pending (no calls)

Locally all 322 `PJ_*.json` exist. With the PDFs already on disk:

```bash
PYTHONPATH=. .venv/bin/python app.py extract_project_files
```

Expected:

- `322 PDFs | 322 already present | 0 pending`;
- no extractor built;
- no wait;
- the extraction counts show zero calls (SC-004).

## 3. Local run with a few pending documents (costs a few calls)

Only with the maintainer's ok:

1. Move 3 JSONs to a backup folder outside `data/exports/`, so they are
   pending.
2. Run with a short budget:

   ```bash
   EXTRACT_PAUSE_S=0 EXTRACT_RETRIES=3 EXTRACT_FIRST_WAIT_S=5 make extract-project-files PROJECT_FILES_LIMIT=
   ```

   The archive restores them first (feature 013). To force real calls, also
   move the local `exports_canonical.zip` aside for the run, and put it back
   afterwards.
3. Check the log:
   - the opening and restore lines;
   - any `rate limited (try …)` lines;
   - the `Extraction finished` counts and their invariants.
4. Compare the 3 new JSONs with the backups. They should have the same
   fields; the text may differ slightly from one LLM run to another.

## 4. Fork run (SC-001, SC-002, SC-003)

Only with the maintainer's ok. Dispatch `weekly-etl.yml` on
`031-mistral-rate-limit-retry` with the defaults. The committed zip still
lacks the 25 documents of 2026-11-09, so they are pending.

Check in the log:

- `322 PDFs | 0 already present | 322 pending`, then `296 restored from the
  archive | 26 to extract` (give or take source changes);
- the `rate limited` retries and their waits;
- `Extraction finished`: at least 23 of the 25 extracted (SC-001);
- the weekly summary line `✎ sigpesq_project_files: …`;
- the phase `extract_project_files` ends with exit 0, within the 20 min
  budget plus 5 min of waits (SC-003);
- `field merge sigpesq_project_files: fields=` close to the local 139
  (SC-002).

The workflow commits the new `exports_canonical.zip`. A second dispatch
should then show the recovered documents as restored from the archive, with
no calls for them.

## 5. Retry off (SC-005)

```bash
EXTRACT_RETRIES=0 EXTRACT_PAUSE_S=0 make extract-project-files
```

The calls and the files written are the same as before the feature (A8).
