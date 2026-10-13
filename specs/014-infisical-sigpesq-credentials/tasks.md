# Tasks: Infisical-backed SigPesq Credentials

**Input**: Design documents from `/specs/014-infisical-sigpesq-credentials/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/credential_source_config.md, quickstart.md

**Tests**: Included — the plan's Definition of Done and `contracts/credential_source_config.md` mandate test-pinned rules C1–C4; each story ships its tests as part of its independent test criteria.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Single project layout: `src/`, `tests/`, `docs/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the new dependency and record the pre-feature baseline

- [X] T001 Add `infisicalsdk==1.0.17` to `requirements.txt` and `infisicalsdk>=1.0.17` to `pyproject.toml` dependencies, then install with `.venv/bin/pip install "infisicalsdk==1.0.17"` (R1)
- [X] T002 Record the pre-feature test baseline per quickstart.md §0/§2: run `.venv/bin/python -m pytest -q`, note the result and the known pre-existing failures (specs/009 baseline) as the reference for T026

**Checkpoint**: Dependency available and baseline recorded — story work can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The port contract every resolution path depends on (Constitution I)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Create `src/core/ports/secret_provider.py` with the `ISecretProvider` ABC (`get_secret(secret_name: str) -> str`) and `CredentialResolutionError` (carries a safe, value-free message), per Constitution I and data-model.md Entity 2/3

**Checkpoint**: Port contract exists — user story implementation can now begin.

---

## Phase 3: User Story 1 - Pipeline runs SigPesq extraction with Infisical-held credentials (Priority: P1) 🎯 MVP

**Goal**: In `infisical` mode the adapter resolves `sigpesq-user`/`sigpesq-password` from the configured Infisical location and hands the pair to the unchanged `agent_sigpesq` download step via the env vars it already reads.

**Independent Test**: With `.env` holding Infisical connection settings and `SIGPESQ_CREDENTIALS_SOURCE=infisical` (and no `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`), run `SigPesqAdapter()._validate_environment()` (or the full `extract()` with a faked download) and confirm the pair resolves, `SIGPESQ_USER`/`SIGPESQ_PASSWORD` are exported, and no portal-credential env vars were read from the operator (quickstart.md §3).

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T004 [P] [US1] Create `tests/test_infisical_secret_provider.py` with nominal-resolution tests for `InfisicalSecretProvider` using a mocked `infisical_sdk` module (login called once, one `get_secret_by_name` per secret, value returned exactly as stored, `cache_ttl=None`): pin C2-01, C2-05, C2-06
- [X] T005 [P] [US1] Create `tests/test_sigpesq_credentials_mode.py` with a fake `ISecretProvider` and a resolution/handoff test asserting `resolve_infisical_credentials()` exports `SIGPESQ_USERNAME`, `SIGPESQ_USER` (alias), and `SIGPESQ_PASSWORD`: pin C3-01

### Implementation for User Story 1

- [X] T006 [P] [US1] Create `src/adapters/secrets/__init__.py` and `src/adapters/secrets/infisical.py` implementing `InfisicalSecretProvider(ISecretProvider)`: env config with documented defaults (`INFISICAL_HOST`/`INFISICAL_ENV`/`INFISICAL_SECRET_PATH`), lazy `infisical_sdk` import, `InfisicalSDKClient(host=..., cache_ttl=None)` context manager, `auth.universal_auth.login(...)`, `secrets.get_secret_by_name(...)` per secret, returning `secret.secretValue` (R1, R2, C2-01, C2-05, C2-06)
- [X] T007 [P] [US1] Create `src/adapters/sources/sigpesq/credentials.py` with `parse_credential_source()` (returns `infisical`/`legacy`; absent/invalid raises the final message naming the variable and both accepted values), the `SIGPESQ_USER_SECRET = "sigpesq-user"` / `SIGPESQ_PASSWORD_SECRET = "sigpesq-password"` constants, and `resolve_infisical_credentials(provider)` that fetches both and exports `SIGPESQ_USERNAME`/`SIGPESQ_USER`/`SIGPESQ_PASSWORD` to `os.environ` (R5, R6, C1-01, C1-02, C1-03, C3-01)
- [X] T008 [US1] Add mode dispatch to `SigPesqAdapter._validate_environment` in `src/adapters/sources/sigpesq/adapter.py`: parse the mode; on `infisical` call the resolver (default `InfisicalSecretProvider`) and log the mode + resolved count (no values); on `legacy` keep the existing validation path unchanged (R4, C1-04, C3-04)
- [X] T009 [US1] Extend `tests/test_sigpesq_adapter.py`: an `infisical`-mode `extract()` test with an injected fake provider asserting `SIGPESQ_USER`/`SIGPESQ_PASSWORD` are exported and the download path is called, plus a `legacy` alias-preservation check: pin C1-04, C3-01, C3-04
- [X] T010 [US1] Run the US1 tests (`tests/test_infisical_secret_provider.py`, `tests/test_sigpesq_credentials_mode.py`, `tests/test_sigpesq_adapter.py`) and the quickstart.md §3 Infisical-mode validation smoke; all must pass

**Checkpoint**: Infisical-mode resolution and hand-off work end to end (US1 = MVP).

---

## Phase 4: User Story 2 - Fail fast and clearly when credentials cannot be resolved (Priority: P1)

**Goal**: Any Infisical misconfiguration (missing/empty secret, unreachable host, invalid identity, single resolvable secret) aborts before any SigPesq portal access with a message naming the exact configuration item, and never mixes sources.

**Independent Test**: Point `INFISICAL_SECRET_PATH` at an empty folder (or use a fake provider that omits `sigpesq-user`), call `extract()`, and confirm it raises before `_trigger_download` with a message naming `sigpesq-user`; repeat for auth/connectivity errors and for a single-secret case (quickstart.md §3 failure cases).

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T011 [US2] Extend `tests/test_infisical_secret_provider.py`: missing required connection var aborts naming it before any network call (C2-02); missing/empty secret aborts naming the exact secret (C2-03); auth failure (401) and connectivity failure map to distinct, actionable messages (C2-04)
- [X] T012 [US2] Extend `tests/test_sigpesq_credentials_mode.py`: no-mixing (legacy vars present alongside `infisical` mode are ignored), single-resolvable-secret aborts, and abort-before-portal (patch/assert `_trigger_download` is never reached): pin C2-03, C3-02, C3-03

### Implementation for User Story 2

- [X] T013 [US2] Harden `InfisicalSecretProvider` in `src/adapters/secrets/infisical.py`: validate required `INFISICAL_*` settings and raise `CredentialResolutionError` naming the missing variable before any network call; map SDK `APIError`/`InfisicalError` to distinct auth (401), permission (403), not-found (404), and connectivity messages (R3, C2-02, C2-04)
- [X] T014 [US2] Harden `resolve_infisical_credentials()` and `_validate_environment` in `src/adapters/sources/sigpesq/credentials.py` / `src/adapters/sources/sigpesq/adapter.py`: distinct missing-vs-empty messages naming the secret, enforce both-non-empty, never read legacy vars in `infisical` mode, and guarantee the abort happens before `_trigger_download` (C2-03, C3-02, C3-03)
- [X] T015 [US2] Run the US2 tests and the quickstart.md §3 failure smokes (empty secret path, invalid identity); all must pass

**Checkpoint**: All failure modes abort clearly before portal access (US1 + US2 independently green).

---

## Phase 5: User Story 3 - No SigPesq credential leakage in logs or artifacts (Priority: P2)

**Goal**: The resolved username and password never appear in plaintext in logs, error messages, artifacts, or exports — even at debug/verbose level.

**Independent Test**: Run the resolution path (success and each failure) while capturing loguru output and exception text, then assert no plaintext credential value appears anywhere (quickstart.md §4 scan).

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T016 [US3] Extend `tests/test_sigpesq_credentials_mode.py` and `tests/test_infisical_secret_provider.py`: capture loguru output (success and each documented failure path) and assert no plaintext username/password appears; assert raised `CredentialResolutionError` messages never embed a value (C4-01, C4-02)

### Implementation for User Story 3

- [X] T017 [US3] Audit and harden masking in `src/adapters/secrets/infisical.py` and `src/adapters/sources/sigpesq/credentials.py`: never log secret values (mask if any diagnostic value is needed), keep all `CredentialResolutionError` messages value-free, and confirm `SigPesqAdapter._validate_environment` logs only mode + resolved count (R6, C4-01, C4-02, C4-03)
- [X] T018 [US3] Run the US3 tests plus the quickstart.md §4 no-leak scan of the run log **and an explicit scan of generated artifacts/exports** for the resolved username/password; zero plaintext matches required in logs, artifacts, and exports (C4-03, SC-003)

**Checkpoint**: No plaintext credentials anywhere in output (US3 independently verifiable).

---

## Phase 6: User Story 4 - Single place to configure where credentials come from (Priority: P2)

**Goal**: The credential source is a deliberate, documented, one-place configuration choice; every environment (laptop, Docker, manual run) picks a mode without code changes, and CI keeps GitHub secrets.

**Independent Test**: Read the updated setup docs and, without touching code, configure one environment in `infisical` mode and another in `legacy` mode; both run the SigPesq step. Confirm absent/invalid mode aborts, and CI gains only the `legacy` line (quickstart.md §3; SC-005, SC-006).

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T019 [US4] Extend `tests/test_sigpesq_credentials_mode.py`: mode flag absent aborts naming the variable + both accepted values (C1-02); invalid value aborts the same way (C1-03); no auto-detection of partial config (C1-05)

### Implementation for User Story 4

- [X] T020 [P] [US4] Update `.env.example`: add `SIGPESQ_CREDENTIALS_SOURCE` (documented values + the mandatory one-time `legacy` addition) and the `INFISICAL_HOST`/`INFISICAL_CLIENT_ID`/`INFISICAL_CLIENT_SECRET`/`INFISICAL_PROJECT_ID`/`INFISICAL_ENV`/`INFISICAL_SECRET_PATH` block with defaults; keep the legacy `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` entries marked as legacy-mode (FR-002, FR-012)
- [X] T021 [P] [US4] Update the `## Configuracao` section of `README.md` to document the mode flag, the Infisical settings with defaults, the `SIGPESQ_USER` alias note, and the one-time legacy migration line (FR-012)
- [X] T022 [P] [US4] Update `docs/operations/automation.md` (mode flag; CI keeps GitHub secrets, one-line `legacy` addition) and `docs/operations/troubleshooting.md` (new entries: absent/invalid mode, missing/empty Infisical secret, unreachable host/invalid identity) (FR-012)
- [X] T023 [US4] Add exactly one env line `SIGPESQ_CREDENTIALS_SOURCE: legacy` to `.github/workflows/weekly-etl.yml` under the `run-etl` job `env:`; leave the GitHub secrets list and the `Validate required secrets` step untouched (D-CI, SC-006)
- [X] T024 [US4] Run the US4 tests and the quickstart.md §3 both-modes configuration walkthrough (legacy and infisical, including the absent/invalid-mode failure); all must pass

**Checkpoint**: All four stories independently functional; configuration documented in one place.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Traceability and whole-feature gate

- [X] T025 [P] Verify contract traceability: every rule C1-01…C4-03 in `specs/014-infisical-sigpesq-credentials/contracts/credential_source_config.md` maps to a passing test
- [X] T026 Run the full gate `make ci-check` (flake8 + black + isort + mypy + pytest) and compare against the T002 baseline; known pre-existing failures (specs/009) are out of scope
- [X] T027 Run the quickstart.md end-to-end validation checklist (§0–§5) and confirm the Definition of Done items in plan.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: depends on Setup — BLOCKS all user stories (the port is the seam US1–US3 implement)
- **US1 (Phase 3)**: after Foundational — MVP, no story dependencies
- **US2 (Phase 4)**: after US1 — hardens the same provider/resolver/adapter files US1 creates (sequential, same-file)
- **US3 (Phase 5)**: after US2 — audits/masks the same provider/credentials files (sequential, same-file)
- **US4 (Phase 6)**: after Foundational for its test task (T019 uses the mode parser), but its docs/CI tasks are independent; runs after US1–US3 in practice to keep the test file edits sequential
- **Polish (Phase 7)**: after all desired stories

### User Story Dependencies

- **US1 (P1)**: no story dependencies — MVP on its own
- **US2 (P1)**: builds on US1's files (provider/resolver/adapter) — same-file ordering US1 → US2
- **US3 (P2)**: audits US1/US2 output — same-file ordering US2 → US3
- **US4 (P2)**: docs/CI are independent of US1–US3 code; only shares `tests/test_sigpesq_credentials_mode.py` (created in US1), so its test task runs after US3's edits to that file

### Within Each User Story

- Test tasks are written and confirmed FAILING before their implementation tasks
- Provider/resolver/adapter implementation precedes the story's integration tests
- Each story's verification task closes the phase and must pass before the next story's same-file edits

### Parallel Opportunities

- T004 and T005 create different new test files — parallel
- T006 (`src/adapters/secrets/infisical.py`) and T007 (`src/adapters/sources/sigpesq/credentials.py`) are different files — parallel
- T020, T021, T022 edit different documentation files — parallel
- T025 (traceability) can run alongside T020–T022
- No parallel file sharing across stories: `infisical.py`, `credentials.py`, `adapter.py`, and the two new test files are edited sequentially in the order US1 → US2 → US3

---

## Parallel Example: User Story 1

```bash
# Launch the two new test files together:
Task: "Create tests/test_infisical_secret_provider.py with nominal resolution tests (C2-01/05/06)"
Task: "Create tests/test_sigpesq_credentials_mode.py with resolution/handoff tests (C3-01)"

# Then create the two source files together:
Task: "Create src/adapters/secrets/infisical.py (InfisicalSecretProvider)"
Task: "Create src/adapters/sources/sigpesq/credentials.py (parse + resolve + handoff)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (dependency + baseline) and Phase 2 (port)
2. Complete Phase 3 (US1: Infisical resolution + handoff)
3. **STOP and VALIDATE**: quickstart.md §3 Infisical-mode smoke — the pair resolves and reaches `agent_sigpesq` unchanged
4. This alone closes the original gap (credentials no longer come from plaintext `.env`)

### Incremental Delivery

1. US1 → MVP (Infisical credentials resolve and hand off)
2. US2 → every misconfiguration fails fast and clearly before portal access
3. US3 → no credential leakage in logs/artifacts
4. US4 → the mode is a documented, one-place configuration choice; CI stays on GitHub secrets
5. Polish → traceability + full gate

Each story adds value without breaking the previous ones; every checkpoint is independently testable.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to a specific user story for traceability (US1–US4 per spec.md)
- Rules C1–C4 in `contracts/credential_source_config.md` are the single source of truth; each implementation task cites its rules
- Verify tests fail before implementing (TDD within each story)
- The five same-file surfaces (`src/adapters/secrets/infisical.py`, `src/adapters/sources/sigpesq/credentials.py`, `src/adapters/sources/sigpesq/adapter.py`, `tests/test_infisical_secret_provider.py`, `tests/test_sigpesq_credentials_mode.py`) are edited strictly sequentially US1 → US2 → US3 → US4
- Commit after each checkpoint
