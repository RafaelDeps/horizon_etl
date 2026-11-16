# Contract: State Bundle

Module `src/scripts/weekly_state_bundle.py`. Format in [data-model.md](../data-model.md).

## Seal

```text
make seal-weekly     # python -m src.scripts.weekly_state_bundle seal --out artifact_out
```

Steps, each guarded, and the command always exits 0:

1. `finalize_sqlite_database` again; a run that was killed may have left a log.
2. Verify the database; write `database_verify_report.json`.
3. Read the key. Not exactly 32 bytes in base64url: state `skipped`, `::warning`, job summary line, go to step 5.
4. Build the tar.gz of the three items in a temp folder inside the workspace, encrypt, write `artifact_out/weekly_state.bundle`, remove the temp. On any error: remove partial files, state `failed`, warning.
5. Stage public text files, scanning each. Write `artifact_stage_report.json` and copy it in.

The plain database and raw files are never copied to `artifact_out`.

## Open

```python
open_bundle(path, dest) -> None     # raises RestoreError
```

1. Check magic and length.
2. Decrypt in one call with the current key, then the previous key if set. `InvalidTag` on all: `state bundle: failed authentication`. No plaintext exists before this succeeds.
3. List members. Any absolute path, `..`, link, device, or a member outside `db/horizon.db`, `data/raw/`, `cache/`: `state bundle: unsafe member`, nothing extracted.
4. `extractall(dest, filter="data")`.

No error message contains key material or a file's content.

## Restore behaviour

Added to `restore_weekly_artifact.restore`, between download and `place`:

- `weekly_state.bundle` in the download: open it. Failure ends in `rebuilt`.
- Not there: legacy layout, as today, `format: legacy`.

`place` then adds the key-stamp check to `check_database`. Exit code stays 0 in every case.

## Generating and rotating the key

Run by the maintainer, not by any script in this feature:

```bash
python -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())" | gh secret set HORIZON_STATE_KEY --repo OWNER/REPO
```

The value goes through a pipe, so it is never an argument and never on screen. Each repository gets its own key.

Rotation: copy the old key to `HORIZON_STATE_KEY_PREVIOUS`, set the new one, let one run succeed, delete the previous secret. Because GitHub secrets cannot be read back, a rotation needs the maintainer's saved copy of the old key; without it, the next run rebuilds. On a suspected leak: rotate and delete old artifacts.

## Never

- No `pull_request_target` or `pull_request` trigger on the weekly workflow.
- No key at job level, in a file, or as an argument.
- No decryption without the tag check, and no streaming plaintext before it.
