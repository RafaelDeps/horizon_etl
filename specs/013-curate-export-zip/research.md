# Research: Curated Export Archive

**Branch**: `013-curate-export-zip` | **Date**: 2026-09-18

Phase 0 output. Every unknown was resolved by reading the affected code; the
two scope decisions were answered by the user during specification and are
restated here as D2 and D3.

## D1 — Where to scrub the PJ corpus for the archive

**Decision**: Scrub at zip time, in memory, inside `zip_exports_task`
(`src/flows/exports/canonical_data.py`), reusing
`src/core/logic/pii_anonymizer.scrub_pii_deep`, and write the copies with
`zf.writestr` under the same relative path
(`project_sigpesq_files_json/PJ_<code>.json`).

**Rationale**:
- `scrub_pii_deep` is the project's single LGPD scrubber (recursively replaces
  e-mails → `<hash>@anon.lgpd`, phones → `LGPD-PHONE-<hash>`; idempotent via
  `is_anonymized_email`/`is_anonymized_phone` guards). Reusing it guarantees
  consistency with the DB backfill and the source-record payload scrubber.
- The raw corpus must stay untouched: it is the resumable input of the
  extraction stage (`extract_json` skip-if-exists depends on it) and carries
  provenance (`_meta`) that must remain faithful.
- Scrubbing at write time costs one JSON parse/dump per small file —
  negligible against the corpus size.

**Alternatives considered**:
- *Persist a sanitized sibling corpus* (`project_sigpesq_files_json_sanitized/`):
  doubles disk use, introduces staleness risk (which copy is current?), and
  was explicitly rejected by the user ("as first" — keep the archive path).
- *Anonymize at extraction write time* (`extract_json` scrubs before writing
  the local JSON): mutates the raw corpus and silently changes what
  `record_source_record(payload=pj)` stores and what a future re-run compares;
  broader blast radius than the feature needs.

## D2 — Exclusion mechanics for the archive walk

**Decision** (user-confirmed): 
- Directories: extend `SKIP_DIRS` to
  `{project_sigpesq_files_json, formandos, docentes, mestrado, parquet}`.
  `project_sigpesq_files_json` **stays** in `SKIP_DIRS` — it keeps the *raw*
  folder out of the walk; the scrubbed copies are added by the explicit
  post-walk block, so there is exactly one inclusion path for PJ files.
- Files: skip any file whose name ends with `.zip` (not just
  `data_snapshot.zip`). A zip inside a zip is never intended; this also
  covers `exports_canonical.zip`, its `.tmp` sibling, and any future snapshot
  archive without list maintenance.

**Rationale**: the walk prune already exists and is tested
(`test_zip_excludes_source_documents.py`); extending two collections is the
smallest possible change. The `SKIP_DIRS` name/dict remains the single source
of truth for directory exclusions.

**Alternatives considered**: filename list (`data_snapshot.zip` only) —
rejected: literal-but-brittle, future zips would leak back in (user chose the
general rule).

## D3 — Parquet removal scope

**Decision** (user-confirmed): remove the parquet step from the canonical
export flow entirely — delete `export_parquet_task` and its call in
`export_canonical_data_flow` (canonical_data.py:365). Weekly, full pipeline
(`unified.py`) and manual `app.py export_canonical` all stop emitting
`parquet/`. The script `src/scripts/export_parquet.py` stays for manual use.
ADR-003 is amended to record that the weekly archive no longer carries the
parquet mirror.

**Rationale**: `export_canonical_data_flow` is the only caller
(grep-verified); a "weekly-only" flag would add a parameter that every caller
must understand to serve a format nobody currently consumes in the flow. The
script keeps the capability alive at zero maintenance cost.

**Alternatives considered**: flow parameter (`with_parquet=True` default,
weekly passes False) — rejected: added complexity for a dead code path;
the user chose full removal.

## D4 — How the extraction step finds and trusts the archive

**Decision**: in `SigPesqProjectFilesAdapter.extract_json`
(`src/adapters/sources/sigpesq/project_files.py`), the archive is located
relative to the corpus: `os.path.join(os.path.dirname(self.json_dir),
"exports_canonical.zip")`. For each pending PDF (no local JSON, `force`
not set), look up entry `project_sigpesq_files_json/<stem>.json`; on a hit
that parses as JSON, write it to `json_dir` with the same formatting the
extraction stage uses (`ensure_ascii=False, indent=2`), count it in a new
`stats["reused"]`, and skip the extractor. Missing archive, missing entry,
malformed entry, or unreadable archive → normal extraction for that project.
`force=True` bypasses reuse entirely.

**Rationale**:
- Same-stem matching reuses the existing naming discipline (the filename is
  the authoritative project code — `_codigo_from_filename` in the library).
- Locating the archive next to `json_dir` respects the `OUTPUT_DIR` env var
  used by CI and manual runs without new configuration.
- The archived copy was already validated by `finalize()` when it was first
  extracted; a `json.loads` guard is enough to catch truncation/corruption.
- Fallback-on-any-doubt keeps the phase non-critical (weekly orchestrator
  treats `extract_project_files` as non-critical).

**Timing note**: within one weekly run, the archive is written by
`export_canonical`, which runs *after* `extract_project_files` — so the reuse
step always consults the **previous** run's archive (or none on a fresh
runner). This matches the spec's "latest export archive" wording; the weekly
db-reset does not wipe `data/`, so local JSONs persist and reuse mainly
benefits fresh/restored environments — exactly the scenario the user asked
for.

**Alternatives considered**:
- *Mark reused files* (e.g. inject `_meta.fonte_texto = "archive"`): rejected
  — mutates provenance data that was honest at extraction time; the `reused`
  stat plus logs give the observability instead.
- *Global zip search by project code* (not stem-path): rejected — the archive
  path is deterministic; anything else hides layout drift.

## D5 — Test strategy

**Decision**: db-less, offline, fast — mirroring the repo's established
patterns:
- Zip behavior: call `zip_exports_task.fn(str(tmp_path))` on a temp exports
  dir (pattern already used by `test_zip_excludes_source_documents.py`) and
  assert on `zf.namelist()` + blob content.
- Reuse behavior: build a real zip in `tmp_path`, point a
  `SigPesqProjectFilesAdapter` at temp dirs, monkeypatch
  `agent_sigpesq.extraction.ProjectExtractor` (the lazy import inside
  `extract_json`) with a fake counting calls; assert hit → 0 calls + file
  restored; miss/malformed/bad-zip → fallback; `force` → always extract;
  local-exists → never consulted.
- `test_export_canonical_data_flow.py` needs no change: it never pinned the
  parquet task (verified), and `zip_exports_task` is already patched there.

**Rationale**: no live Prefect server, no network, no Mistral key — the whole
suite stays in the fast CI lane.

## D6 — Documentation impact

**Decision**: amend ADR-003 (status note: parquet emission removed from the
flow; script + manual invocation remain; dashboard keeps consuming the JSON
mirror of `src/data` as before — unaffected because the dashboard build reads
its own repo copies, not the ETL archive). Add a short zip-contents note to
`docs/outputs-and-artifacts.md`. No other docs reference the archive
contents.

**Rationale**: ADR-003 explicitly states the parquet lives "dentro do zip" —
leaving it unamended would make the record false after this feature.
