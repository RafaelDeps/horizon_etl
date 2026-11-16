# Implementation Plan: PII-Safe Exports and Deduplicated Articles

**Branch**: `029-pii-safe-exports` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/029-pii-safe-exports/spec.md`

## Summary

Nothing plain leaves the runner. The archive is built in a new critical phase right after the people graph, from exporters that all scrub, with a final safety net that replaces any match and never stops the run. The run artifact becomes an allow-list: one encrypted bundle holding the database, `data/raw` and `cache/` unaltered, plus report files that pass a scan. Because the bundle keeps those files byte for byte, skip hashes, rotation and early stop keep working with no re-ingest. Published hashes get a key at export time, so no hash used by skip changes. Articles match on normalized DOI and title at ingest, and a one-time consolidation clears the existing duplicates through the merge log, so old ids stay resolvable. History purge and artifact deletion are scripts that this feature provides and does not run.

## Technical Context

**Language/Version**: Python 3.12 in CI (`actions/setup-python`); the local `.venv` is 3.14.

**Primary Dependencies**: `cryptography` (AES-256-GCM, already installed through `prefect`, version 50.0.2 locally; becomes an explicit requirement), stdlib `tarfile`/`zipfile`/`hmac`, `gh` CLI (already used by restore), `git-filter-repo` (maintainer's machine only; installed as a uv tool, module not importable from the project's Python).

**Storage**: SQLite `db/horizon.db` (361 MB locally, 92,303 pages, 6 free). Committed `data/exports/exports_canonical.zip` (56.4 MB, 759 members, all JSON, 931 MB unpacked). GitHub Actions artifact (public, 90 days).

**Testing**: pytest. Checked on 2026-11-05 when writing tasks: the local `.venv` has pytest 9.2.0 (the earlier note that it was missing was wrong); `pyproject.toml` lists pytest in the `dev` extra, `requirements.txt` does not, CI installs it. `make test` depends on `prefect-server` (Docker), so implementers run `PYTHONPATH=. .venv/bin/python -m pytest` directly. Nothing in this plan has been run.

**Target Platform**: GitHub Actions `ubuntu-latest`, job limit 300 minutes, on two public repositories (origin and ifesserra-lab).

**Project Type**: ETL pipeline with Prefect flows and operational scripts.

**Performance Goals**: SC-006, at most 10% over the median restored run. Steady restored runs took 36-48 min, so the budget is about 4 min. See R17.

**Constraints**: The workflow must never break before it ends. Restore never fails the run. No `HORIZON_RULE_VERSION` change. Archive under 100 MiB. Simplest solution that follows the present architecture.

**Scale/Scope**: 7,832 articles; 2,376 tracked documents; 242,435 assertions; 39,345 source records; 28 existing artifacts; 42 + 2 archive versions and 38 cache blobs in git history.

## Constitution Check

| Principle | Status | Note |
|---|---|---|
| I. Ports & Adapters | Pass | Scan and hash helpers go in `src/core/logic/pii_anonymizer.py` (no adapter imports). The article lookup stays in the flow's session code, the same place as today's lookup; matching uses `normalize_text`/`normalize_doi` from core. |
| II. Domain-First | Pass | No new domain entity. `export_manifest.json` is an ETL-only marker. |
| III. Prefect Flows | Pass | `zip_exports_flow` has state handlers. Seal, restore, purge and artifact deletion are operational scripts that do no ingest or export. |
| IV. Audit-Driven | Pass | New reports: `export_scan_report.json`, `database_verify_report.json`, `article_consolidation_report.json`. New flow and scripts get tests. |
| V. LGPD | Pass, strengthened | Adds free text, malformed known fields, CPF in text, artifact contents and logs. |
| Rule 1-2 Persistence, idempotency | Pass | Sanitizing and consolidation are fixpoints: a second pass changes nothing. |
| Rule 3 Re-creatable | Pass | Rebuild still works, with no bundle or a bad one. |
| Rule 4 Identity history | Pass | The archive stays a read-only id source. Merged ids become aliases. |
| Rule 5-6 Raw inputs | Pass | Raw files and manifests travel unaltered. |
| Workflow gate | Pass | Workflow steps call Makefile targets (`make seal-weekly`, `make restore-weekly`). |

Post-design re-check: pass, no violations to justify.

## Key Design Decisions

Details and alternatives are in [research.md](research.md).

1. **Zip phase (R1)**: `zip_exports` right after `people_relationship_graph`, critical, skipped when a required phase failed. Skipping leaves the checked-out archive untouched, so the commit step finds no change and the run stays usable for the next restore.
2. **Safety net (R3)**: Inside `zip_exports_task`, per member. It never raises on a match. On the real archive it found 1 email and 6 malformed known-field values, 0 phones and 0 formatted CPFs, so `_PHONE_RE` has no false positives there. Bare 11-digit numbers are not scanned in text: a first attempt hit 95 places inside hex hashes.
3. **Database sanitizing (R4)**: Extends `anonymize_backfill`, so no new phase, and it already runs last, before `finalize_sqlite_database`. VACUUM runs only when rows changed, then finalize truncates the log. The recorder scrubs at write time so the plain values stop arriving.
4. **The database travels encrypted (R5)**: **Confirmed by the user (D1).** `source_document_states.content_hash` is an unkeyed hash of plain source rows, and skip compares it, so a plain database cannot satisfy FR-023 without changing a hash used by skip.
5. **Published hashes (R6)**: `payload_hash` and `value_hash` become an HMAC of the stored hash, at export time only. No database, recorder or skip change.
6. **Bundle (R7)**: AES-256-GCM one-shot through `cryptography`. The tag is verified before any byte is unpacked. Measured input: database, raw and cache compress to 297 MB in about 15 s.
7. **Artifact (R8)**: The upload path is a single staged folder. Nothing else can be uploaded, whatever fails earlier. With no key the staged folder simply holds no state.
8. **Articles (R10, R11)**: Ingest helper, plus a one-time `consolidate_articles` in the existing `consolidate_duplicates` phase. **No `fresh_database=true` run (D2, confirmed).**
9. **Public logs (R15)**: New finding. scriptLattes debug prints put curriculum lines, including phone and CPF patterns, into public run logs. They are redirected away from the log, and old logs are deleted with the artifacts.

## Decisions for the User (answered 2026-11-05)

The user has answered D1-D9; the Answer column records it. The open part of D7 was closed on 2026-11-05: `MAILTO` stays hard-coded in `src/scripts/fetch_openalex_citations.py`, is not moved to `.env`, and no terms file is needed for it.

| # | Decision | Plan's default | Why it needs you | Answer |
|---|---|---|---|---|
| D1 | Database always inside the encrypted bundle | Yes | You allowed plain if verified. Verification cannot clear `content_hash`, and you said skip hashes must not change. The alternative is a keyed compare in `Document.unchanged` plus a one-time migration of `content_hash`, which keeps a public database but changes the stored skip hashes. Cost of the default: with no key the database does not persist, and inspecting a CI database needs the key. | Accepted: always encrypted inside the bundle; skip hashes unchanged. |
| D2 | No `fresh_database=true` run | None needed | This corrects what you were told. A fresh run alone would retire an estimated 80 merged ids with no target (not simulated), which breaks FR-011, and `--disabled` also discards raw and cache, so it downloads everything (the slowest recent runs took 220 and 283 min of the 300 limit). | Accepted: no fresh run; one-time `consolidate_articles` through the merge log; `~` ids become aliases; small guard in `_apply_merges`. |
| D3 | FR-002 reworded: a match is replaced and reported, not a publish stop | Reworded in spec | Your guidance ("never raise on a match") contradicted the earlier spec text. | Accepted: FR-002 stands as reworded. |
| D4 | Title normalizer also folds punctuation | Use `normalize_text`, the one ids already use | FR-010 says case and accents only. Folding gives 195 groups (2 with conflicting DOIs) against 171 (1). Those 24 extra groups already collide as `~` ids. | Accepted: `normalize_text`; FR-010 and SC-005 updated. |
| D5 | Artifacts on branches that will never run again | Delete them right after the first clean run on `main` | FR-016 says "first clean run on each branch", but 20 of origin's 24 artifacts are on 10 feature branches that may not get one. Without this they stay public up to 90 days. | Accepted: delete right after the first clean run on `main`. |
| D6 | Public run logs | Stop the prints; delete old logs with the artifacts | Not in your answers. Logs of 2 runs were checked: both hold plain-pattern lines. Log deletion cannot be undone. | Accepted: silence scriptLattes prints; delete old logs with the artifacts, after the first clean run. |
| D7 | Other tracked files | Untrack `cache/` (16 files), `data/exports/data_snapshot.zip` and `.prefect/` (4 files, 2 email-shaped hits in the log file) from the tip | `.prefect/` was not in the baseline. Should the purge also cover `.prefect/` history? Also please look at `specs/013-curate-export-zip` (3 email-shaped) and `src/scripts/fetch_openalex_citations.py` (1): are they real addresses? | Accepted: purge also covers `.prefect/` history; untrack `cache/`, `data/exports/data_snapshot.zip`, `.prefect/` from the tip. Closed 2026-11-05: `MAILTO` in `src/scripts/fetch_openalex_citations.py` stays in the code, not in `.env`. The 3 hits in `specs/013-curate-export-zip` are placeholders. The replacement list stays configurable but is not needed for these. |
| D8 | Old hashes in history | Purge also blanks `payload_hash` and `value_hash` in old archive versions | Beyond "emails", but otherwise FR-023's exposure stays in history. It is a flag and can be turned off. | Accepted: blank `payload_hash` and `value_hash` in old archive versions; flag, on by default. |
| D9 | Secret `HORIZON_STATE_KEY` | One random key per repository, created by you before merge | Without it the runs are safe but rebuild every time. Keep a private copy if you want to open a bundle locally. | Accepted: the user creates `HORIZON_STATE_KEY` on each repository before merge. |

### Readings from the clarify step, for your review

- **FR-009**: A portal early stop, or a non-critical phase after the archive build, does not block publishing. In the design, the two marts and the graph block the archive build even though they stay non-critical phases: the run stays green and the previous archive stays. Report phases cannot block.
- **FR-010**: A DOI on only one record still merges, and the survivor keeps the DOI. Two different DOIs stay separate. A DOI-less record in a group with two different DOIs joins the lowest id at ingest, as today, and consolidation leaves existing ones alone.
- **FR-020**: At most one re-baseline run. With unaltered encrypted files the design needs zero.
- **SC-006**: 10% limit over the median of recent restored runs. Recent successful runs range from 29 to 283 min and the median of the last 15 is 98 min, but that mixes rebuilds and restores. The baseline should use only runs whose `restore_outcome.json` says restored; those look like 36-48 min, which needs confirming.

## Project Structure

### Documentation (this feature)

```text
specs/029-pii-safe-exports/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── archive-build.md
│   ├── state-bundle.md
│   ├── workflow-artifact.md
│   └── history-purge.md
└── tasks.md             # /speckit-tasks, not created here
```

### Source Code (repository root)

```text
app.py                                        # zip_exports command; export_canonical passes zip_exports=False
.github/workflows/weekly-etl.yml              # seal step, staged upload, publish gate, no compress step
.github/workflows/ci.yml                      # archive publish check
.githooks/pre-commit                          # same check (the hook is not enabled locally: core.hooksPath is unset)
Makefile                                      # seal-weekly and purge targets
requirements.txt                              # explicit cryptography
.gitignore                                    # artifact_out/, .prefect/
src/core/logic/pii_anonymizer.py              # CPF in text, known fields, scan_text, keyed_export_hash, key_fingerprint
src/core/logic/canonical_exporter.py          # scrub in initiatives and advisorships; keyed hashes on export
src/core/logic/horizon_identity.py            # merge_candidates for articles
src/core/logic/horizon_id_assigner.py         # a ~ id never wins a merge
src/core/logic/reference_consolidator.py      # consolidate_articles
src/tracking/recorder.py                      # scrub assertions and change logs before hash and write
src/flows/exports/canonical_data.py           # zip_exports_flow, safety net, manifest, size limit
src/flows/lattes/projects.py                  # _find_article helper
src/flows/lattes/download.py                  # library stdout kept out of the public log
src/flows/maintenance/anonymize_backfill.py   # tracking JSON columns, VACUUM, key stamp
src/flows/pipelines/weekly_orchestrator.py    # zip phase and its gate
src/scripts/consolidate_duplicates.py         # calls consolidate_articles in the weekly phase
src/scripts/restore_weekly_artifact.py        # opens the bundle; legacy artifacts; key stamp check
src/scripts/weekly_state_bundle.py            # NEW: seal and open, public staging, verify
src/scripts/check_publishable_archive.py      # NEW: publish gate
src/scripts/purge_history_pii.py              # NEW: not run by this feature
src/scripts/purge_public_artifacts.py         # NEW: not run by this feature
tests/                                        # see quickstart.md
```

**Structure Decision**: The existing layout. Three existing Python modules get most of the logic, and new files are only operational scripts next to `restore_weekly_artifact.py`.

## Complexity Tracking

No constitution violations to justify.

## Not Verified

Everything here is a design; no code was changed or run. See the end of [research.md](research.md) for what was measured and what was not.
