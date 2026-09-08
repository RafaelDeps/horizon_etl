# Quickstart: verifying concurrent fetch, serial write

**Feature**: 012-cnpq-concurrent-fetch | **Date**: 2026-09-04

## 1. Unit tests

```bash
.venv/bin/python -m pytest tests/test_cnpq_groups_flow.py tests/test_cnpq_fetch_worker.py -v
```

Should include, at minimum: fetch results processed in submission order;
write calls proven never to overlap (see contracts/fetch_write_contract.md);
a failed fetch does not stop subsequent groups; `CNPQ_FETCH_CONCURRENCY=1`
falls back to one fetch in flight at a time.

## 2. Confirm concurrent fetches are actually concurrent

Against a copy of the database (never the live `db/horizon.db`):

```bash
cp db/horizon.db /tmp/cnpq-concurrent-check.db
DATABASE_URL="sqlite:////tmp/cnpq-concurrent-check.db" STORAGE_TYPE=db \
  CNPQ_FETCH_CONCURRENCY=4 .venv/bin/python -c "
from src.flows.cnpq.groups import sync_cnpq_groups_flow
sync_cnpq_groups_flow.fn()
"
```

In the log, timestamps for `Navigating to ...` lines (the network fetch) for
different groups should interleave — a later group's fetch starting before
an earlier group's fetch has finished — which never happens in the current
sequential code.

## 3. Confirm process isolation, not threads

While the run from step 2 is in progress:

```bash
ps -eo pid,ppid,cmd | grep -c "[c]hrome\|[c]hromium"
```

Should show multiple Chromium processes with **different parent PIDs**
corresponding to separate `ProcessPoolTaskRunner` worker processes, not
multiple browser sessions inside one Python process.

## 4. SC-001 / SC-003: duration

```bash
time DATABASE_URL="sqlite:////tmp/cnpq-concurrent-check.db" STORAGE_TYPE=db \
  CNPQ_FETCH_CONCURRENCY=4 .venv/bin/python app.py cnpq_sync
```

Compare against the 50.2-minute baseline. Then repeat with
`CNPQ_FETCH_CONCURRENCY=1` and confirm the duration returns to
approximately the baseline (SC-003).

## 5. SC-002: end-to-end equivalence

Same methodology already used for feature 011: snapshot the database before
the change, run `make weekly-flows` after, and diff table counts for
`researchers`, `persons`, `roles`, `team_members`, `research_groups`,
`advisorships` — plus, specific to this feature, cross-check CNPq-linked
`team_members` by natural key (group name, person name, role name), not
raw ID, since `db-reset` means IDs are not comparable across runs.

## 6. SC-004: failure isolation

Temporarily point one group's URL at an invalid address (or use a group
already known to fail — the `espelhogrupo/nepro` case from `docs/backlog.md`)
and confirm the run still completes with every other group processed.
