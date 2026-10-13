# Quickstart: Infisical-backed SigPesq Credentials

**Branch**: `017-infisical-sigpesq-credentials` | **Date**: 2026-10-13

Runbook to implement, test, and manually verify the feature. All commands run
from the repository root.

## 0. Preconditions

```sh
git branch --show-current        # expect: 017-infisical-sigpesq-credentials
test -d .venv || make setup      # venv with requirements installed
.venv/bin/pip install "infisicalsdk==1.0.17"   # new dependency (added by the task)
```

Read [contracts/credential_source_config.md](./contracts/credential_source_config.md)
(C1–C4 rules) and [data-model.md](./data-model.md) (resolution state machine)
before starting.

## 1. Fast, targeted verification (implementers loop)

```sh
.venv/bin/python -m pytest tests/test_infisical_secret_provider.py -q
.venv/bin/python -m pytest tests/test_sigpesq_credentials_mode.py -q
.venv/bin/python -m pytest tests/test_sigpesq_adapter.py -q
```

All must pass. C1–C4 map 1:1 to these files. Every test is offline: the
Infisical SDK is mocked and the provider is faked, so no live Infisical and no
network are required.

## 2. Full gate

```sh
make ci-check        # flake8 + black + isort + mypy + pytest
```

Compare against the pre-existing baseline (known failures recorded in
specs/009, e.g. `test_export_canonical_data_flow.py`, the
`test_sigpesq_adapter.py` 429 test, `test_download_lattes_flow.py`) — do not
fix those here.

## 3. Local configuration smoke (no portal access)

**Legacy mode (backward compatibility)**: in `.env`, keep
`SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD` and add

```sh
SIGPESQ_CREDENTIALS_SOURCE=legacy
```

Run the validation-only path so no browser starts:

```sh
.venv/bin/python - <<'PY'
from src.adapters.sources.sigpesq.adapter import SigPesqAdapter
SigPesqAdapter()._validate_environment()
print("legacy validation OK")
PY
```

Expected: `legacy validation OK` (or the existing missing-vars error if the
credentials are absent).

**Infisical mode**: in `.env` set

```sh
SIGPESQ_CREDENTIALS_SOURCE=infisical
INFISICAL_HOST=https://app.infisical.com
INFISICAL_CLIENT_ID=<machine-identity-id>
INFISICAL_CLIENT_SECRET=<machine-identity-secret>
INFISICAL_PROJECT_ID=<project-id>
INFISICAL_ENV=dev
INFISICAL_SECRET_PATH=/
```

(Values match the validated proof of concept in the sibling
`infisical_test` project.) Then run the same `_validate_environment()` snippet.

Expected: it resolves `sigpesq-user` and `sigpesq-password`, exports
`SIGPESQ_USERNAME`/`SIGPESQ_USER`/`SIGPESQ_PASSWORD`, and prints `OK` — with
**no credential value anywhere in the output**.

**Mode-flag failure**: remove `SIGPESQ_CREDENTIALS_SOURCE` (or set it to
`typo`) and re-run. Expected: an immediate abort naming the variable and both
accepted values, before any resolution.

**Missing-secret failure**: point `INFISICAL_SECRET_PATH` at an empty folder
and re-run. Expected: an abort naming `sigpesq-user` (or `sigpesq-password`)
and no portal access.

## 4. End-to-end live run (optional, needs the real account)

With Infisical mode fully configured and `SIGPESQ_USERNAME`/`SIGPESQ_PASSWORD`
**removed** from `.env`:

```sh
make weekly-flows          # or the SigPesq ingestion flow of your choice
```

Expected: the SigPesq portal login succeeds using the Infisical-resolved pair
and reports download; scan the run log for the plaintext username/password —
zero matches (SC-001/SC-003).

## 5. What each artifact proves

- [data-model.md](./data-model.md) — the mode → resolution → hand-off state
  machine and exclusivity/freshness/no-leak invariants.
- [contracts/credential_source_config.md](./contracts/credential_source_config.md)
  — C1–C4, each mapped to the test that pins it.
- [research.md](./research.md) — R1–R8 decisions (SDK version/API, config
  names, timeout policy, placement, hand-off, CI line, test strategy).