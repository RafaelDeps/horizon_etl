# Research: PII-Safe Exports and Deduplicated Articles

Measured read-only on 2026-11-05 on the local archive and database, and through the GitHub API. All figures are counts; no value was written anywhere.

## R1. Zip phase

**Decision**: Bring in the code of commit 99f45fe by hand, without its binary zip: `zip_exports_flow`, `export_canonical_data_flow(zip_exports=True)` for in-process callers (`src/flows/pipelines/weekly.py:63`, `unified.py:134`), the `zip_exports` command in `app.py`, and `export_canonical` passing `zip_exports=False`. Unlike that commit, the phase sits right after `people_relationship_graph`, not after the report phases.

```python
("people_relationship_graph", ["people_graph"], 1800, False, "app"),
("zip_exports", ["zip_exports"], 900, True, "app"),
```

`_run_phase` passes `output_dir` for this command. The phase list changed since 99f45fe (`assign_horizon_ids` and others): all of them run earlier, so nothing else moves. The commit's test needs its writer list adjusted, since `ppp_edital_report` now runs after the zip.

**Gate (FR-009)**: In `run_weekly`, before running this phase: if any earlier critical phase failed, or any of `export_canonical`, `knowledge_areas_mart`, `initiatives_analytics_mart`, `people_relationship_graph` failed, it is not run and is recorded as a non-critical failure with reason "skipped". The checked-out archive stays as it was, the commit step's `git diff --cached --quiet` finds nothing, and the run stays green if nothing critical failed. A green run can be restored from, unlike a red one.

**Checked**: Report phases all write under `data/exports/docentes/`, which the zip skips (`OUT_DIR` in the modules). `anonymize_backfill` runs after the zip and changes only values the exporters already scrub.

**Alternatives rejected**: Making marts critical. A mart failure would turn the run red, and the next restore would skip this run's artifact.

## R2. Detectors and exporters

**Decision**:

- `export_initiatives` and `export_advisorships` call `scrub_pii_deep` before `sink.export`, like `export_researchers` (line 1590). `export_production_authors` is integers only and needs nothing.
- Add `_CPF_RE`, formatted CPF only (`ddd.ddd.ddd-dd` with digit boundaries), to `scrub_pii_text` and `is_anonymized_text`.
- Add `_PAYLOAD_EMAIL_FIELDS` to `scrub_source_record_payload`: `OrientadoEmail`, `OrientadorEmail`, `email`, `contact_email`. These are tokenized whatever the format, which covers the 6 malformed `OrientadoEmail` values.

**Measured on the real archive**: 1 email (`initiatives_canonical.json`), 0 `_PHONE_RE` hits, so no false positives, 0 formatted CPFs, 6 non-token `OrientadoEmail` values. All other known-field values are tokens (`OrientadoCpf` 704, `OrientadorEmail` 704, `email` 405).

**Why no bare 11-digit CPF in text**: With weak boundaries, 95 check-digit-valid hits, all inside hex hashes (`value_hash` 79, `payload_hash` 15, `horizon_id` 1). With proper boundaries, 0 hits at an extra 21 s. Rewriting a hash is worse than the gain. Bare CPFs are caught only in known fields, where a number can be numeric (`_PAYLOAD_CPF_FIELDS`).

## R3. Safety net in `zip_exports_task`

**Decision**: For each `.json`, `.csv` and other text member, read the text with `surrogateescape`, apply `scan_text` (the free-text scrub plus a known-field regex on `"key": value` pairs), and:

- unchanged: `zf.write(fpath, arcname)`, so dates stay;
- changed: `zf.writestr(ZipInfo.from_file(fpath, arcname), text)` with deflate, and log the file name and count;
- a binary or unknown extension: left out and logged. The real archive holds only JSON, so this path is a guard.

Never raises on a match. Counts go to `data/reports/export_scan_report.json`. A read or scan error does raise, so the critical phase fails and the previous archive stays. Then the size is checked: over 100 MiB raises before `os.replace` (FR-019). The net also covers the scrubbed project documents written by `writestr` today.

**Cost**: 65 s here over 931 MB for the three text detectors (Python 3.14, includes unpacking), against 26 s measured earlier with a different method. The known-field regex adds 3.5 s. `_EMAIL_RE` is the slow one: it restarts at every position of long hex runs. A lookbehind `(?<![a-zA-Z0-9._%+\-])` should remove the restarts without changing matches; try it during implementation.

**Spec impact**: FR-002 reworded (plan D3).

## R4. Database sanitizing

**Decision**: Extend `anonymize_backfill_flow`. It already runs last, is critical, and is followed by `finalize_sqlite_database`, so the order is: backfill, then VACUUM if rows changed, then finalize (checkpoint TRUNCATE removes old pages from the log).

1. `PII_COLUMN_REGISTRY["description"] = "free_text"`. The backfill discovers it in `initiatives` and six other tables (all have `id`), and the ORM hook covers future writes.
2. A new step for JSON text columns, with a regex prefilter so only hits are parsed:
   - `attribute_assertions.value_json`: scrub, and set `value_hash = stable_hash(new value)` (FR-022). `UPDATE OR IGNORE`; if the unique constraint blocks it, an equal row exists, so delete this one.
   - `entity_change_logs.before_json`, `after_json`: scrub.
   - `source_records.raw_payload_json`: `scrub_source_record_payload` (the 6 malformed values). `payload_hash` stays: it is documented as taken from the original payload.
3. `PRAGMA secure_delete=ON` for this connection; `VACUUM` only when something changed, so normally only once.
4. Store the key fingerprint in `horizon_meta` (R12).

**Stop the inflow**: `record_attribute_assertions` scrubs the value before both hash and write; `record_change` scrubs `before` and `after`. Values without personal data do not change, so their hashes do not change.

**Skip**: Unaffected. It compares a hash of the source document, never stored values.

**Check on the first run**: `initiative_decision` uses a content hash to order `~2`, `~3` collisions, so one changed description could in theory reorder a collision group. Compare `horizon_ids` before and after in validation.

**Alternatives rejected**: A new phase, because it adds a place to fail and needs its own timeout. Sanitizing in the seal step, because a database used locally would stay plain.

## R5. Database in the artifact

**Decision**: The database always goes inside the encrypted bundle (plan D1). Sanitizing and verifying still run, and `database_verify_report.json` reports table, column and count plus a byte scan of the file for freed pages. A nonzero result is a warning in the job summary, never a failure, since nothing plain is uploaded.

**Why**: `source_document_states` holds `content_hash = stable_hash(content)`, an unkeyed SHA-256. For 1,159 documents (`sigpesq_advisorship` 704, `sigpesq_group` 352, `sigpesq_project` 103) the content is one report row, which can include CPF, phone and email, and the scrubbed row is public. So a guess can be confirmed offline. That fails FR-023, and "verified free of plain data" does not catch it because a hash is not plain text. The user also said hashes used by skip must not change.

**Alternatives**:

| Option | Effect | Verdict |
|---|---|---|
| Encrypted database | No skip change, no migration, verify cannot be a false pass | Default |
| Plain if verified, plus keyed compare in `Document.unchanged` and an idempotent migration wrapping `content_hash`, `payload_hash`, `value_hash` with HMAC | Public database stays, no reprocessing if done right; a mistake reprocesses 2,376 documents | Available if the user wants a public database |
| Plain if verified, with `content_hash` unchanged | Fails FR-023 | Rejected |
| Hash map moved into the bundle, stripped from the plain copy | Most code | Rejected |

## R6. Published hashes (FR-023)

**Decision**: `keyed_export_hash(value) = HMAC-SHA256(subkey "export_hash", stored hash)` applied by the exporter: `_enrich_export_rows` for `payload_hash` and `value_hash`, and the `attributes` block near `canonical_exporter.py:870`. Equal values stay equal across exports under one key.

**Checked**: `payload_hash` and `value_hash` are read only by the exporter and in unique constraints; skip uses neither. `content_hash` is not exported (`_STATE_FIELDS` leaves it out), and `horizon_ids` has no such column. `dependency_fingerprint` holds name lookups, not personal data under FR-017.

**Alternatives rejected**: Changing the recorder plus a migration, which is only needed with a plain database (R5). Dropping the fields changes the export format.

## R7. Encrypted bundle

**Decision**: `src/scripts/weekly_state_bundle.py`, using `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.

- **Key**: `secrets.token_bytes(32)`, base64url, in secret `HORIZON_STATE_KEY`. Anything not decoding to exactly 32 bytes counts as no key, so a passphrase is refused. Separate from `HORIZON_PII_HMAC_KEY`.
- **Format**: magic `HZSTATE1`, a 12-byte random nonce from `os.urandom`, then ciphertext and tag; the magic is the associated data. The tag is checked before any plaintext exists, so tampering is caught before unpacking.
- **Inside**: `tar.gz` of `db/horizon.db`, `data/raw`, `cache`. One file, so file names are hidden. Compressed first since encrypted data does not compress.
- **Opening**: Decrypt, then `tarfile.extractall(filter="data")`, plus a check that every member is a regular file or folder under the three allowed roots.
- **Exposure**: The key is read only from the environment, set only on the restore and seal steps, not at job level, so phases and third-party libraries do not see it. Never an argument, never logged. GitHub masks it too.
- **Rotation**: Seal uses `HORIZON_STATE_KEY`; open tries it, then the optional `HORIZON_STATE_KEY_PREVIOUS`. After one successful run the previous one is removed.
- **Forks**: The workflow has only `schedule` and `workflow_dispatch` triggers, so a fork's pull request cannot run it, and `ci.yml`, which does run on pull requests, gets no state key. The contract forbids adding `pull_request_target`.

**Size**: Measured 297 MB gzipped in about 15 s (database, raw, cache). AES-GCM one-shot limit in `cryptography` is 2 GiB minus 1; over it, sealing fails safely: no state uploaded, a warning, and the next run rebuilds.

**Alternatives rejected**: `age`, which is sound but adds an apt step and a key file on disk. `gpg --symmetric` and `openssl enc`, because they are passphrase-based or have no authenticated mode. Encrypted zip, which leaks file names.

## R8. Workflow

**Decision**:

- **Remove** "Compress large export files". It only exists for the broad upload.
- **New step** "Prepare artifact", `if: always()`, `continue-on-error: true`, with `HORIZON_STATE_KEY` in its `env`: `make seal-weekly`. It finalizes the database again (a killed run may leave a log), verifies, seals, stages. It always exits 0.
- **Upload** `path: artifact_out` only, still `if: always()`, same name and 90 days.
- **Stage**: `artifact_out/weekly_state.bundle`, and `artifact_out/public/` with `data/reports/**` and `data/exports/docentes/**` limited to text extensions, each scanned; a file with a hit is left out and logged. Local scan: 188 files, 0 hits.
- **Publish step** adds `check_publishable_archive` before `git add`.

**What leaves the artifact**: `data/exports/*.json` (they are in the committed archive), `data/lattes_json`, `data/exports/project_sigpesq_files_json`, `data/lattes_run`, raw and cache in plain form. Nothing restored comes from the removed paths.

**On failure**: The seal step runs on `always()`, so a failed phase still seals. If no key: nothing plain, a `::warning` and a job summary line, exit 0.

**Not added to "Validate required secrets"**: A missing state key must not stop the run (FR-018).

## R9. Restore, transition, Lattes JSON

**Trace of `data/lattes_json`**: Not restored today (`FOLDERS` is `data/raw` and `cache`). `download_lattes_flow` deletes its JSONs, rotates downloads into `cache/`, then `run_script_lattes_real` regenerates every JSON from `cache_dir` through `generate_config`. So CI rebuilds it each run from the cache, and leaving it out of the artifact loses nothing. If the `lattes_download` phase fails, the folder is empty in CI, the same as today.

**`project_sigpesq_files_json`**: Also not restored. `extract_project_files` reads scrubbed copies from the published archive (`project_files.py:226`), kept by FR-021.

**Restore change**: After download, if `weekly_state.bundle` is present, open it into the work folder, then the existing `place()` runs unchanged. Otherwise treat it as a legacy plain artifact, as today.

| Case | Result |
|---|---|
| First run, old plain artifact | Restored as before; sanitized by backfill at the end; uploaded only sealed |
| Bundle, good key | Restored |
| Bundle, no key or wrong key | `rebuilt`, reason "state bundle: ..."; exit 0 |
| Tampered or truncated | Tag fails before unpacking; `rebuilt` |
| Run without key before (no bundle, no database) | Existing path: "database missing", rebuilt |
| Database with another key's stamp (R12) | Raw and cache placed, database rebuilt |

Errors from `cryptography`, `tarfile` and memory become `RestoreError`; the step also keeps `continue-on-error`.

**Fresh database**: `--disabled` skips raw and cache too. Left as is; not needed by this feature (R11).

**Fork**: With no secret, `Validate required secrets` already stops a fork on `DATABASE_URL` and others. If it had those, it would run without state, rebuilding each time, and upload no plain data.

## R10. Article match at ingest

**Decision**: One helper in `src/flows/lattes/projects.py`, replacing the two lookups at lines 491-504, with column-only SQL as there:

```python
def _find_article(session, title, year, doi):
    wanted = normalize_doi(doi)
    if wanted:
        # candidates by lower(doi) LIKE '%' || :tail, confirmed with normalize_doi
        ...return the lowest matching id
    name = normalize_text(title)
    if not name:
        return None  # blank titles never match
    # SELECT id, title, doi FROM articles WHERE year = :y ORDER BY id
    for row in rows:
        if normalize_text(row.title) == name:
            other = normalize_doi(row.doi)
            if not (wanted and other and other != wanted):
                return row.id
    return None
```

`_fill_missing_article_fields` already gives the survivor the DOI. `source_document_items` already handles an article shared by several documents.

**Normalizer**: `normalize_text`, the one `hash12` uses (plan D4).

**Not done**: No rule-version change. It would reset the database.

## R11. Existing duplicates and `~` ids

**Decision**: `ReferenceConsolidator.consolidate_articles()`, called from `consolidate_duplicates`, which runs before `assign_horizon_ids`. No fresh run.

**Why a fresh run does not work (plan D2)**:

- `Document.unchanged` skips unchanged curricula, so the helper alone never revisits existing rows. That is why a fresh run was suggested.
- On a rebuild, `reconcile` resolves old ids by merge log, candidates or natural key. Old `~` ids with a hash form can resolve by natural key (reason `rebuild`). But `article:doi:...~x` has no natural key, and a loser `article:h:B` that differed in venue has a natural key no current row holds. These retire with no target, against FR-011. Duplicate rows by id form: 167 plain hash, 164 `~` hash, 11 plain DOI, 2 `~` DOI, so an estimated 80 plain-hash losers. This comes from reading `reconcile`; it was not simulated.
- `--disabled` also drops raw and cache, so it re-downloads everything. Recent long runs took 220 and 283 min of the 300-minute limit.

**How it works**:

1. Group by normalized DOI; then by normalized title and year. A group with two different DOIs only merges rows with the same DOI; DOI-less rows in it are left alone. Blank titles are never grouped.
2. Survivor: lowest `id_priority` of the id without its `~` suffix, then lowest row id. So a DOI row wins, and the survivor keeps its id and ties cannot move it.
3. In one transaction per group: fill empty fields; `UPDATE OR IGNORE` then delete leftovers for `article_authors`, `entity_matches`, `attribute_assertions`, `entity_change_logs` (`canonical_entity_type='article'`), `source_document_items` (`article`, and `article_author` refs `a:r`); delete the loser; `record_merge`.
4. Report with counts to `data/reports/article_consolidation_report.json`.

**How `~` ids retire**: `record_merge` receives `merge_candidates("article", row)` (new branch: `article_decision(row).candidates`), the loser's current `horizon_id`, and the survivor's current id when it has a `~`. `reconcile` puts these in `merged`, so each becomes a `merge` alias of the survivor. After the merge there is no collision, so the survivor gets the bare id. `_apply_merges` needs one guard, `"~" not in c` in its pool, so a suffixed id cannot be chosen as permanent. A survivor going from `X~a` to `X` is the one id change SC-009 must allow, and `X~a` stays resolvable.

**Baseline**: 204 `~` article ids. With punctuation folding, 195 title groups (394 rows, 2 with conflicting DOIs) and 6 DOI groups (12 rows); only 10 `~` ids lie outside title groups. The spec's 169 used a slightly different folding than this count's 171 for case and accents; recount with the final normalizer. Fixpoint: a second pass finds nothing.

## R12. One official key

**Decision**:

- `key_fingerprint()` = first 16 hex of HMAC(subkey "fingerprint", fixed label). Publishing it reveals no more than the tokens do.
- `zip_exports_task` adds `export_manifest.json`: `{"official": bool, "key_fingerprint": ...}`. `official` is true only when `GITHUB_ACTIONS=true`.
- `check_publishable_archive.py`: refuses a non-official archive, one over 100 MiB, or one whose fingerprint differs from the archive at `HEAD` when that one has a manifest. In the weekly commit step, refusal is a `::warning`, the archive is restored with `git checkout`, and it exits 0. In `ci.yml`, when the archive changed in the push or pull request, refusal fails the check. In `.githooks/pre-commit`, the same; note `core.hooksPath` is unset here, so CI is the real guard.
- `anonymize_backfill` stamps `horizon_meta.pii_key_fingerprint`. Restore compares it when set; a difference means the database is rebuilt. An unstamped database (transition) is accepted, then stamped.

**Restore sources** stay CI only: the `--github` mode uses the same repository and branch, successful runs only. `--from-dir` and `--from-zip` remain for local simulation and are not used by the workflow.

**Not verified**: That both repositories' secrets hold the same key. The clarify step inferred it from shared tokens.

## R13. History purge

**Decision**: `src/scripts/purge_history_pii.py`, run with git-filter-repo's own Python, because the module is not importable from the project's (`~/.local/share/uv/tools/git-filter-repo/bin/python`). Modes: `plan`, `rewrite`, `verify`. Details in [contracts/history-purge.md](contracts/history-purge.md).

- Blob callback filtered by `blob.original_id` (present in the installed version, 2.47.0) against a target set computed first from `git rev-list --objects --all` by path: `data/exports/*.zip` and `cache/*`. Paths are not available in a blob callback, and matching any text blob would alter code and test fixtures.
- Zips: Only members with hits are changed; other members keep date and compression. Cache files: text replaced.
- Replacement is the constant `redacted@anon.lgpd`, with matching constants for phone and CPF. It needs no key, the CI key cannot be read back, and old tokens have no consumers. The same input gives the same output, so both repositories should converge on the same new commits; this needs proving on a test.
- Fresh `--mirror` clones, with `refs/pull/*` removed before the rewrite, because they cannot be pushed.

**Cost**: 44 archive versions at about 50 MB each, 38 cache blobs, 428 commits. Not timed.

**Not run by this feature.** Needs the user's confirmation listing branches and remotes.

## R14. Deleting artifacts and logs

**Decision**: `src/scripts/purge_public_artifacts.py`: dry-run by default; `--execute` needed to delete. It lists per repository and branch, and deletes artifacts older than the first clean run of that branch, never a clean run's own. The maintainer names that run per branch (`--first-clean-run BRANCH=RUN_ID`), and the script refuses it unless it succeeded and its artifact holds `weekly_state.bundle`. `--include-branches-without-clean-run` covers plan D5. `--logs` also deletes those runs' logs (`DELETE /actions/runs/{id}/logs`).

**Counts on 2026-11-05**: origin 24 (`main` 4; on 10 feature branches 20: `026` 4, `025` 3, `028` 3, `022` 2, `023` 2, `027` 2, and `020`, `024`, `feat/003`, `fix-sqlite-finalize-lock` 1 each); ifesserra-lab 4 (`main`).

## R15. Public run logs (new finding)

**Measured**: Logs of 2 recent runs on origin: both have 1 email-shaped hit; one has 1 phone pattern, the other 2 CPF patterns. All sit in lines printed by scriptLattes debug `print`s (`parserLattes.py:601`, `producoesUnitarias/atuacaoProfissional.py:34`), which echo curriculum lines. In one run, about 6,900 of 33,500 log lines look like this.

**Decision**: In `run_script_lattes_real`, wrap `executar_scriptLattes` with `contextlib.redirect_stdout` to null, keeping loguru's stderr and a final count. This also shortens the log. Old logs are deleted by R14. Other phases were not reviewed beyond these 2 logs; add a quickstart check on the first clean run.

**Spec impact**: FR-003 now names run logs. For the user's review (plan D6).

## R16. Tracked files at the tip

**Decision**: `git rm --cached` for `cache/` (16 files, already ignored; CI gets them from restore), `.prefect/` (4 files) and `data/exports/data_snapshot.zip` (only default output of `src/scripts/zip_exports.py`; no reader).

**Local count at `HEAD`**, zips apart: `cache` 4 emails and 16 phones; `.prefect/prefect.db-wal` 2 email-shaped; `specs/013-curate-export-zip` 3; `src/scripts/fetch_openalex_citations.py` 1; `.specify`, `.opencode` 1 each, a `github.com` address; `lattes_generators.py` 1 at an example domain; tests use synthetic values, not individually checked. `data/exports/formandos/relatorio_institucional.pdf`: 1 byte-level hit, 0 in `pdftotext` output, so probably not visible text.

The tracked report HTML files (10) were covered by this byte scan. The one tracked PDF was also read with `pdftotext`.

## R17. Duration (SC-006)

| Item | Estimate | Basis |
|---|---|---|
| Safety net | +65 s, less with the regex fix | Measured locally, not on a runner |
| Database verify | about +60 s | Rough, from the scan here; not timed separately |
| Seal | +20 s | gzip measured at 15 s, AES not timed |
| Open at restore | +10 s | Not measured |
| Recorder, helper | Negligible | Most documents are skipped |
| Archive phase moved | About 0 | It already ran inside `export_canonical` |
| Compress step, 931 MB less to upload | Saves time | Not measured |

Total about +2.6 min before savings, within the budget of about 4 min. Validate on a real run.

## What Was Measured and What Was Not

**Measured**: Archive and database scans, known fields, article groups and id forms, tracked files at `HEAD`, reports folders, artifact counts, durations of 15 runs, logs of 2 runs, bundle size and gzip time.

**Not verified**:

- No code was written or run, and no test exists yet. pytest is not in `.venv`. 99f45fe's test never ran.
- Blob callback behavior on real history, its speed, and convergence across both repositories.
- `always()` steps after a job timeout, and memory on a runner for one-shot AES-GCM. Peak should be about 600 MB.
- Silencing stdout around `executar_scriptLattes`: whether its internals depend on stdout.
- Whether GitHub Support will purge what is asked. The purge can't be proven complete from outside.
- Phone and CPF in the raw PDFs and Office files: moot once they are encrypted, but they sit in old artifacts until deletion.
- Old archive versions were not rescanned here; the spec's figures are from the clarify step.
