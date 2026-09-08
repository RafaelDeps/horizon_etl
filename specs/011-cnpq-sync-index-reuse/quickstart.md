# Quickstart: verifying the CNPq sync fix

**Feature**: 011-cnpq-sync-index-reuse | **Date**: 2026-09-01

## 1. Unit tests

```bash
.venv/bin/python -m pytest tests/test_cnpq_sync.py -v
```

Expect all passing, in well under 5 seconds — no database, no network.

## 2. Confirm the registry is read once, not once per group

Against a copy of the database (never the live `db/horizon.db`):

```bash
cp db/horizon.db /tmp/cnpq-check.db
DATABASE_URL="sqlite:////tmp/cnpq-check.db" STORAGE_TYPE=db .venv/bin/python -c "
from loguru import logger; logger.remove()
from sqlalchemy import event
from research_domain.controllers import ResearcherController
ctrl = ResearcherController()
session = ctrl._service._repository._session
calls = {'n': 0}
@event.listens_for(session.get_bind(), 'before_cursor_execute')
def _count(*a, **k):
    calls['n'] += 1

from src.flows.cnpq.groups import sync_cnpq_groups_flow
sync_cnpq_groups_flow.fn()
print('cursor executions during the run:', calls['n'])
"
```

A single full-registry read shows up as one query near the start of the run,
not one per group — visually confirmed by comparing against the pre-fix
behavior (351 near-identical multi-join queries repeated throughout the log).

## 3. End-to-end equivalence (SC-003)

Run a full weekly pipeline before and after the change, from the same
starting database snapshot, and compare:

```bash
cp db/horizon.db /tmp/before_fix.db
# ... apply the change ...
make weekly-flows
```

Then compare table counts between `/tmp/before_fix.db` and the post-run
`db/horizon.db` for `researchers`, `persons`, `roles`, `team_members`,
`research_groups` — any difference beyond what the CNPq source data itself
contributed independently of this change is a regression.
