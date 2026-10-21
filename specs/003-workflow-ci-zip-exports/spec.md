# Feature Specification: Weekly CI Workflow Validation and Export Compression

**Feature Branch**: `feat/003-workflow-ci-zip-exports`

**Created**: 2026-05-16

**Status**: Draft — amended 2026-10-14 for versioned archive publishing

## Clarifications

### Session 2026-05-16

- Q: How should Chrome for Lattes/Selenium be provided in CI? → A: Reuse Playwright-managed Chromium + bundled chromedriver (no separate Chrome install).
- Q: Artifact retention period? → A: 30 days (covers ~4 weekly runs, reduces storage).

### Session 2026-10-14

- Q: How should `exports_canonical.zip` be delivered? → A: The workflow commits it back to the repository, updating the tracked `data/exports/exports_canonical.zip`, when (and only when) it changed. It is no longer published as a downloadable CI artifact.
- Q: May the pre-upload compression step rewrite the archive? → A: No. The archive MUST be committed byte-for-byte exactly as `make weekly-flows` wrote it, so the compression step skips every `*.zip` file.
- Q: When should the commit happen? → A: Only when the weekly flows completed successfully, so an incomplete archive from a failed run is never committed.

## User Scenarios & Testing

### User Story 1 — Reliable Weekly Pipeline Execution in CI (Priority: P1)

As a maintainer, I want the weekly ETL pipeline to run correctly on GitHub Actions every Saturday so that data is always refreshed without manual intervention.

**Why this priority**: The entire data refresh cycle depends on CI running correctly. If the workflow fails silently or misconfigures permissions, data becomes stale and the team has no visibility.

**Independent Test**: Trigger `workflow_dispatch` manually on the `weekly-etl` workflow; verify it completes with `success` state and all expected artifacts are uploaded.

**Acceptance Scenarios**:

1. **Given** all required secrets are configured, **When** the scheduled workflow runs on Saturday, **Then** all pipeline steps complete successfully and artifacts are uploaded within 300 minutes.
2. **Given** a required secret is missing, **When** the workflow runs, **Then** the validation step fails immediately with a descriptive error naming the missing secret, and no pipeline steps execute.
3. **Given** the pipeline step fails, **When** the failure occurs, **Then** artifacts collected up to that point are uploaded and Prefect logs are shown in the workflow summary.

**Edge Cases**:
- Workflow triggered while a previous run is still in progress → second run waits (cancel-in-progress: false prevents data corruption).
- Prefect server fails to start → pipeline step fails with clear error; Prefect logs shown via `docker compose logs`.

---

### User Story 2 — Automatic Compression of Large Export Files (Priority: P2)

As a maintainer, I want export files exceeding 10 MB to be automatically compressed before being uploaded as CI artifacts so that artifact storage is not wasted and downloads are faster.

**Why this priority**: The `data/exports/` directory currently totals 16 MB. Without compression, each weekly run accumulates large uncompressed artifacts in GitHub Actions storage.

**Independent Test**: After a successful pipeline run, verify that no individual uncompressed file exceeding 10 MB appears in the uploaded artifact; files above the threshold must be present as `.zip` archives.

**Acceptance Scenarios**:

1. **Given** export files exist after the pipeline, **When** the artifact upload step runs, **Then** any file larger than 10 MB is replaced by a `.zip` archive of the same name.
2. **Given** all export files are under 10 MB, **When** the artifact upload step runs, **Then** files are uploaded without modification.
3. **Given** the compression step completes, **When** artifacts are downloaded, **Then** the `.zip` archives can be extracted to recover the original files.
4. **Given** an existing archive (`exports_canonical.zip`) larger than 10 MB, **When** the compression step runs, **Then** the archive is left untouched (no `.zip.zip` wrapper is created).

**Edge Cases**:
- Export directory is empty (pipeline failed mid-run) → compression step runs, finds no files, uploads nothing; `if-no-files-found: ignore` prevents failure.
- Single file is exactly 10 MB → not compressed (threshold is strictly greater than 10 MB).
- The curated archive `exports_canonical.zip` is itself larger than 10 MB → excluded from compression by name so the flow's exact output survives.

---

### User Story 4 — Versioned Archive Publishing (Priority: P2)

As a downstream consumer, I want each weekly run to publish the curated `exports_canonical.zip` back into the repository (replacing the previous copy) so I can always fetch the latest dataset from git, without downloading a CI artifact by hand.

**Why this priority**: `exports_canonical.zip` is the single curated dataset deliverable. Determining "latest" from a 30-day artifact list and committing it manually is error-prone; the workflow already produces the archive, so publishing it is a small, high-value addition.

**Independent Test**: Trigger `workflow_dispatch`; verify the run creates a commit updating `data/exports/exports_canonical.zip` when the archive changed, creates no commit when it did not, and that the archive is absent from the downloadable artifacts.

**Acceptance Scenarios**:

1. **Given** the weekly flows produced an archive that differs from the committed one, **When** the workflow reaches the publish step, **Then** a commit updates `data/exports/exports_canonical.zip` (and nothing else).
2. **Given** the newly generated archive is byte-identical to the committed one, **When** the publish step runs, **Then** no commit is created.
3. **Given** the run failed before producing a complete archive, **When** the workflow ends, **Then** no commit is attempted (partial archives are never published).
4. **Given** the run completes, **When** the uploaded artifacts are inspected, **Then** `exports_canonical.zip` is not among them — git is its delivery channel.

**Edge Cases**:
- Archive produced but unchanged → publish step is a no-op (no empty commit).
- Archive absent (flows failed) → publish step logs a warning and exits without committing.
- Repository branch is protected → the push is rejected; the run surfaces it (documented precondition).

---

### User Story 3 — Lattes Flow Compatibility in CI (Priority: P3)

As a maintainer, I want the Lattes ingestion step to run correctly in the GitHub Actions runner environment so that researcher curriculum data is refreshed as part of the weekly pipeline.

**Why this priority**: Lattes uses a browser automation tool that requires a compatible Chrome binary and driver. Without explicit setup, the step silently fails or aborts.

**Independent Test**: Run `make ingest-lattes-download` on a clean ubuntu-latest environment with the same secret configuration; verify it completes without a `ChromeDriverRuntimeError`.

**Acceptance Scenarios**:

1. **Given** the CI runner environment, **When** the Lattes download step runs, **Then** it locates a compatible Chrome binary and proceeds with curriculum download.
2. **Given** the Chrome version and driver version are incompatible, **When** the Lattes step runs, **Then** it fails with a descriptive error identifying the version mismatch.

**Edge Cases**:
- Chrome installed by Playwright (for SigPesq) is a different version than the system chromedriver → version mismatch error must be clear.
- `CHROME_BINARY` env var not set → fallback to system Chrome detection.

---

### Edge Cases

- What happens when the artifact upload permission is denied? → Workflow step fails with permission error; fix: `permissions: actions: write` must be present.
- How does the workflow handle partial pipeline success? → `if: always()` on artifact upload ensures partial results are preserved even if pipeline fails; the archive publish step, by contrast, runs only on success and never commits a partial archive.
- What happens when the archive push is rejected (protected branch / stale token)? → The publish step fails and the run surfaces it; the previously committed archive stays valid until the next run.

## Requirements

### Functional Requirements

- **FR-001** [P1]: The workflow MUST declare `actions: write` (so artifact uploads succeed under fine-grained token policies) and `contents: write` (so the workflow can commit and push the export archive).
- **FR-002** [P1]: The workflow MUST validate all required secrets before executing any pipeline step and fail with a named error for each missing secret.
- **FR-003** [P2]: A pre-upload step MUST compress any export file larger than 10 MB into a `.zip` archive in-place before the artifact upload action runs. It MUST NOT modify any existing `.zip` file, so archives delivered by the pipeline (notably `exports_canonical.zip`) are preserved byte-for-byte.
- **FR-004** [P2]: The compression step MUST run even if the pipeline step failed (`if: always()`) so partial exports are still uploaded.
- **FR-005** [P3]: The workflow MUST set `CHROME_BINARY` and `CHROMEDRIVER_PATH` environment variables to the Playwright-managed Chromium binary and its bundled chromedriver (already installed by the `playwright install --with-deps chromium` step), so the Lattes flow can reuse the same browser without a separate installation.
- **FR-006** [P1]: The `Stop Prefect server` step MUST always run (`if: always()`) to prevent orphaned Docker containers on the runner.
- **FR-007** [P1]: The workflow MUST use the Playwright-installed Chromium for SigPesq (already covered by `playwright install --with-deps chromium` step).
- **FR-008** [P2]: CI artifacts MUST be retained for exactly 30 days to balance run history availability against storage consumption.
- **FR-009** [P2]: When the weekly flows complete successfully and the generated `data/exports/exports_canonical.zip` differs from the committed one, the workflow MUST commit that file back to the repository and push it, updating the tracked archive. When the archive is unchanged, or was not produced, no commit MUST be created.
- **FR-010** [P2]: The publishing commit MUST be authored as `github-actions[bot]` and MUST touch only `data/exports/exports_canonical.zip` (no other `data/` output is committed).
- **FR-011** [P2]: `exports_canonical.zip` MUST NOT be published as a downloadable CI artifact; its delivery channel is the repository (see FR-009). The remaining `data/` tree and `db/horizon.db` continue to be uploaded as the 30-day artifact.

### Key Entities

- **CI Artifact**: Uploaded output of a workflow run; contains the `data/` tree and `db/horizon.db`, but **excludes** `exports_canonical.zip`; retained for 30 days.
- **Export File**: JSON file produced by a pipeline export flow in `data/exports/`.
- **Compressed Export**: A `.zip` archive replacing an export file exceeding the 10 MB threshold. Existing `*.zip` files are never re-compressed.
- **Versioned Export Archive**: `data/exports/exports_canonical.zip`, the single curated dataset deliverable; produced once per weekly run by `zip_exports_task` and committed to the repository by the workflow when it changes. It is the byte-for-byte output of `make weekly-flows` (no nested/re-zipped wrapper).

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of manual `workflow_dispatch` triggers complete without permission-related failures after the fix.
- **SC-002**: Artifact upload size is reduced by at least 30% compared to uncompressed upload when exports exceed 10 MB.
- **SC-003**: The `Validate required secrets` step catches 100% of missing-secret scenarios within the first 30 seconds of the run.
- **SC-004**: Zero orphaned Docker containers remain on the runner after a workflow run (success or failure).
- **SC-005**: The Lattes flow completes without a `ChromeDriverRuntimeError` on at least 95% of CI runs when the portal is reachable.
- **SC-006**: The archive committed by the workflow is byte-for-byte the file produced by the run's `make weekly-flows` (no nested or re-compressed wrapper); a `.zip` member named `exports_canonical.zip` inside the committed archive is a regression.
- **SC-007**: A weekly run with an unchanged archive produces zero commits; a run with a changed archive produces exactly one commit that modifies only `data/exports/exports_canonical.zip`.

## Assumptions

- GitHub Actions runner is `ubuntu-latest` with Docker available (confirmed: all ubuntu-latest runners include Docker Engine).
- Playwright's bundled Chromium (installed via `playwright install --with-deps chromium`) is used for SigPesq (Playwright-based).
- Lattes uses Selenium/chromedriver; `CHROME_BINARY` and `CHROMEDRIVER_PATH` point to the Playwright-managed Chromium and its bundled chromedriver — no separate Chrome installation required.
- The 10 MB compression threshold applies per-file, not to the total artifact size, and never applies to files that are already `.zip`.
- `.zip` compression is sufficient; no encryption or password protection required.
- Secrets `DATABASE_URL`, `STORAGE_TYPE`, `SIGPESQ_USERNAME`, `SIGPESQ_PASSWORD`, `HORIZON_TELEGRAM_BOT_TOKEN`, `HORIZON_TELEGRAM_CHAT_ID` are pre-configured in the repository.
- The `docker compose down -v` in the final step intentionally removes Prefect volumes (ephemeral in CI — SQLite data is in workspace, not in Docker volumes).
- The workflow runs on a branch where the default `GITHUB_TOKEN` may push (`contents: write`); the branch is not protected against the bot in a way that rejects the commit, or that protection is configured to allow it.
- `data/exports/exports_canonical.zip` is already tracked in the repository, so the publish step modifies a versioned file rather than creating a new one.
- The archive is produced by `zip_exports_task` inside `make weekly-flows`; the workflow changes only its delivery (commit vs. artifact), not its contents or generation.

## Out of Scope

- Changing the pipeline schedule or runtime duration targets.
- Caching Docker images between runs.
- Storing artifacts to external storage (S3, GCS) — GitHub Actions artifact storage only; the versioned archive is delivered through git.
- Committing any other `data/` output (canonical JSON, marts, graphs, raw corpora, `db/horizon.db`) — only `data/exports/exports_canonical.zip` is published.
- Making the archive reproducible/byte-deterministic across runs; each weekly run is expected to produce a new archive.
- Multi-campus parallel execution in CI.
- The Chromium/Chromedriver setup for the (since-migrated) Lattes Selenium flow — see the review note in this spec set; the current flow uses Playwright.
