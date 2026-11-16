# Contract: History Purge and Artifact Deletion

**Neither of these runs as part of this feature.** Both rewrite or delete public things and need the maintainer's explicit confirmation, listing branches and remotes.

## `purge_history_pii.py`

Run with git-filter-repo's interpreter:

```bash
PY=~/.local/share/uv/tools/git-filter-repo/bin/python
"$PY" src/scripts/purge_history_pii.py plan    --repo /path/mirror.git
"$PY" src/scripts/purge_history_pii.py rewrite --repo /path/mirror.git [--no-redact-hashes]
"$PY" src/scripts/purge_history_pii.py verify  --repo /path/mirror.git [--terms-file FILE]
```

| Mode | Does |
|---|---|
| `plan` | Writes nothing. Lists refs, target blobs per path, and hits per blob as counts. |
| `rewrite` | Refuses a repository that is not a bare, fresh mirror, or that has remotes still set for push. Removes `refs/pull/*`. Rewrites target blobs. |
| `verify` | Scans every target blob of every branch and tag, inside zips. Exit 1 on any hit. Counts per path only. Optional `--terms-file` holds the coordinator's email, one term per line, outside any repository; it also searches all blobs and commit messages. |

**Targets**: Blob ids reachable at `data/exports/*.zip`, `cache/*` or `.prefect/*` in any ref (user decision D7), computed before the rewrite.

**Rewriting a zip**: Open from bytes; for each member run the detectors; members without hits are copied with their original date and method; the blob is replaced only when something changed. A blob that cannot be opened as a zip is reported and left, and `verify` then fails.

**Replacement**: Constants, so the rewrite is deterministic and needs no key. `redacted@anon.lgpd`, `LGPD-PHONE-redacted`, `LGPD-redacted`. Known fields as in `scan_text`. By default, `payload_hash` and `value_hash` values in members are blanked.

**Configurable replacement list (D7, closed 2026-11-05)**: `--extra-terms-file FILE` (outside any repository) adds literal strings to replace in target blobs. The default list is the detectors only. `MAILTO` in `src/scripts/fetch_openalex_citations.py` stays in the code by user decision, and that file is not a purge target.

**Re-runnable**: A second pass over the result changes nothing.

## Procedure

For each repository, origin and ifesserra-lab:

1. Announce it; collaborators must re-clone afterwards. Open branches are invalidated.
2. Disable the weekly workflow (`gh workflow disable`) so no run pushes during the purge.
3. `git clone --mirror`; keep an offline backup, which itself holds plain data: store it privately and delete it afterwards.
4. Save `horizon_ids_canonical.json` and `horizon_id_aliases_canonical.json` hashes from the tip archive.
5. Run `plan`. **Stop: show the maintainer the list of branches, tags and remote, and get confirmation.**
6. Run `rewrite`, then `verify`.
7. Compare the id files of the tip archive with step 4: identical. Compare the tip trees: only target paths differ.
8. `git push --force --mirror` of heads and tags only.
9. Fresh clone; run `verify` again.
10. Re-enable the workflow; dispatch a run; confirm that restore and publish work.

Then, once for both repositories:

11. Contact GitHub Support on **both** repositories: purge cached views, unreachable commits by SHA, `refs/pull/*`, and fork-network copies. A force-push does not rewrite pull-request refs, and old commits can stay reachable by SHA until then.
12. Collaborators re-clone. Local branches not pushed are not covered; the maintainer's own clone also holds old objects.

**Not covered**: Other people's forks and clones, and anything already downloaded. Addresses that remain public elsewhere stay public.

## `purge_public_artifacts.py`

```bash
python -m src.scripts.purge_public_artifacts --repo OWNER/REPO --first-clean-run main=RUN_ID                 # dry run: lists only
python -m src.scripts.purge_public_artifacts --repo OWNER/REPO --first-clean-run main=RUN_ID --execute [--logs] [--include-branches-without-clean-run]
```

- A clean run: named by the maintainer per branch with `--first-clean-run BRANCH=RUN_ID`. The script refuses it unless the run succeeded and its artifact, downloaded to a temp folder, holds `weekly_state.bundle`.
- Per branch: delete artifacts older than its first clean run; never delete an artifact of a clean run.
- `--include-branches-without-clean-run`: also deletes every artifact of a branch with no clean run. Used right after the first clean run on `main`; those branches then rebuild if they ever run again.
- `--logs`: also deletes the logs of those runs. Cannot be undone.

Counts on 2026-11-05: origin 24, ifesserra-lab 4.
