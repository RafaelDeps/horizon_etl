# Research: Infisical-backed SigPesq Credentials

**Branch**: `017-infisical-sigpesq-credentials` | **Date**: 2026-10-13

Phase 0 output. All unknowns resolved by reading the affected code, the SDK
installation in the `infisical_test` sibling repo, and the existing weekly CI
workflow.

## R1 — Infisical SDK package and API surface

**Decision**: add `infisicalsdk==1.0.17` (PyPI `infisicalsdk`, import
`infisical_sdk`) to `requirements.txt`, and `infisicalsdk>=1.0.17` to
`pyproject.toml` dependencies. Use the SDK exactly as validated in
`/home/henriq/Projects/gith/infisical_test/test_credentials.py`:

```python
from infisical_sdk import InfisicalSDKClient
from infisical_sdk.infisical_requests import APIError, InfisicalError

with InfisicalSDKClient(host=host, cache_ttl=None) as client:
    client.auth.universal_auth.login(client_id=..., client_secret=...)
    secret = client.secrets.get_secret_by_name(
        secret_name=..., project_id=..., environment_slug=..., secret_path=...,
    )
    value = secret.secretValue
```

**Rationale**: the user's proof-of-concept already exercised login + read
against the real instance; reusing the same version (`1.0.17`, verified in
`infisical_test/.venv`) and the same call surface removes API-discovery risk.
`cache_ttl=None` disables the SDK's in-memory secret cache, which satisfies
FR-011 (credentials must be resolved fresh on each run).

**Alternatives considered**:
- The older `infisical` package (InfisicalClient, token-based) — rejected: not
  what the validated POC used, and it predates the Universal Auth workflow the
  identity is configured for.
- Shelling out to Infisical CLI — rejected: adds a runtime binary dependency
  and bypasses the ports-and-adapters seam.

## R2 — Connection settings names and defaults (FR-002)

**Decision**: reuse the exact env var names from the validated POC and the
`infisical_test/README.md` table, with the same defaults:

| Variable | Required | Default |
|---|---|---|
| `INFISICAL_HOST` | no | `https://app.infisical.com` |
| `INFISICAL_CLIENT_ID` | yes | — |
| `INFISICAL_CLIENT_SECRET` | yes | — |
| `INFISICAL_PROJECT_ID` | yes | — |
| `INFISICAL_ENV` | no | `dev` |
| `INFISICAL_SECRET_PATH` | no | `/` |
| `INFISICAL_TIMEOUT_SECONDS` | no | SDK default (see R3) |

These flow through the existing env-variable mechanism (`python-dotenv`, used
by the flows and existing adapter module constants like
`_SIGPESQ_429_WAIT_SECONDS`).

**Rationale**: keeps operator knowledge from the `infisical_test` project
directly transferable; matches the spec assumption that defaults match the
existing test-setup values (`dev` environment, `/` secret path).

**Alternatives considered**: a custom `SIGPESQ_INFISICAL_*` prefix — rejected;
it would alias well-known Infisical tooling conventions for no benefit.

## R3 — Timeout / retry parameters (deferred plan item)

**Decision**: no SDK-level retry loop in v1; the SDK's `InfisicalSDKClient`
constructor only exposes `host`, `token`, `cache_ttl` (verified by
`inspect.signature` in the installed 1.0.17 wheel) — there is no timeouts
parameter in the constructor. Rely on the SDK's internal request timeout and
fail fast: any `APIError`/`InfisicalError` aborts the run before any SigPesq
access (FR-006). If an operator needs a bound at the HTTP layer later,
`INFISICAL_TIMEOUT_SECONDS` is documented as an optional override that the
adapter forwards to the SDK's request layer if supported by a future SDK
version.

**Rationale**: fail-fast is the spec's chosen behavior (User Story 2); the
existing `agent_sigpesq` retry machinery already handles transient SigPesq
portal slowness and must never be reached with stale/empty credentials.

**Alternatives considered**: wrapping fetch in `tenacity` retries — rejected as
scope creep; a retried login could mask a genuinely bad machine identity and
delay the clear error FR-006 requires.

## R4 — Where the mode dispatch and resolution live

**Decision**: a new `src/adapters/sources/sigpesq/credentials.py` module owns
mode parsing and the resolution helper; `SigPesqAdapter._validate_environment`
becomes the single dispatch point that `extract()` already calls today. The
Infisical interaction is mediated by a new port contract
`ISecretProvider` in `src/core/ports/secret_provider.py`, implemented by
`src/adapters/secrets/infisical.py`.

**Rationale**: `_validate_environment` is the existing credential-check seam
called from the top of `extract()`; every flow path (`download_all_sigpesq_reports`,
`ingest_sigpesq_flow`, `projects`/`groups`/`advisorships` flows) funnels
through it. Routing Infisical through a port keeps Constitution I intact.
Flows need no changes.

**Alternatives considered**:
- Resolving in the flows layer — rejected: five flow entry points would each
  duplicate the same env parsing; constitution reserves orchestration in
  flows, not per-secret configuration parsing.
- Direct SDK import inside `_validate_environment` — rejected: bypasses the
  mandated port contract for a new external system.

## R5 — Mode flag name and semantics (FR-003)

**Decision**: `SIGPESQ_CREDENTIALS_SOURCE` with values `infisical` and
`legacy`. Absent or any other value → abort before any credential resolution,
message listing both accepted values and the variable name. No default, no
auto-detection (Q3 answer).

**Rationale**: explicit flag per the clarified spec; abort-instead-of-guess is
precisely what User Story 4 / acceptance scenario 3 requires (partial config
must fail with a message describing the incomplete configuration).

**Alternatives considered**: defaulting to `legacy` — rejected, it would
contradict FR-003 and silently skip real credential validation.

## R6 — Hand-off mechanism to the download step (FR-008, deferred plan item)

**Decision**: the download step (`agent_sigpesq.SigpesqReportService.__init__`)
reads `SIGPESQ_USER` and `SIGPESQ_PASSWORD` from the process environment —
verified in `.venv/lib/python3.14/site-packages/agent_sigpesq/services/reports_service.py`
(lines 28-29, 80). Therefore the resolution helper exports the resolved pair
via `os.environ` under `SIGPESQ_USERNAME`, `SIGPESQ_USER`, and
`SIGPESQ_PASSWORD` (the alias set the adapter already maintains today), then
lets `_validate_environment` finish its existing checks. The `agent_sigpesq`
component is not modified.

**Rationale**: FR-008 asks for the same shape/names the download step expects;
setting env vars is the mechanism and costs zero changes to the external
component or to `_trigger_download`.

**Alternatives considered**: passing credentials as constructor args through
`SigpesqReportService` — rejected: that library is read-only for this feature
(the spec dependency section says it must remain unchanged).

## R7 — CI interaction with the mandatory flag (SC-006 + FR-003)

**Decision**: CI stays on GitHub secrets (out of scope, Q2 answer). Because
FR-003 makes the mode flag mandatory for any run that reaches the SigPesq
adapter, `.github/workflows/weekly-etl.yml` gains exactly **one** env line:
`SIGPESQ_CREDENTIALS_SOURCE: legacy`. No Infisical variables are added, the
secrets list and `Validate required secrets` step are untouched.

**Rationale**: without this line the weekly workflow would now abort on the
missing flag — an unintended CI behavior change that violates SC-006. One
`legacy` line keeps the credential source exactly as today (GitHub secrets)
while satisfying FR-003.

**Alternatives considered**: leaving CI untouched and treating "absent" as
legacy in CI specifically — rejected (special-casing CI breaks the
explicit-flag contract). Building default-to-legacy into the flag — rejected
(contradicts FR-003).

## R8 — Testing strategy (offline, hermetic)

**Decision**: all Infisical behavior is tested without network or SDK
installation:
- `tests/test_infisical_secret_provider.py` — unit tests of
  `InfisicalSecretProvider` with `infisical_sdk` import mocked
  (`patch.dict(sys.modules, {...})` or patching the lazy import), exercising
  login + `get_secret_by_name` calls, missing/empty secret, error mapping, and
  value masking.
- `tests/test_sigpesq_credentials_mode.py` — `SigPesqAdapter._validate_environment`
  with a fake `ISecretProvider`: mode parsing (valid/absent/invalid),
  legacy-preservation, infisical handoff via env vars, no-mixing, fail-fast,
  and no-leak assertions on loguru output.
- `tests/test_sigpesq_adapter.py` — extended with an infisical-mode
  end-to-end extract test using a fake provider so the real `extract()` path
  (validate → clean → trigger → load) is exercised with mocked download.

**Rationale**: the existing suite already uses exactly this pattern
(`test_sigpesq_adapter.py` patches `dotenv.load_dotenv` and constructs the
service from the cached import; extract tests patch `_validate_environment`).
Mocking the SDK keeps `make ci-check` offline and repeatable.

**Alternatives considered**: an integration test hitting live Infisical —
kept out of the unit suite; the quickstart documents the manual live smoke
instead.

## Consolidated decision list

| # | Area | Decision |
|---|---|---|
| R1 | Dependency | `infisicalsdk==1.0.17`, SDK call surface from validated POC |
| R2 | Config | `INFISICAL_HOST/CLIENT_ID/CLIENT_SECRET/PROJECT_ID/ENV/SECRET_PATH` |
| R3 | Timeout | fail-fast, no SDK retry; optional `INFISICAL_TIMEOUT_SECONDS` |
| R4 | Placement | port + adapter for Infisical; credentials.py; `_validate_environment` dispatches |
| R5 | Mode flag | `SIGPESQ_CREDENTIALS_SOURCE` = `infisical` \| `legacy`, absent/invalid aborts |
| R6 | Hand-off | `os.environ` exports under `SIGPESQ_USERNAME`/`SIGPESQ_USER`/`SIGPESQ_PASSWORD` |
| R7 | CI | one env line `SIGPESQ_CREDENTIALS_SOURCE: legacy`; GitHub secrets unchanged |
| R8 | Tests | hermetic: mocked SDK + fake provider; live smoke lives in quickstart |