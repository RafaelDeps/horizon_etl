# Research: Weekly CI Workflow Validation and Export Compression

## Decision 1: Chrome/Chromedriver for Lattes in CI

**Decision**: Install `chromium-browser` + `chromium-driver` from apt on ubuntu-latest; set `CHROME_BINARY=/usr/bin/chromium-browser` and `CHROMEDRIVER_PATH=/usr/bin/chromedriver`.

**Rationale**: Playwright does NOT bundle chromedriver — it uses its own CDP protocol internally. Selenium (used by scriptLattes) requires a standalone chromedriver binary. The `chromium-browser` + `chromium-driver` apt packages are an auto-versioned pair (guaranteed version-match), identical to the Dockerfile approach. They are available on ubuntu-latest without extra configuration. Installing them takes ~5s and eliminates any version mismatch between browser and driver.

**Alternatives considered**:
- Reuse Playwright Chromium binary path: Playwright stores Chromium at `~/.cache/ms-playwright/chromium-<rev>/chrome-linux/chrome` but there is no bundled chromedriver. Path is runtime-dependent.
- `webdriver-manager` pip package: Downloads chromedriver at runtime matching installed Chrome; adds network dependency and pip install step.
- `browser-actions/setup-chrome` GitHub Action: Manages Chrome + matching chromedriver; works but adds an external Action dependency for what apt handles natively.

## Decision 2: Export File Compression Approach

**Decision**: `find data/ -type f -size +10M ! -name '*.zip' -exec sh -c 'for f; do zip -m -j "$f.zip" "$f"; done' sh {} +`

**Rationale**: `find -size +10M` targets files strictly over 10 MB (matches spec threshold). The `! -name '*.zip'` guard (added 2026-10-14) is essential now that `exports_canonical.zip` is committed: without it, the step re-wraps the archive as `exports_canonical.zip.zip`, so the file that reaches git is not the one `make weekly-flows` produced. `zip -m` moves the original into the archive (deletes source after compression). `-j` strips directory paths so the archive extracts cleanly. Running in a `sh -c` loop batches multiple matches without spawning one `zip` process per file. No extra tooling needed — `zip` is pre-installed on ubuntu-latest.

**Alternatives considered**:
- `gzip` per-file: Produces `.gz` not `.zip`; less portable for Windows consumers downloading artifacts.
- `actions/upload-artifact` built-in compression: v4 compresses the full artifact but doesn't reduce per-file threshold control.
- GNU parallel: Faster for many large files but requires `parallel` installed; overkill for ~1-3 files over 10 MB.

## Decision 3: Artifact Retention Period

**Decision**: 30 days via `retention-days: 30` on `actions/upload-artifact@v4`.

**Rationale**: Weekly schedule = 4 runs/month. 30 days covers the last 4 runs with room for debugging. GitHub default (90 days) would retain 12+ runs, wasting storage. 7 days risks losing the previous run before the next completes.

**Alternatives considered**:
- 90 days (default): Retains ~13 runs; excessive for a dataset refreshed weekly.
- 7 days: Too short; if a run fails on Saturday and is only noticed Monday, the prior artifact is already gone.

## Decision 4: `permissions: contents: write` + `actions: write`

**Decision**: Set `contents: write` and `actions: write` in the workflow-level permissions block (amended 2026-10-14; `contents` was `read`).

**Rationale**: GitHub's fine-grained token model sets any unspecified permission to `none` when a `permissions:` block exists. `actions/upload-artifact@v4` requires `actions: write` to create artifact entries in the Actions API. Since the workflow now also commits and pushes the export archive (Decision 6), it additionally needs `contents: write`; without it the `git push` fails with a 403. Minimal privilege is preserved — only the two scopes actually used are granted.

**Alternatives considered**:
- Remove `permissions:` block entirely: Reverts to permissive defaults; against security best-practice of minimal privilege.
- Add only at job level: Equivalent; workflow-level is cleaner and applies to all future jobs.

## Decision 6: Publish `exports_canonical.zip` by committing it (2026-10-14)

**Decision**: After the weekly flows succeed, commit `data/exports/exports_canonical.zip` (updating the tracked file) and push it, only when the staged content differs; and exclude the archive from the CI artifact upload.

**Rationale**: `exports_canonical.zip` is the single curated dataset deliverable (feature 013). Leaving it to a manual `download artifact → copy → commit` step is error-prone (the artifact list is 30 days deep, and the pre-fix compression step silently re-wrapped the file). Committing it makes git the canonical, always-latest source and removes the manual step. `if: success()` guarantees a partial archive from a failed run is never published. `git diff --cached --quiet` guarantees no empty/duplicate commits. Excluding it from the artifact removes the redundant download channel.

**Alternatives considered**:
- Keep publishing as an artifact and let a human commit it: current manual, error-prone flow — rejected.
- Publish to GitHub Releases: adds a second delivery surface and tagging logic; git already tracks the file.
- Commit on every run regardless of change: creates empty/no-op commits and churn — rejected in favor of the diff guard.
- Make the archive byte-deterministic to avoid diffs: out of scope; the dataset changes every week by design.

**Consequences**: the reader sees a new weekly commit `chore(exports_canonical.zip): update from weekly run <date>`; branch protection must allow the bot to push; each new archive is a full-replacement binary diff (repo growth of ~24 MB/run).

## Decision 5: Playwright Chromium for SigPesq (unchanged)

**Decision**: Keep the existing `playwright install --with-deps chromium` step. SigPesq uses Playwright's own browser API (not Selenium/chromedriver) — no changes needed.

**Rationale**: `agent_sigpesq` calls Playwright's async API directly. Playwright manages its own browser instance completely separately from Selenium. The two tools share the system chromium only if `CHROME_BINARY` points to the same binary, but they use different driver protocols and do not conflict when run sequentially.
