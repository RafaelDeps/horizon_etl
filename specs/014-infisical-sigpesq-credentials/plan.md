# Implementation Plan: Infisical-backed SigPesq Credentials

**Branch**: `017-infisical-sigpesq-credentials` | **Date**: 2026-10-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/014-infisical-sigpesq-credentials/spec.md`

## Summary

Give the SigPesq extraction an explicit credential-mode setting
(`SIGPESQ_CREDENTIALS_SOURCE`) with exactly two values: `infisical` and
`legacy`. In `infisical` mode the SigPesq adapter resolves the login pair
(`sigpesq-user` / `sigpesq-password`) from the configured Infisical project /
environment / secret path through a new `ISecretProvider` port + Infisical
adapter, and hands them to the unchanged `agent_sigpesq` download step via the
same env vars it already reads. In `legacy` mode nothing changes. An absent or
invalid setting aborts before any credential resolution with a clear message.

## Technical Context

**Language/Version**: Python 3.12 (CI runner), 3.14 (local venv),
`requires-python >=3.10` (pyproject).

**Primary Dependencies**: one new dependency — `infisicalsdk==1.0.17` (PyPI
`infisicalsdk`; import name `infisical_sdk`; the same version validated in the
user's `infisical_test` proof of concept). Everything else untouched: pinned
`agent_sigpesq[extract]` (still reads `SIGPESQ_USER`/`SIGPESQ_PASSWORD` at
service init), `python-dotenv`, `loguru` for logging, `pytest` for tests.

**Storage**: none — no DB schema or file-artifact changes. Credentials are
resolved in-memory per run and exported to the process environment only.

**Testing**: pytest, offline and DB-less. The Infisical adapter is unit-tested
with a mocked `infisical_sdk` client (lazy import, like `agent_sigpesq`);
mode-selection and no-mixing behavior are tested with a fake `ISecretProvider`
injected into `SigPesqAdapter`, so no live Infisical is ever required in CI.

**Target Platform**: Linux — local laptop, Docker deployment, and manual runs
(CI is out of scope and stays on GitHub secrets).

**Project Type**: ETL pipeline; this feature touches one source adapter plus a
new secret-provider port/adapter.

**Performance Goals**: credential resolution adds a single authenticated
Infisical fetch per run (one `get_secret_by_name` per secret, one login via
Universal Auth), with the SDK cache disabled (`cache_ttl=None`) so values are
always fresh (FR-011); the added latency is sub-second network time at the
start of the run, before any browser/SigPesq interaction.

**Constraints**: the mode setting is mandatory (steady-state); no fallback or
mixing with `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`/`SIGPESQ_USER` in `infisical`
mode (FR-004); all resolution errors abort before any SigPesq portal access;
no plaintext credential may reach logs, error messages, artifacts, or exports
(FR-009); the `agent_sigpesq` download code path is not modified (FR-008); CI
keeps GitHub-secret sourcing.

**Scale/Scope**: one environment setting, one new `ISecretProvider` port, one
Infisical adapter, one resolver helper, `_validate_environment` mode dispatch
in the SigPesq adapter, one dependency line, `.env.example` + 3 docs updated,
CI gains one env line (see Decision D-CI), 2 new test files + mode tests in
the existing adapter test file.

## Constitution Check

*GATE — passed for Phase 0 (research) and re-checked after Phase 1 design.*

- **I. Ports & Adapters (non-negotiable)**: the Infisical interaction is
  mediated through a new port contract `ISecretProvider` in
  `src/core/ports/`; the concrete Infisical SDK adapter lives in
  `src/adapters/`; `src/core/logic/` imports nothing new from `src/adapters/`;
  flows are untouched (the adapter stays flow-agnostic and does its own
  env/credential orchestration inside `_validate_environment`, which it already
  owns today). **PASS**
- **II. Domain-First Data Modeling**: no new domain entities; no canonicals or
  mart changes. The credential pair is an ETL-transient operational value, not
  a domain concept. **PASS**
- **III. Prefect Flow Orchestration (non-negotiable)**: all credential
  resolution runs inside the existing `SigPesqAdapter.extract()` step of the
  existing SigPesq ingestion flows; no standalone ingestion/export path is
  added; no flow files change. **PASS**
- **IV. Audit-Driven Data Quality**: `infisical` mode logs which mode was used
  and how many secrets resolved, without values (FR-010), keeping runs
  diagnosable; the existing SigPesq 429/retry observability is untouched.
  **PASS**
- **V. LGPD Compliance by Default**: strengthened — the whole point is to stop
  carrying SigPesq credentials in plaintext `.env` values; FR-009 adds an
  explicit no-plaintext-credentials-in-logs/artifacts guarantee, which is
  reviewed and enforced by tests. **PASS**
- **Data Integrity & Clean-State Ingestion**: no changes to raw directories,
  clean-state clearing, DB, or export lifecycle. **PASS**
- **Development Workflow & Quality Gates**: new/updated pytest tests for mode
  selection, fail-fast, no-mixing, and no-leak; `make ci-check` remains the
  gate; existing `tests/test_sigpesq_adapter.py` extract tests already patch
  `_validate_environment`, so the mandatory flag does not disturb them. **PASS**

## Project Structure

### Documentation (this feature)

```text
specs/014-infisical-sigpesq-credentials/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output — credential-source config contract
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
├── core/
│   └── ports/
│       └── secret_provider.py              # NEW: ISecretProvider port contract
├── adapters/
│   ├── secrets/                            # NEW: credentials adapters
│   │   ├── __init__.py
│   │   └── infisical.py                    # NEW: InfisicalSecretProvider (ISecretProvider)
│   └── sources/
│       └── sigpesq/
│           ├── adapter.py                  # MODIFIED: mode dispatch in _validate_environment
│           └── credentials.py              # NEW: mode parsing + resolution helper (fail-fast, no-leak)
tests/
├── test_infisical_secret_provider.py       # NEW: mocked-SDK unit tests for the adapter
├── test_sigpesq_credentials_mode.py        # NEW: mode flag, fail-fast, no-mixing, no-leak
└── test_sigpesq_adapter.py                 # MODIFIED: infisical-mode env handoff tests
.env.example                                # MODIFIED: SIGPESQ_CREDENTIALS_SOURCE + INFISICAL_* docs
requirements.txt                            # MODIFIED: infisicalsdk==1.0.17
pyproject.toml                              # MODIFIED: infisicalsdk>=1.0.17 in dependencies
README.md                                   # MODIFIED: Configuracao section (FR-012)
docs/operations/automation.md               # MODIFIED: note mode flag + CI keeps GitHub secrets
docs/operations/troubleshooting.md          # MODIFIED: new Infisical-mode failure entries
.github/workflows/weekly-etl.yml            # MODIFIED: +SIGPESQ_CREDENTIALS_SOURCE: legacy (D-CI)
```

**Structure Decision**: single existing project; the change follows the
established Ports & Adapters split (`src/core/ports/` contracts,
`src/adapters/` implementations) and the existing per-source adapter folder
naming. A new `src/adapters/secrets/` folder holds the Infisical adapter so it
is not pinned to the SigPesq source and can serve future consumers through the
same port.

## Design

### D1 — Credential-mode setting (FR-003)

New environment variable `SIGPESQ_CREDENTIALS_SOURCE`, env-var mechanism
loaded from `.env` by the existing `python-dotenv` usage. Values:

- `infisical` — resolve credentials via the Infisical adapter.
- `legacy` — existing behavior byte-for-byte.
- absent or anything else — abort before **any** credential resolution.

Parsing lives in `src/adapters/sources/sigpesq/credentials.py` as a tiny pure
function (`parse_credential_source()`) so it is unit-testable without the
adapter. The message lists the accepted values and the variable name.

Existing deployments must add `SIGPESQ_CREDENTIALS_SOURCE=legacy` once — the
mode is deliberately mandatory (no implicit default), per Q3 of the clarify
session. Documented in `.env.example`, README, and quickstart.

### D2 — Infisical secrets provider (FR-001, FR-002, FR-006, FR-011)

- **Port** `src/core/ports/secret_provider.py`:
  `ISecretProvider.get_secret(secret_name: str) -> str`, raising a
  `CredentialResolutionError` (defined alongside the port) on any failure
  (missing secret, empty value, auth/connectivity, unreadable path, invalid
  config). The error carries a message that **never** includes the secret
  value.
- **Adapter** `src/adapters/secrets/infisical.py`:
  `InfisicalSecretProvider(ISecretProvider)`. Configuration read from the
  environment, with documented defaults per FR-002:
  - `INFISICAL_HOST` (default `https://app.infisical.com`)
  - `INFISICAL_CLIENT_ID` (required)
  - `INFISICAL_CLIENT_SECRET` (required)
  - `INFISICAL_PROJECT_ID` (required)
  - `INFISICAL_ENV` (default `dev`)
  - `INFISICAL_SECRET_PATH` (default `/`)
  - `INFISICAL_TIMEOUT_SECONDS` (optional; used for the SDK HTTP layer if
    honored by the pinned SDK — otherwise the SDK default applies)
  - The `infisical_sdk` import is lazy (inside methods) so tests never need
    the package or network.
- **Resolution flow**: `InfisicalSDKClient(host=host, cache_ttl=None)` →
  `auth.universal_auth.login(client_id, client_secret)` → one
  `secrets.get_secret_by_name(secret_name, project_id, environment_slug,
  secret_path)` per requested secret. `cache_ttl=None` disables the SDK cache
  so each run resolves fresh values (FR-011). Full round-trip inside one
  context-managed client session per run. SDK `APIError`/`InfisicalError` map
  to `CredentialResolutionError` with actionable messages (host unreachable,
  invalid machine identity, project/env/path not found, read permission
  denied) — never a generic webdriver login failure (FR-006).
- Secret names resolved: `sigpesq-user` and `sigpesq-password` (constants in
  `credentials.py`).

### D3 — Hand-off to the SigPesq download step (FR-008)

`agent_sigpesq`'s `SigpesqReportService` reads `SIGPESQ_USER` and
`SIGPESQ_PASSWORD` at construction (verified in
`.venv/lib/python3.14/site-packages/agent_sigpesq/services/reports_service.py`).
In `infisical` mode, after both secrets resolve and validate non-empty
(FR-005), `credentials.py` exports them to `os.environ` under the same names
the adapter already maintains today:

- `SIGPESQ_USERNAME` = resolved username
- `SIGPESQ_USER` = resolved username (alias the download step actually reads)
- `SIGPESQ_PASSWORD` = resolved password

`_validate_environment` then proceeds unchanged, so the download code path is
never modified. No `SIGPESQ_*` env var set by the operator is read in
`infisical` mode (FR-004).

### D-CI — Out-of-scope CI stays green (SC-006 + FR-003 interaction)

FR-003 makes the mode flag mandatory for every run that reaches the SigPesq
adapter, and the weekly GitHub workflow runs the SigPesq flows. To keep CI
fully out of scope credential-wise, add **one** env line to
`.github/workflows/weekly-etl.yml`:

```yaml
env:
  ...
  SIGPESQ_CREDENTIALS_SOURCE: legacy   # CI continues to use GitHub secrets only
```

No Infisical variables, no secret migration; the GitHub-secret sourcing and
`Validate required secrets` step are unchanged. This is the minimal bridle
FR-003 requires and preserves SC-006's substance.

### No-leak and observability (FR-009, FR-010)

- `InfisicalSecretProvider` masks values in its own logging (never prints
  them); `credentials.py` logs only the mode and resolved count.
- `CredentialResolutionError` messages name the configuration item/secret but
  never the value; tests assert this for both fake and mocked-SDK paths.
- No credential is written to any file; exports/artifacts are untouched.

## Definition of Done

- With only Infisical connection settings configured and
  `SIGPESQ_CREDENTIALS_SOURCE=infisical`, `SigPesqAdapter.extract()` resolves
  `sigpesq-user`/`sigpesq-password` and hands the pair to `agent_sigpesq`
  through `SIGPESQ_USER`/`SIGPESQ_PASSWORD` (SC-001, FR-001/FR-008, validated
  with a fake provider + mocked SDK; live run documented in quickstart).
- Missing or empty secret aborts before any download with a message naming the
  secret (SC-002, FR-005); unreachable host/invalid identity abort with a
  connectivity/auth message (FR-006); a single resolvable secret aborts
  (FR-004, SC-002).
- A full scan of logs and error output finds zero occurrences of the resolved
  username/password in tests (SC-003, FR-009).
- `legacy` mode yields byte-for-byte existing behavior including the
  `SIGPESQ_USER` alias (SC-004, FR-007); the mode flag is required and
  documented (FR-003, FR-012).
- GitHub Actions weekly workflow gains only `SIGPESQ_CREDENTIALS_SOURCE:
  legacy` and keeps GitHub-secret sourcing (SC-006, D-CI).
- `infisicalsdk==1.0.17` added to `requirements.txt` (and `pyproject.toml`);
  `make ci-check` passes; new targeted tests are green, existing suite stays
  green.

## Complexity Tracking

> Filled only if Constitution Check has violations that must be justified.

No violations. The new adapter/port pair is mandated by Constitution I (a new
external system must be mediated by a port contract); it adds one small
interface and one thin implementation, no schema, no flow changes, no new
subsystem.