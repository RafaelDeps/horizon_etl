# Quickstart: Verifying the Team Lookup Index

Three checks, from cheapest to most expensive:
1. **Tests.** The automated tests cover FR-012.
2. **Controlled replay.** Proves the results are unchanged (SC-004).
3. **Full timing run.** Proves the speed-up (SC-001, SC-002, SC-003, SC-005).

Commands assume the repository root and the project venv (`.venv`).

## 1. Tests

```bash
.venv/bin/python -m pytest -q tests/test_team_synchronizer.py tests/test_team_management.py tests/test_lattes_advisorships_loader_reuse.py
```

```bash
make ci-check
```

The new tests MUST cover each case in FR-012:
- a hit by exact name;
- a hit by normalised name;
- lowest-id tie-breaking;
- creation on a miss, found by the next lookup;
- a team created outside the synchroniser, found by the incremental read;
- a failed creation leaving the lookup unchanged;
- one `ProjectLoader` per advisorships run.

## 2. Controlled replay (SC-004)

Goal: run the same persistence on the same frozen inputs with the **base**
commit and with the **feature** branch, then compare. Nothing contacts SigPesq,
CNPq or Lattes. Use a scratch directory outside the repository for the
snapshots, for example `$REPLAY=/tmp/replay-015`.

### 2.1 Freeze the inputs (once)

- `data/raw/sigpesq/` (the SigPesq Excel reports from the last real run) and
  `data/lattes_json/` (the ~435 CVs) are the inputs. Copy both to `$REPLAY/inputs/`.
- From a full run, take a DB snapshot **just before `lattes_projects`**. That is
  the database after `sigpesq`, `cnpq` and `lattes_download`. Use SQLite's
  backup API while no phase is writing, or stop the run after `lattes_download`.
  Save it as `$REPLAY/pre_lattes.db`.

### 2.2 Replay the SigPesq persistence

For each of `base` and `feature`:
1. Check out the commit.
2. Point `DATABASE_URL` at a fresh file, `sqlite:///$REPLAY/<version>_sigpesq.db`.
3. Run `make db-init` with that `DATABASE_URL`.
4. Run, inside a throwaway Prefect flow (constitution III), the three persist
   tasks `persist_research_groups`, `persist_projects` and
   `persist_advisorships`, with `data/raw/sigpesq/` restored from
   `$REPLAY/inputs/`.

### 2.3 Replay the Lattes phases

For each of `base` and `feature`:
1. Copy `$REPLAY/pre_lattes.db` to `$REPLAY/<version>_lattes.db`.
2. Point `DATABASE_URL` at that copy.
3. With `data/lattes_json/` restored from `$REPLAY/inputs/`, run:

```bash
.venv/bin/python app.py ingest_lattes_projects
```

```bash
.venv/bin/python app.py lattes_advisorships
```

### 2.4 Compare

Run the same read-only queries on `base_*.db` and `feature_*.db`:

```sql
-- counts
SELECT 'teams', COUNT(*) FROM teams
UNION ALL SELECT 'team_members', COUNT(*) FROM team_members
UNION ALL SELECT 'initiatives', COUNT(*) FROM initiatives
UNION ALL SELECT 'initiative_teams', COUNT(*) FROM initiative_teams
UNION ALL SELECT 'advisorships', COUNT(*) FROM advisorships
UNION ALL SELECT 'persons', COUNT(*) FROM persons;

-- initiative ↔ team links, by name
SELECT i.name, t.name
FROM initiative_teams it
JOIN initiatives i ON i.id = it.initiative_id
JOIN teams t ON t.id = it.team_id
ORDER BY 1, 2;

-- team memberships, by name
SELECT t.name, p.name, r.name
FROM team_members tm
JOIN teams t ON t.id = tm.team_id
JOIN persons p ON p.id = tm.person_id
LEFT JOIN roles r ON r.id = tm.role_id
ORDER BY 1, 2, 3;
```

**Pass**: counts are equal, and both name-based result sets are identical, for
the SigPesq pair and for the Lattes pair. Document any difference with its cause
in the feature's notes before merging.

## 3. Full timing run (SC-001, SC-002, SC-003, SC-005)

```bash
make weekly-flows > logs/weekly_015_validation.log 2>&1
```

Then check:
- **Phase durations** in the orchestrator summary and in Prefect:
  - `lattes_projects` under 20 min (baseline 81);
  - `lattes_advisorships` under 20 min (baseline 252);
  - the whole run under 4 h 02 min (half of 8 h 04 min).
- **Team lookup summary lines.** There should be four: `sigpesq_projects`,
  `sigpesq_advisorships`, `lattes_projects` and `lattes_advisorships`, each with
  `failed=0` or explained failures.
- **SC-003.** From the INFO lines `Lattes lattes_advisorships CV i/N … took Xs`
  in the run log, the mean of the last 50 CVs must be ≤ 1.5 × the mean of the
  first 50.

If either Lattes phase still exceeds ~15 min, apply the conditional R9 change
(Prefect parameter `quote`) and repeat this step.
