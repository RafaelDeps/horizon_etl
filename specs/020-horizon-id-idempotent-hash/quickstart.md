# Quickstart: validating Horizon ids and idempotent tracking

Everything runs locally first. GitHub Actions only after the local steps pass.
Never write `db/horizon.db` during validation: every step works on copies in
the session scratchpad (`$S` below).

## 0. Baseline

```bash
S=<session scratchpad>
cp db/horizon.db $S/before.db
.venv/bin/python -I specs/020-horizon-id-idempotent-hash/research-scripts/sim_horizon_ids.py $S/before.db
.venv/bin/python -I specs/020-horizon-id-idempotent-hash/research-scripts/sim_tracking_keys.py $S/before.db
```

Expected on the 2026-10-24 database: 149 shared-id groups; 1 005 tracking keys
with more than one hash today, 22 with the new keys.

## 1. Unit and scenario tests

```bash
.venv/bin/python -m pytest tests/test_horizon_identity.py tests/test_horizon_ids_flow.py tests/test_save_horizon_id_history.py tests/test_horizon_id_assigner.py tests/test_idempotent_rerun.py tests/test_team_synchronizer.py tests/test_export_canonical_data_flow.py -q
.venv/bin/python -m pytest -q
```

The scenario tests cover:

| Test | Spec |
|---|---|
| Same rules applied to the same rows in two fresh databases give the same ids | SC-001, US1 |
| `person:lattes:` / `group:cnpq:` / `article:doi:` formats; no e-mail, CPF or phone in any id | FR-003, FR-007, US1 |
| Two homonymous persons without `lattes_id` get two distinct ids, identical in two rebuilds | FR-008, SC-003 |
| Merge: `lattes_id` person + name-only person → survivor `person:lattes:`, alias `merge` | FR-010, US3 |
| Upgrade: name-only person gains `lattes_id` → alias `upgraded key`; children follow | FR-011 |
| Rebuild: history only in the previous zip → every old id current or alias `rebuild` | FR-013a, SC-007 |
| Key corrected: DOI-less title changed by one letter in the same CV → alias `key corrected`; two similar candidates → no alias, counted | FR-013b |
| Version guard: older `rule_version` in the database → reset requested; same version → no reset | FR-024, US5 |
| Rule-version change: old ids of the changed type recomputed from `natural_key` become aliases `rebuild` | FR-024, FR-013a |
| History sources: database tables, else the pre-reset snapshot `db/horizon_id_history.json`, else the published zip; snapshot and zip merged | FR-013a |
| `save_horizon_id_history.py`: writes the snapshot before `make db-reset`, never blocks the reset | FR-013a |
| `assign_horizon_ids_flow` end to end: migrations, ids, report, `Completed` | Constitution III |
| Same input three times on one database file → second and third passes leave every table identical, ids included | FR-022, FR-023, FR-023b, SC-002 |
| Two persons with the same best name-match score → the same one is chosen whatever the database order | FR-023a |
| Team fed by two CVs with different rosters → union, earliest `start_date`, independent of order and of starting state | FR-023 |
| Existing tables: same `PRAGMA table_info` / `index_list` before and after migrations | FR-014, SC-005 |
| Existing export files: same field sets; two new files present in the zip | FR-015, FR-016 |

## 2. Rerun on a populated database (idempotency on real data)

The Lattes and enrichment phases read local files only and can run directly
on a copy:

```bash
cp db/horizon.db $S/rerun.db
DATABASE_URL=sqlite:///$S/rerun.db .venv/bin/python app.py ingest_lattes_projects
DATABASE_URL=sqlite:///$S/rerun.db .venv/bin/python app.py lattes_advisorships
DATABASE_URL=sqlite:///$S/rerun.db .venv/bin/python app.py enrich_projects
```

The SigPesq and CNPq phases download from the portals. Do not run them against
the portals for this test. Replay them with throwaway harnesses in the
scratchpad, as specs 015–017 did (`replay_sigpesq.py` on the frozen SigPesq
reports; a Prefect flow that patches `CnpqCrawlerAdapter.get_group_data` to
return captured payloads). Those harnesses were not committed and must be
rebuilt. The CNPq payloads can be exported from `source_records`
(`cnpq_group_payload`, 350 rows).

Run the passes three times. Compare every table of `$S/rerun.db` after the second and the third pass: they must be identical (fixpoint, research R9.3). Also report what changed between the first and the second pass; today the only expected cause is person resolution against a fuller database (25 team rows on the 2026-10-24 data). Expected: identical, except `ingestion_runs` (see
[contracts/tracking-keys.md](contracts/tracking-keys.md)). Today, for
`ingest_lattes_projects` alone: +3 806 change logs, 713 rewritten
`team_members`, +23 `source_records`.

## 3. Two rebuilds from scratch

Run the weekly phases twice from a reset database on the same frozen inputs
(SigPesq reports, Lattes JSON, CNPq payloads, PJ documents), then compare
`horizon_ids_canonical.json`:

- same set of (`entity_type`, `horizon_id`, `natural_key`) rows: SC-001;
- for every previously published id, current or alias: SC-007.

## 4. Replay: old code vs new code

Old (`022-enrich-lock-fix` head) and new code, each from a reset database, on
the same frozen inputs. Compare:

| What | Expected |
|---|---|
| Entity tables (by content, not numeric id) | Identical, except (a) `team_members` of teams fed by several CVs (union and earliest date instead of last writer: count and list them), and (b) attributes of the ~22 same-CV duplicate items where the kept version differs |
| Existing `*_canonical.json` files | Same field sets; content identical apart from (a) and (b) |
| New files | Present; one row per entity; no shared `horizon_id` |
| `source_records` | Same row count minus duplicates; keys in the new format |
| `entity_change_logs` | Only real changes |

Record the numbers in `docs/reports/2026-10-XX-horizon-id-validation.md`.

## 5. Local weekly, then CI

```bash
make weekly-flows
```

Check that the phase order includes `assign_horizon_ids` between
`consolidate_duplicates` and `export_canonical`, that it exits 0, and the
report `data/reports/horizon_ids_report.json`. Only after this passes:
push to the fork and dispatch the workflow manually. The CI id file must equal
a local run on the same inputs (SC-006).
