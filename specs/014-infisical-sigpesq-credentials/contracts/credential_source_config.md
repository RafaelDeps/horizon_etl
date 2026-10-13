# Contract: Credential Source Configuration

**Branch**: `017-infisical-sigpesq-credentials` | **Date**: 2026-10-13

This is the interface contract for the feature: the environment-variable
configuration surface plus the behavioral contract tests pin. It maps 1:1 to
tests (R = rule number).

## C1 — Mode flag (FR-003, FR-007)

| Rule | Contract | Pinned by |
|---|---|---|
| C1-01 | `SIGPESQ_CREDENTIALS_SOURCE` accepts exactly two values: `infisical` and `legacy`. | `tests/test_sigpesq_credentials_mode.py` |
| C1-02 | If the variable is absent, the run aborts before any credential resolution with a message naming the variable and both accepted values. | same |
| C1-03 | If the variable holds any other value, the run aborts with the same message. | same |
| C1-04 | `legacy` mode reproduces today's behavior byte-for-byte, including the `SIGPESQ_USER` ⇄ `SIGPESQ_USERNAME` alias and missing-vars error. | same |
| C1-05 | No auto-detection and no implicit default: partial config is never silently interpreted. | same |

## C2 — Infisical resolution (FR-001, FR-002, FR-005, FR-006)

| Rule | Contract | Pinned by |
|---|---|---|
| C2-01 | In `infisical` mode, `sigpesq-user` and `sigpesq-password` are resolved from `INFISICAL_PROJECT_ID` / `INFISICAL_ENV` / `INFISICAL_SECRET_PATH` via Universal Auth. | `test_infisical_secret_provider.py` |
| C2-02 | Missing required connection setting (`INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`, `INFISICAL_PROJECT_ID`) aborts naming the variable, before any network call. | same |
| C2-03 | A missing or empty secret aborts naming the exact secret (`sigpesq-user` or `sigpesq-password`) — never a combined message. | same |
| C2-04 | Authentication failure (bad/expired identity) or connectivity failure (unreachable host) aborts with an auth/connectivity message; the run never proceeds with placeholder, stale, or cached values. | same |
| C2-05 | Each run resolves fresh values (SDK `cache_ttl=None`); an Infisical edit is picked up on the next run. | same |
| C2-06 | Values are returned exactly as stored — no trimming, no quoting. | same |

## C3 — Hand-off (FR-008, FR-004)

| Rule | Contract | Pinned by |
|---|---|---|
| C3-01 | After resolution, `os.environ` carries `SIGPESQ_USERNAME`, `SIGPESQ_USER` (alias), and `SIGPESQ_PASSWORD` set to the resolved values. | `tests/test_sigpesq_credentials_mode.py`, `test_sigpesq_adapter.py` |
| C3-02 | In `infisical` mode, operator-set `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`/`SIGPESQ_USER` are ignored — never mixed or fallen back to. | same |
| C3-03 | A single resolvable secret aborts; one Infisical secret is never combined with a legacy value. | same |
| C3-04 | The `agent_sigpesq` download component and `_trigger_download` are not modified. | `tests/test_sigpesq_adapter.py` (T009: download path invoked unchanged) |

## C4 — No leakage and observability (FR-009, FR-010)

| Rule | Contract | Pinned by |
|---|---|---|
| C4-01 | No log line, error message, or raised exception contains the resolved username or password (asserted against loguru output and exception text). | `test_sigpesq_credentials_mode.py` |
| C4-02 | Logs at debug/verbose level still contain no plaintext credential values. | same |
| C4-03 | Resolved credentials never reach generated artifacts or exports. | `test_sigpesq_credentials_mode.py::test_credentials_never_reach_generated_artifacts` (plus quickstart §4 artifact/export scan, T018), SC-003 |

## Default values summary (FR-002)

`INFISICAL_HOST`=`https://app.infisical.com` · `INFISICAL_ENV`=`dev` ·
`INFISICAL_SECRET_PATH`=`/` · `INFISICAL_TIMEOUT_SECONDS`=SDK default
(`INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`, `INFISICAL_PROJECT_ID` are
required, no default).