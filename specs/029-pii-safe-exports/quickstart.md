# Quickstart: Validating PII-Safe Exports

Tests use synthetic addresses only (FR-015). Reports and notes hold counts, never values.

## Before merging

The maintainer creates `HORIZON_STATE_KEY` on each repository ([contracts/state-bundle.md](contracts/state-bundle.md)). Without it, runs are safe but rebuild each time.

## Automated tests

Run pytest directly, from the repository root, in the local `.venv` (pytest is installed there). Do not use `make test`: it starts Docker for a Prefect server.

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_zip_exports_scan.py
```

The database is always inside the encrypted bundle (decision D1), so any step below that inspects a CI database needs the state key: open `weekly_state.bundle` with it (`open_bundle` in `src/scripts/weekly_state_bundle.py`). The public part of the artifact holds only report text files.

| Test file | Proves |
|---|---|
| `tests/test_weekly_orchestrator.py` | Phase order and criticality; the gate skips on a failed mart; the run stays exit 0 |
| `tests/test_zip_exports_scan.py` | Match replaced, count logged, no value in the log; unchanged member keeps its date; hash values untouched; idempotent; over 100 MiB keeps the old archive; malformed known fields; numeric CPF |
| `tests/test_pii_anonymizer.py` | CPF in text; known fields; `keyed_export_hash`; fingerprint |
| `tests/test_canonical_exporter.py` | Initiatives and advisorships scrubbed; hashes keyed on export |
| `tests/test_anonymize_backfill.py` | Three columns, malformed values, `value_hash` consistent, fixpoint, no plain value in the file's bytes after VACUUM, `content_hash` untouched |
| `tests/test_tracking_recorder_scrub.py` | Assertions and change logs scrubbed; hash unchanged for clean values |
| `tests/test_app_zip_exports.py` | `export_canonical` does not zip, `zip_exports` does; the flow and the command |
| `tests/test_purge_public_artifacts.py` | Dry run by default; clean run refused unless it succeeded and holds the bundle; only older artifacts deleted; logs only with the flag |
| `tests/test_weekly_state_bundle.py` | Round trip byte-identical; flipped bit, truncated file, wrong key, passphrase-sized key; `..`, link and absolute members refused with nothing extracted; no key gives no bundle and exit 0; failed phase state still seals; key never in logs |
| `tests/test_restore_weekly_artifact.py` | Bundle, legacy, tampered, no key, other-key database; exit 0 always |
| `tests/test_lattes_articles.py` | Case, accents and DOI case match; different DOIs and blank titles do not; one DOI merges |
| `tests/test_article_consolidation.py` | Links repointed; merge log; `~` and plain losers become aliases; survivor's id kept; second pass finds nothing |
| `tests/test_horizon_id_assigner.py` | A suffixed id is never chosen by `_apply_merges` |
| `tests/test_purge_history.py` | On a throwaway repository: blobs rewritten, others untouched, same commits from two runs, `verify` passes, and fails on a planted synthetic address |
| `tests/test_check_publishable_archive.py` | Non-official, no manifest, other fingerprint, over the limit |

`tests/test_download_lattes_flow.py` also has a test that a phase's stdout has no scriptLattes debug line.

## First CI run on a branch

Dispatch with defaults (no `fresh_database`), then check:

```bash
gh run download RUN_ID --repo OWNER/REPO -n weekly-etl-artifacts -D "$TMP/artifact"
find "$TMP/artifact" -maxdepth 2 | head                   # bundle and public/ only
```

| Check | Expected | Criteria |
|---|---|---|
| `restore_outcome.json` | `restored`, `format: legacy` | FR-006 |
| Artifact listing | Only `weekly_state.bundle` and `public/` | FR-003, SC-002 |
| Scan of `public/` | 0 hits | SC-002 |
| Archive scan, all members | 0 emails, 0 phones, 0 formatted CPFs, 0 non-token known fields | SC-001 |
| `export_scan_report.json` | Expected nonzero only if an exporter missed something; look at it | FR-002 |
| Archive size | Under 100 MiB, about 56 MB | SC-010 |
| Marts and graph in the archive | Same run's dates | SC-004 |
| `export_manifest.json` | `official: true`, same fingerprint on both repositories | SC-008 |
| Same person's token, old and new archive | Equal | SC-008 |
| `database_verify_report.json` | 0 everywhere | FR-022 |
| Article report and `~` ids | Merged; old ids resolve in the alias file | SC-005, SC-009 |
| `horizon_ids` outside merges | Identical to before | SC-009 |
| Run log scan | 0 plain patterns | FR-003 |

## Second CI run

| Check | Expected | Criteria |
|---|---|---|
| `restore_outcome.json` | `format: bundle` | FR-005 |
| Documents reprocessed | Only those with changed content | SC-011, FR-020 |
| Rotation, early stop | Report as before | FR-005 |
| Duration | Within 10% of the restored baseline | SC-006 |

## Failure drills

On a test branch:

| Drill | Expected |
|---|---|
| Remove the state key | Run completes; no bundle; warning; next run rebuilds |
| Corrupt an uploaded bundle, by restoring from a doctored `--from-dir` locally | `rebuilt`, nothing unpacked |
| Force a mart to fail | Archive byte-identical, run green, artifact sealed (SC-007) |
| Force a critical phase to fail | No commit, artifact sealed, no plain upload |

## Cleanup after clean runs

Dry-run first, then get the maintainer's confirmation ([contracts/history-purge.md](contracts/history-purge.md)):

```bash
python -m src.scripts.purge_public_artifacts --repo OWNER/REPO --first-clean-run main=RUN_ID
```

The history purge has its own procedure in the same contract; SC-003 is checked by its `verify` mode.
