# Contract: `sync_members` and `sync_single_group`

**Feature**: 011-cnpq-sync-index-reuse | **Date**: 2026-09-01

Internal call-site contract — not a public API, but documented because the
signature changes and there must be exactly one place that needs updating.

## Before

```python
# src/flows/cnpq/groups.py
@task
def sync_single_group(group_info: dict): ...
    sync_logic = CnpqSyncLogic()
    ...
    sync_logic.sync_members(group_id, members, source_file=url)

# src/core/logic/strategies/cnpq_sync.py
def sync_members(self, group_id, members_data, *, source_file=None):
    all_res = self.res_ctrl.get_all()          # 8.81s, every call
    for m_data in members_data:
        ...
        all_roles = self.role_ctrl.get_all()   # every member
```

## After

```python
# src/flows/cnpq/groups.py
@task(cache_policy=NO_CACHE)
def sync_single_group(group_info: dict, researcher_index: list[ResearcherRef]):
    sync_logic = CnpqSyncLogic()
    ...
    sync_logic.sync_members(
        group_id, members, source_file=url, researcher_index=researcher_index
    )

@flow(...)
def sync_cnpq_groups_flow(campus_name=None):
    ...
    session = ResearcherController()._service._repository._session
    researcher_index = load_researcher_index(session)
    for g_info in groups:
        sync_single_group(g_info, researcher_index)

# src/core/logic/strategies/cnpq_sync.py
def sync_members(self, group_id, members_data, *, source_file=None, researcher_index):
    all_roles = self.role_ctrl.get_all()        # once per group, not per member
    for m_data in members_data:
        ...
        # uses researcher_index in place of all_res
```

## Invariants that must hold after the change

1. **Single read**: the researcher registry is fetched exactly once per
   `sync_cnpq_groups_flow` execution (FR-001, SC-001).
2. **Cross-group visibility**: a researcher created while processing any
   group is found — not recreated — by every subsequently processed group in
   the same run (FR-003).
3. **Behavioral equivalence**: for the same input data, the set of matched or
   created researchers, and the set of assigned roles, is identical to the
   pre-change behavior (FR-004, FR-005).
4. **Single caller**: `sync_members` has exactly one call site
   (`sync_single_group`); if a second call site is found during
   implementation, it must be updated in the same change or the contract is
   violated.
