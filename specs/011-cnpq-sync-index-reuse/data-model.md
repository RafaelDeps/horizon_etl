# Data Model: researcher/role registries in CNPq member sync

**Feature**: 011-cnpq-sync-index-reuse | **Date**: 2026-09-01

No database schema changes. The only new state is in-memory, scoped to a
single flow run.

## Researcher registry snapshot

Identical in shape to feature 007's `ResearcherRef` — reused, not redefined.

| Field | Source | Used for |
|---|---|---|
| `id` | `researchers.id` | Identifies the match once found |
| `name` | `persons.name` | Name comparison in `resolve_or_create_researcher` |
| `identification_id` | `persons.identification_id` | Same comparison, secondary key |
| `cnpq_url` | `researchers.cnpq_url` | Same comparison |
| `resume` | `researchers.resume` | Tie-break scoring, unchanged from feature 007 |
| `citation_names` | `researchers.citation_names` | Tie-break scoring, unchanged |

**Lifecycle within a run**:

```text
sync_cnpq_groups_flow starts
  │
  ├─ build researcher index once  ──►  list[ResearcherRef], length = current
  │                                     researcher count
  │
  ├─ for each group (351×):
  │     sync_single_group(group_info, researcher_index)
  │        └─ sync_members(..., researcher_index)
  │              for each member:
  │                 resolve_or_create_researcher(researcher_index, ...)
  │                    found  → return existing ResearcherRef
  │                    not found → create researcher, APPEND to
  │                                researcher_index in place
  │
  └─ flow ends; researcher_index discarded
```

The list is **mutated in place** by append — this is the mechanism, already
built in feature 007, that lets a researcher created while processing group 5
be found by group 200 later in the same run, without rereading the registry.

## Role registry snapshot

Same shape as today's `self.role_ctrl.get_all()` result (full `Role` ORM
entities) — unchanged. Only its *scope* changes: read once per call to
`sync_members` (i.e., once per group) instead of once per member inside that
call.

```text
sync_members(group_id, members_data, ...)
  │
  ├─ read role registry once  ──►  list[Role]  (11 rows today)
  │
  └─ for each member:
        match role by case-insensitive name against the registry already in
        hand; create a new role (and, implicitly, extend what a *later group*
        would see, since the next group's read is a fresh, current query)
```

No cross-group carry-over is needed for roles: each group's `sync_members`
call performs its own single read at the top, current as of that call.

## What does NOT change

- `Researcher`, `Person`, `Role` entity definitions.
- The matching rules inside `resolve_or_create_researcher` and the role
  case-insensitive comparison.
- Anything written to the database — same rows, same values, same order of
  creation for a given input, per FR-004/FR-005.
