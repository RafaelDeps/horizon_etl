# Persistent Database Between GitHub Actions Weekly Runs — Validation Report (spec 022)

Date: 2026-10-29 · Spec: `specs/022-ci-persistent-database/` · Branch:
`025-ci-persistent-database` (fork RafaelDeps) · Code: `997fa47`.

## 1. Summary

- **A CI weekly now continues from the previous run's database.** The second
  dispatch on the branch restored `db/horizon.db` (333 MB), `data/raw`
  (221 MB) and `cache/` (64 MB) from the first in 16 s, and took **47 min 49 s
  instead of 1 h 46 min** (45%; SC-001 target: at most 60%).
- **The largest gains come from the restored raw files**, not only from the
  skipped documents:
  - `lattes_download` went from 30.2 to 1.7 min (the Lattes cache);
  - `extract_project_files` went from 22.3 to 5.6 min (the project PDFs);
  - the Lattes phases went from 15.9 to 6.1 min (the skipped CVs).
- **A run with nothing to restore rebuilds and does not fail**: the first
  dispatch logged `restore: rebuilt — no successful run` and completed every
  phase.
- **Exports**: both runs give the same 37 files with the same fields, and the
  counts match. The restored run has one researcher fewer, which matches
  `deleted_items=1` in its Lattes phases.
- **Not yet measured on CI**: the steady state, a third run where the Lattes
  phases skip at least 95% of the CVs (SC-002). The second run is the one-time
  convergence after a rebuild described in the spec 021 report (section 4):
  74 of 399 CVs were processed again, as locally (78). A forced rebuild
  (`fresh_database`) was not dispatched either.

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 time | restored run ≤ 60% of a rebuild | 47 min 49 s vs 1 h 46 min 9 s (45%) | Met |
| SC-002 Lattes skips | ≥ 95% of the CVs skipped | Second run: 325 of 399 (81%), the one-time convergence after a rebuild; locally the next run skips 100% (spec 021 report, section 9) | Not yet measured on CI (needs a third run) |
| SC-003 no artifact | rebuild, no failure | First dispatch: `rebuilt — no successful run`, all phases exit 0. Locally: missing, truncated and disabled cases all rebuild | Met |
| SC-004 same files | restored files identical | Local simulation: the database restored from the 2026-10-29 artifact passes `quick_check` and matches the artifact byte for byte; tests check sha256 of database, raw files and cache. CI: sizes match what the first run left (333 MB database) | Met locally; sizes on CI |
| SC-005 summary | 100% of runs state the source | Both runs logged and summarized the outcome (`rebuilt — no successful run`; `restored ... from run 40882304674 (2026-10-29, 997fa47)`) | Met |
| SC-006 exports | same files and fields | Same 37 files and fields; counts equal except 1 researcher (a deleted orphan) | Met |
| SC-007 retention | 90 days | Artifact of run 40882304674 expires 2027-01-27 | Met |

## 3. Runs

| Run | Kind | Restore outcome | Total |
|---|---|---|---|
| [40856179199](https://github.com/RafaelDeps/horizon_etl/actions/runs/40856179199) | spec 021, before this spec | (no restore step) | 1 h 38 min |
| [40882304674](https://github.com/RafaelDeps/horizon_etl/actions/runs/40882304674) | first dispatch | `rebuilt — no successful run` | 1 h 46 min |
| [40899987152](https://github.com/RafaelDeps/horizon_etl/actions/runs/40899987152) | second dispatch | `restored db/horizon.db (333 MB), data/raw (221 MB), cache (64 MB) from run 40882304674 (2026-10-29, 997fa47)` | 47 min 49 s |

Per phase (minutes, from the orchestrator's phase start times):

| Phase | Rebuild (40882304674) | Restored (40899987152) |
|---|---:|---:|
| restore step | — | 0.3 |
| sigpesq | 1.2 | 1.7 |
| cnpq | 21.0 | 16.2 |
| lattes_download | 30.2 | 1.7 |
| lattes_projects | 5.4 | 2.6 |
| lattes_advisorships | 10.5 | 3.5 |
| extract_project_files | 22.3 | 5.6 |
| consolidate_duplicates | 2.9 | 2.7 |
| export_canonical | 4.6 | 4.6 |

Documents processed (rebuild → restored):

| Source | Rebuild | Restored |
|---|---|---|
| lattes_projects | 399 (+36 unidentified) | 74 processed, 325 skipped |
| lattes_advisorships | 399 (+36 unidentified) | 35 processed, 364 skipped |
| cnpq_group | 347 | 3 processed, 347 skipped |
| sigpesq_group | 353 | 2 (the duplicated row) |
| sigpesq_project | 103 | 19 |
| sigpesq_advisorship | 704 (+498 repeated rows) | 54 |

The CNPq phase still downloads every page to compare it (16 min). Keeping the
pages between runs and downloading only a rotating share is spec D.

## 4. Local validation

- **Tests**: `tests/test_restore_weekly_artifact.py` (16 tests, with a fake
  `gh`) and 2 workflow tests in `tests/test_weekly_etl_workflow.py`. They
  cover:
  - run selection (newest successful run with a live artifact);
  - every fallback reason;
  - the unzip of compressed raw files;
  - the database check, the placement and the summary.
  Full suite: 650 passed, the same 6 failures as before this spec.
- **Simulation on the real artifact of run 40856179199** (downloaded to a
  scratch folder, never into the repository):
  - restore: 329 MB database and 221 MB `data/raw` placed in 1.5 s;
    `quick_check` ok;
  - `db/ensure_db.py` on it: "Database kept, pending migrations applied";
  - an artifact without the database gives `database missing`, a truncated
    database gives `database check failed: database disk image is
    malformed`, and `--disabled` gives `restore disabled`. In each case
    `db/ensure_db.py` then creates a new database.
- **The real artifact had no compressed file under `data/raw`** (its largest
  raw file is under 10 MB). The unzip safety net is covered by a test only.

## 5. Notes

- The database path appears masked (`***`) in the CI log, because it comes
  from the `DATABASE_URL` secret.
- The artifact grew from 366 MB to 378 MB with `cache/`.
- Pending: a third dispatch to measure the steady state on CI (SC-002) and,
  optionally, a dispatch with `fresh_database: true` (T029).
