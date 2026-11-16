# Quickstart: validating spec 032

## 1. Tests

```bash
.venv/bin/python -m pytest -q tests/test_project_enrichment.py tests/test_project_enrichment_db.py
.venv/bin/python -m pytest -q
```

Expected: the new rule tests pass; the full suite has no failure.

## 2. Two enrichment runs on a copy of the local database

Back up `db/horizon.db` first (it is the working database). Then run the
`enrich_projects` flow twice over the same `data/exports/project_sigpesq_files_json/`:

```bash
.venv/bin/python app.py enrich_projects
.venv/bin/python app.py enrich_projects
```

After the second run, check:

- every note with `origin = new_from_document` has
  `match_strategy = new_from_document` (37 on the local database of
  2026-11-09);
- no `entity_change_logs` row was added by the second run for those
  initiatives;
- the `Enrichment complete` log line still counts `by_title_exact` for them
  (the per-run match is unchanged).

## 3. Drifted database

On a database whose document-created notes say `title_exact` (the fork CI
state), the first run writes `new_from_document` once per drifted note and the
second run writes nothing. The fork state can be checked with the weekly
workflow after the maintainer approves a run.
