# Feature Specification: Infisical-backed SigPesq Credentials

**Feature Branch**: `017-infisical-sigpesq-credentials`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "I need to use, only, the Infisical secrets `sigpesq-password` and `sigpesq-user` instead of the values from `SIGPESQ_USERNAME=` and `SIGPESQ_PASSWORD=` that are read from the `.env` in this repository."

## Clarifications

### Session 2026-10-13

- Q: Should the legacy `.env`-based credential variables `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` remain supported as a credential mode, or be removed entirely so Infisical is the only source of SigPesq credentials? → A: Keep both modes — Infisical primary, legacy env vars remain as an explicit alternative for offline/constrained environments (Option A).
- Q: Should the weekly GitHub Actions CI workflow (which currently injects `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` as GitHub secrets) also be migrated to Infisical, or keep using GitHub secrets? → A: Keep GitHub secrets in CI — CI is out of scope; the feature touches only local/Docker/manual pipeline runs (Option B).
- Q: How should the pipeline decide at runtime which credential mode to use — an explicit configuration flag, automatic detection of which settings are present, or precedence rules when both are configured? → A: Explicit mode flag — a single documented setting selects `infisical` or `legacy`; an absent or invalid flag aborts the run with a clear message (Option A).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pipeline runs SigPesq extraction with Infisical-held credentials (Priority: P1)

As a pipeline operator, I configure the weekly ETL run with our Infisical connection settings (host, machine identity, project, environment, and secret path) instead of putting the SigPesq username and password in `.env`, and the SigPesq download and login step works using the `sigpesq-user` and `sigpesq-password` secrets — because the repository no longer requires the SigPesq credentials to be stored as plaintext local environment variables.

**Why this priority**: This is the core of the feature. Moving the actual SigPesq credentials out of `.env` is the whole point, and it is what every other requirement builds on.

**Independent Test**: In an environment where `.env` contains Infisical connection settings but no `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`, run the SigPesq extraction end to end and confirm the SigPesq portal login succeeds and reports are downloaded.

**Acceptance Scenarios**:

1. **Given** `.env` contains valid Infisical connection settings and the secrets `sigpesq-user` and `sigpesq-password` exist in the configured project/environment/path, and no `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` variables, **When** the SigPesq extraction runs, **Then** the SigPesq portal login succeeds using the Infisical secret values and the download completes.
2. **Given** the Infisical secret values match the working SigPesq account, **When** the extraction step logs into the SigPesq portal, **Then** the credentials used are identical to the ones stored in Infisical (no transformation).
3. **Given** an environment that still uses the legacy local-credential mode, **When** the extraction runs, **Then** it keeps working exactly as before through the explicit legacy path.

---

### User Story 2 - Fail fast and clearly when credentials cannot be resolved (Priority: P1)

As a pipeline operator, when the Infisical-backed mode is selected but the secrets cannot be obtained (missing secret, empty value, unreachable host, or expired machine identity), I want the run to stop before any SigPesq portal access, with an error message that tells me exactly which configuration item is wrong — not a confusing login failure after the browser already started.

**Why this priority**: Silent or late failures hide misconfiguration and waste a full download cycle. Failing fast at the credential step is cheap to build and protects every downstream run.

**Independent Test**: Configure the Infisical-backed mode pointing at a project that lacks the `sigpesq-user` secret; run the extraction and observe a clear, immediate failure naming the missing secret, with no SigPesq portal login attempt.

**Acceptance Scenarios**:

1. **Given** the Infisical-backed mode is selected and the secret `sigpesq-user` (or `sigpesq-password`) does not exist or is empty in the configured location, **When** the extraction starts, **Then** the run aborts before contacting the SigPesq portal with an error that names the missing/empty secret.
2. **Given** the Infisical host is unreachable or the machine identity credentials are invalid, **When** the extraction starts, **Then** the run aborts with a clear authentication/connectivity error and does not attempt the SigPesq login with placeholder or stale values.
3. **Given** only one of the two secrets is resolvable, **When** the extraction starts, **Then** the run aborts — it never combines one Infisical secret with one legacy value.

---

### User Story 3 - No SigPesq credential leakage in logs or artifacts (Priority: P2)

As a security-conscious maintainer, I want to be confident that the SigPesq username and password never appear in plaintext in run logs, generated artifacts, or exported files, so that operational outputs stay safe even though the credentials are now resolved at runtime.

**Why this priority**: This is the security guarantee that makes moving the secret source worthwhile; without it the change adds risk instead of removing it.

**Independent Test**: Run the extraction in Infisical-backed mode with a debug/verbose log level, then scan every log line and generated artifact for the plaintext username and password values; nothing should match.

**Acceptance Scenarios**:

1. **Given** a successful extraction run in Infisical-backed mode, **When** all log output is inspected, **Then** the plaintext SigPesq username and password do not appear in any log line.
2. **Given** a failed run (e.g., missing secret), **When** the error output is inspected, **Then** it names the missing configuration but never prints the secret value that was attempted or obtained.
3. **Given** the generated export and report artifacts are inspected, **When** they are scanned for credential values, **Then** no SigPesq credential plaintext is present.

---

### User Story 4 - Single place to configure where credentials come from (Priority: P2)

As a maintainer, I want the credential source to be a deliberate, documented choice — Infisical-backed or legacy local variables — so that each environment (a developer laptop, a Docker deployment, a manual run) picks the mode that suits it without code changes, and so that onboarding a new environment is a one-place configuration task.

**Why this priority**: Different environments have different constraints (a developer laptop may not reach the Infisical instance; CI already feeds credentials as secrets). An explicit mode keeps both options working and testable.

**Independent Test**: Read the setup documentation for the feature and, without touching code, configure one environment in Infisical-backed mode and another in legacy mode; both run the SigPesq step successfully.

**Acceptance Scenarios**:

1. **Given** a fresh environment following the updated setup guide, **When** the operator chooses Infisical-backed mode and sets only the documented connection variables, **Then** the SigPesq step runs using the Infisical secrets without any code edit.
2. **Given** an environment where legacy mode is selected, **When** the operator sets only `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` in `.env`, **Then** the SigPesq step runs exactly as it did before this feature (backward compatible).
3. **Given** an environment that sets neither mode completely (e.g., partial Infisical connection settings and no legacy variables), **When** the extraction runs, **Then** it fails with a message describing the incomplete configuration.

---

### Edge Cases

- **Missing or empty secret**: abort before SigPesq portal access with the secret name in the message.
- **Absent or invalid mode flag**: abort before any credential resolution with a message explaining the two accepted values; no mode is assumed by default.
- **Unreachable Infisical host or invalid machine identity**: abort with a clear authentication/connectivity error; never retry against SigPesq with stale or empty values.
- **Single resolvable secret**: abort; do not mix one Infisical secret with one legacy value.
- **Legacy mode unchanged**: environments that keep using `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` behave byte-for-byte as they do today, including the existing `SIGPESQ_USER` alias.
- **Repeated runs**: secrets are resolved per run; a value updated in Infisical between runs is picked up on the next run without requiring a restart of anything outside the run.
- **Concurrent runs**: two runs resolving the same Infisical secrets do not interfere with each other.
- **Empty-string password in Infisical**: treated as missing and aborts with a clear message (credentials must never be empty).
- **Whitespace/value fidelity**: values are used exactly as stored (no trimming, no quoting) so padded values fail loudly rather than silently.
- **Debug/verbose logging**: even at maximum verbosity, plaintext credential values never hit the logs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST resolve the SigPesq username and password from the configured Infisical location (the `sigpesq-user` and `sigpesq-password` secrets) and use them for the SigPesq portal login when the Infisical-backed mode is selected.
- **FR-002**: The Infisical connection settings (host, machine identity credentials, project, environment, and secret path) MUST be configurable through the existing environment-variable configuration mechanism, with a documented default for each.
- **FR-003**: The credential mode MUST be selected by a single explicit, documented setting with exactly two valid values: `infisical` and `legacy`; when the setting is absent or holds any other value, the run MUST abort before any credential resolution with a clear, actionable message.
- **FR-004**: When the mode setting selects `infisical`, the SigPesq credentials MUST come exclusively from Infisical; the system MUST NOT fall back to, or mix in, values from `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`/`SIGPESQ_USER`.
- **FR-005**: Before any SigPesq portal access, the system MUST validate that both secrets resolved to non-empty values; a missing or empty secret MUST abort the run with an error naming the specific secret.
- **FR-006**: A failure to connect to or authenticate against Infisical MUST abort the run with a clear error before any SigPesq portal access; the run MUST NOT proceed with placeholder, cached, or partially resolved credentials.
- **FR-007**: The legacy local-credential mode (reading `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` from the environment, including the `SIGPESQ_USER` alias) MUST continue to work unchanged when explicitly selected, preserving existing behavior and validation.
- **FR-008**: A resolvable pair of credentials MUST be made available to the SigPesq login step in the same shape and under the same names the SigPesq download step expects, so the download code path itself does not change behavior.
- **FR-009**: Plaintext SigPesq credentials MUST NOT be written to any log line, error message, generated artifact, or exported file.
- **FR-010**: The chosen credential mode and its resolution result MUST be observable at a non-secret level (for example, which mode was used and how many secrets resolved) so runs can be diagnosed without revealing values.
- **FR-011**: Credentials MUST be resolved fresh on each run; a change in Infisical MUST take effect on the next run.
- **FR-012**: The setup documentation MUST describe how to choose the credential mode and what configuration each mode requires, so a new environment (local, Docker, or manual run) can be configured without code changes.

### Key Entities *(include if feature involves data)*

- **SigPesq credential pair**: the username and password that the SigPesq portal login requires; the sensitive values at the center of this feature.
- **Infisical secret location**: the project plus environment plus secret path where `sigpesq-user` and `sigpesq-password` live.
- **Credential mode**: the explicit selection between Infisical-backed resolution and the legacy local-environment variables.
- **Connection settings**: the non-secret-plus-machine-identity variables that let the pipeline reach the Infisical instance (host, identity id/secret, project id, environment, secret path).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In an environment configured only with Infisical connection settings and no `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` variables, the SigPesq extraction completes and downloads reports successfully (100% of the reports the same account can access).
- **SC-002**: With either `sigpesq-user` or `sigpesq-password` missing or empty in Infisical, the run aborts before any SigPesq portal access and the error message names the exact missing secret.
- **SC-003**: A full scan of run logs and generated artifacts finds zero occurrences of the plaintext SigPesq username and password values.
- **SC-004**: All existing behavior of the legacy local-credential mode is preserved: environments that set `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` (or the `SIGPESQ_USER` alias) continue to run the SigPesq step successfully with no code change; the operator adds the single `SIGPESQ_CREDENTIALS_SOURCE=legacy` selection once.
- **SC-005**: A new environment (local, Docker, or manual run) can be configured to the Infisical-backed mode by following the updated setup documentation alone, with no code changes, in a single configuration step.
- **SC-006**: The GitHub Actions weekly workflow keeps working unchanged with its existing GitHub secrets; this feature introduces no CI behavior change.

## Assumptions

- The Infisical instance, machine identity (Universal Auth), and the `sigpesq-user`/`sigpesq-password` secrets under project `/ environment / path` already exist and the identity has read access to them — the feature consumes them, it does not provision them.
- The connection settings may remain in `.env`/process environment; only the SigPesq credentials move out of them. Machine-identity client id/secret are access credentials to the secrets manager itself and are handled by the existing environment-variable mechanism.
- The SigPesq download step will keep receiving the credentials through the same environment variables it reads today (`SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`, with `SIGPESQ_USER` alias support) because the external SigPesq download component is not being modified; the feature changes where those values come from, not how they are consumed.
- Remote Infisical access may be restricted in some deployment contexts (e.g., some CI runners or offline developer machines); those environments use legacy mode, which remains fully functional.
- The GitHub Actions weekly workflow is explicitly out of scope: it keeps injecting `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` from the GitHub secret store and is not migrated to Infisical.
- The credential mode is selected by an explicit mode-flag setting (no auto-detection, no implicit default); when it is absent or invalid, the run aborts (FR-003).
- Secrets are resolved at the start of each run; no long-lived persistence of the resolved credentials is required beyond the run itself.
- Default values for connection settings should match the values used in the project's existing test setup (host, `dev` environment, `/` secret path) unless an environment overrides them.

## Dependencies

- Requires read access to the Infisical instance from wherever the pipeline runs, using the credentials the operator configures.
- Requires the existing SigPesq download component (which consumes SigPesq credentials from environment variables) to remain available and unchanged.
- Depends on the configuration mechanism already used by the repository (environment variables loaded from `.env`) to carry the connection settings and the mode selection.