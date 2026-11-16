# Quickstart: Validating SQLite WAL Journaling

`$R` is a scratch directory **on disk**, outside the repository, for example
`~/.cache/horizon_wal_replay`. Do not use `/tmp` if it is tmpfs: commits are
already cheap in memory, so the comparison would hide the effect. Telegram must
be off for every replay run:

```bash
export HORIZON_TELEGRAM_BOT_TOKEN= HORIZON_TELEGRAM_CHAT_ID= TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID=
```

## 1. Unit tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_sqlite_settings.py tests/test_weekly_orchestrator_finalize.py
```

They cover: the listener on a temporary file (wal / NORMAL), an engine created
before installation, an in-memory database (stays `memory`), a non-SQLite
connection (untouched), idempotent installation, finalize on a WAL file
(checkpointed, `delete`, no companion files, copy alone readable), finalize
no-op cases, finalize with a connection still open (returns the error, does not
raise), and `run_weekly` calling finalize after the phases even when phases
fail.

## 2. Build the pre-Lattes snapshot (offline, ~15 min)

Requires a `db/horizon.db` from a previous full local run (it holds the 350
`cnpq_group_payload` source records) and the SigPesq reports in
`data/raw/sigpesq/`.

1. `DATABASE_URL=sqlite:///$R/pre_lattes.db .venv/bin/python db/create_db.py`
2. In a throwaway script (patch, then call):
   - patch `CnpqCrawlerAdapter.__init__` to do nothing and
     `CnpqCrawlerAdapter.get_group_data` to return the stored payload for
     `normalize_cnpq_url(url)`, read from `db/horizon.db`
     (`source_records` where `source_entity_type = 'cnpq_group_payload'`,
     keyed by `source_path`);
   - inside one throwaway Prefect flow, call `persist_research_groups()`,
     `persist_projects()`, `persist_advisorships()`;
   - call `sync_cnpq_groups_flow(campus_name=None)`.
3. Expect 350/350 groups and roughly the counts in `data-model.md`.

## 3. Replay the Lattes phases (old vs new code, ~70 min)

For `version` in `base` (commit before this feature) and `feature`:

```bash
cp $R/pre_lattes.db $R/$version.db
export DATABASE_URL=sqlite:///$R/$version.db PYTHONPATH=.
.venv/bin/python app.py ingest_lattes_projects
.venv/bin/python app.py lattes_advisorships
```

During the `feature` run, check that the phase really runs in WAL mode: while it
runs, `$R/feature.db-wal` exists, and from a separate shell
`PRAGMA journal_mode` on the file returns `wal`.

Record each phase's wall time. Reference (2026-10-23, same machine):
`lattes_projects` 1 298 s → 521 s, `lattes_advisorships` 1 476 s → 875 s.

## 4. Compare

Run on `base.db` and `feature.db` and diff the outputs:

```sql
SELECT 'teams', COUNT(*) FROM teams
UNION ALL SELECT 'team_members', COUNT(*) FROM team_members
UNION ALL SELECT 'initiatives', COUNT(*) FROM initiatives
UNION ALL SELECT 'initiative_teams', COUNT(*) FROM initiative_teams
UNION ALL SELECT 'advisorships', COUNT(*) FROM advisorships
UNION ALL SELECT 'persons', COUNT(*) FROM persons
UNION ALL SELECT 'researchers', COUNT(*) FROM researchers;

SELECT i.name, t.name FROM initiative_teams it
JOIN initiatives i ON i.id = it.initiative_id
JOIN teams t ON t.id = it.team_id ORDER BY 1, 2;

SELECT t.name, p.name, r.name FROM team_members tm
JOIN teams t ON t.id = tm.team_id
JOIN persons p ON p.id = tm.person_id
LEFT JOIN roles r ON r.id = tm.role_id ORDER BY 1, 2, 3;

SELECT name FROM persons ORDER BY 1;
```

Expected: no difference (SC-002).

## 5. The `enrich_projects` lock (investigation)

1. Reproduce the CI conditions. The two failing CI runs (39009721014,
   40002646510) produced the failure; their `weekly-etl-artifacts` hold the
   `data/` folder and `db/horizon.db` from the run. Use the database as it was
   before `enrich_projects` if available; otherwise rebuild up to
   `extract_project_files` with the CI inputs.
2. Run `app.py enrich_projects` with the base code and with the feature code.
3. If it still fails, find the two writers: log the session/connection identity
   of `ProjectEnrichment._session` and of the tracking repositories at the
   failing call (`_record_tracking`). Research R6 predicts two sessions in one
   process.
4. Record the outcome in the validation report. A fix, if needed, is a separate
   spec.

## 6. Full local weekly

```bash
make weekly-flows 2>&1 | tee logs/weekly_018_validation.log
```

Check:
- exit 0 and the same critical-phase results as the spec 017 run;
- `lattes_projects` and `lattes_advisorships` faster than 21.1 / 24.7 min;
- the `SQLite finalize: …` line reports `finalized=True`;
- afterwards: `ls db/` shows only `horizon.db` (no `-wal`/`-shm`),
  `PRAGMA journal_mode` returns `delete`, and a copy of `db/horizon.db` alone,
  opened read-only, has the same row counts as the original (SC-003).

## 7. Reset

After a run that left companion files (for example one killed mid-phase):

```bash
make db-clean && ls db/
```

Expected: no `horizon.db`, `horizon.db-wal` or `horizon.db-shm`.

## 8. Lint and full suite

```bash
black --check <changed files> && isort --check <changed files>
flake8 . --count --select=E9,F63,F7,F82 --statistics
PYTHONPATH=. .venv/bin/python -m pytest -q tests/
```

Expected: no new failures beyond the 6 pre-existing ones (SC-005).
