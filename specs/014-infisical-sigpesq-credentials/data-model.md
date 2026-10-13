# Data Model: Infisical-backed SigPesq Credentials

**Branch**: `017-infisical-sigpesq-credentials` | **Date**: 2026-10-13

No database entities change and no persistent stores are introduced. This
document models the configuration surface the feature adds and the
resolution state machine it introduces, plus the transient payload handed to
the SigPesq download step.

## Entity 1 — Credential mode (`SIGPESQ_CREDENTIALS_SOURCE`)

The explicit, mandatory selection of where the SigPesq credential pair comes
from. Env-loaded through the existing `.env`/environment mechanism.

| Field | Type | Values | Validation |
|---|---|---|---|
| `SIGPESQ_CREDENTIALS_SOURCE` | str | `infisical`, `legacy` | absent or any other value → abort before any resolution (FR-003) |

### State transitions

```text
[ absent ] ──► ABORT (message lists variable + accepted values)
[ invalid ] ─► ABORT (same message)
[ "legacy" ] ─► run legacy validation path (existing behavior, FR-007)
[ "infisical" ] ─► resolve pair via ISecretProvider (FR-001)
```

Deterministic; no auto-detection and no implicit default (Q3).

## Entity 2 — Infisical connection settings

Non-secret-plus-machine-identity variables that let the pipeline reach the
Infisical instance (FR-002). Read once per run by `InfisicalSecretProvider`.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `INFISICAL_HOST` | no | `https://app.infisical.com` | HTTP(S) base URL of the instance |
| `INFISICAL_CLIENT_ID` | yes | — | Universal Auth machine identity ID |
| `INFISICAL_CLIENT_SECRET` | yes | — | Universal Auth machine identity secret |
| `INFISICAL_PROJECT_ID` | yes | — | project that holds the secrets |
| `INFISICAL_ENV` | no | `dev` | environment slug (e.g. `dev`, `prod`) |
| `INFISICAL_SECRET_PATH` | no | `/` | folder within the environment |
| `INFISICAL_TIMEOUT_SECONDS` | no | SDK default | optional HTTP-layer bound (R3) |

Missing required connection settings produce a `CredentialResolutionError`
naming the missing variable **before** any network call.

## Entity 3 — Resolved SigPesq credential pair

Transient, in-memory, per-run values resolved from the Infisical location.

| Field | Source secret | Non-empty required | Handed to download step as |
|---|---|---|---|
| username | `sigpesq-user` | yes (FR-005) | `SIGPESQ_USERNAME` + `SIGPESQ_USER` (alias) |
| password | `sigpesq-password` | yes (FR-005) | `SIGPESQ_PASSWORD` |

### Invariants

- **Exclusivity (FR-004)**: in `infisical` mode the pair is read exclusively
  from Infisical; operator-set `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`/
  `SIGPESQ_USER` are ignored — never mixed or fallen back to.
- **Fidelity**: values are used exactly as stored — no trimming, no quoting
  (edge case); padded values fail loudly on the portal if wrong.
- **Freshness (FR-011)**: each run opens a new SDK client with
  `cache_ttl=None` and resolves again; an Infisical edit takes effect next run.
- **No persistence**: values live only in process env for the run duration;
  nothing is written to disk or DB.
- **Pair atomicity (FR-005, edge case)**: both secrets must resolve to
  non-empty; one missing → abort naming it.
- **No leakage (FR-009)**: no log line, error message, artifact, or export may
  contain the resolved values.

### Resolution state machine

```text
[ infisical mode selected ]
      │
      ▼
[ validate connection config ] ──missing var──► ABORT (names variable)
      │
      ▼
[ universal_auth.login() ] ──APIError/InfisicalError──► ABORT (auth/connectivity, FR-006)
      │
      ▼
[ get sigpesq-user ] ──missing/empty──► ABORT (names secret, FR-005)
      │
      ▼
[ get sigpesq-password ] ──missing/empty──► ABORT (names secret, FR-005)
      │
      ▼
[ export SIGPESQ_USERNAME / SIGPESQ_USER / SIGPESQ_PASSWORD to os.environ ]
      │
      ▼
[ continue _validate_environment → _trigger_download (agent_sigpesq unchanged) ]
```

Every abort occurs **before** any SigPesq portal access, satisfying User Story 2.

## External structures (unchanged, consumed only)

- `agent_sigpesq.services.reports_service.SigpesqReportService` reads
  `SIGPESQ_USER` / `SIGPESQ_PASSWORD` at construction — this feature does not
  modify it (FR-008, spec Dependencies).
- `SigPesqAdapter._validate_environment` keeps its env-var alias mapping
  (`SIGPESQ_USER` ⇄ `SIGPESQ_USERNAME`); in `infisical` mode those vars are
  populated by the resolver instead of by the operator.