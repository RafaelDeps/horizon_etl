# Research: reuse the researcher index in CNPq member sync

**Feature**: 011-cnpq-sync-index-reuse | **Date**: 2026-09-01

## R1 — Where the fix must live: flow, not the sync class

**Decision**: build the researcher index once in `sync_cnpq_groups_flow` and pass
it down through `sync_single_group` into `sync_members`, mirroring the pattern
already used by the Lattes flows in feature 007.

**Rationale**: `CnpqSyncLogic()` is constructed fresh inside `sync_single_group`
(`src/flows/cnpq/groups.py:113`), which is itself a Prefect `@task` invoked once
per group — 351 times per run (`src/flows/cnpq/groups.py:255-256`,
`for g_info in groups: sync_single_group(g_info)`). Any cache placed on `self`
inside `CnpqSyncLogic.__init__` or `sync_members` is rebuilt from scratch on
every call, because there is no `self` that survives across groups. The only
object that survives the whole run is the flow's own local state — so the
index has to be built there, exactly once, and threaded through the task
boundary as an explicit parameter.

**Alternative considered and rejected**: caching inside `CnpqSyncLogic`
(module-level cache, or a cache keyed by nothing). Rejected because it would
introduce global mutable state shared across unrelated flow runs and tests —
a correctness risk with no precedent in this codebase — when passing the
index explicitly as a parameter, the way feature 007 already does, has none of
that risk and already has a working precedent to copy.

## R2 — Passing a mutable list across a Prefect task boundary

**Decision**: decorate `sync_single_group` with `cache_policy=NO_CACHE` once it
gains a `researcher_index: list[ResearcherRef]` parameter, following the exact
precedent in `src/flows/lattes/advisorships.py:25` and
`src/flows/lattes/projects.py:317`.

**Rationale**: `sync_single_group` already receives a `dict` (`group_info`) as
a task parameter without `NO_CACHE`, so Prefect's default task caching
tolerates unhashable dict parameters today without complaint. Feature 007
nonetheless added `NO_CACHE` explicitly wherever a task received a shared
mutable list of `ResearcherRef`, because it is the list *identity* that must be
preserved call to call (append-in-place from `resolve_or_create_researcher`),
not just its contents — an equality-based cache would be free to treat two
calls with "the same" list as interchangeable, silently discarding the
append made by an intervening call. Matching that precedent removes any doubt
rather than relying on today's default behavior continuing to be safe.

## R3 — Session for `load_researcher_index`

**Decision**: obtain the session once in the flow via a throwaway
`ResearcherController()._service._repository._session`, exactly the pattern
already used for the Lattes flows, and pass the resulting index down — not the
session itself.

**Rationale**: all controllers in this codebase share one global SQLAlchemy
session (verified: `self.res_ctrl`, `self.rg_ctrl`, and `self.role_ctrl` inside
`CnpqSyncLogic` all resolve to the same `_repository._session` object, and this
is the same session `load_researcher_index` expects). The flow does not need
`CnpqSyncLogic` to exist yet to get that session — a bare `ResearcherController()`
is sufficient and matches what `get_groups_to_sync` already does one call
above it in the same file.

## R4 — Keeping the self-healing joined-table fix intact

**Decision**: no change to the raw-SQL self-healing block in `sync_members`
(`src/core/logic/strategies/cnpq_sync.py:306-`) that inserts a bare row into
`researchers` when a partial joined-table insert is detected.

**Rationale**: that block runs *after* a researcher is resolved or created,
using `self.rg_ctrl._service._repository._session` — the same shared session.
It is untouched by this feature: it neither reads nor writes the researcher
index, and the index's `ResearcherRef` records only need `id`, which this block
does not affect. Confirmed by inspection that none of the fields the block
touches are read from `ResearcherRef` anywhere.

## R5 — Role lookup scope

**Decision**: hoist `self.role_ctrl.get_all()` from inside the per-member loop
to the top of `sync_members`, run once per group — not once per run.

**Rationale**: the spec (FR-002) asks for once-per-group, not once-per-run,
because the measured cost (an 11-row table) does not justify the added
complexity of threading a second index across the flow/task boundary. Fixing
it locally, inside the function that already owns the loop, is the smallest
change that satisfies the requirement and carries no risk of stale data across
groups (roles are rarely created mid-run, and if one is, the next group's
fresh per-group read picks it up immediately — unlike the researcher case,
where waiting a full group before seeing a new name is the exact problem being
fixed).

## R6 — Test strategy

**Decision**: unit tests against `CnpqSyncLogic` following the
`ProjectLoader.__new__` + `MagicMock` collaborator pattern already established
in `tests/test_project_loader_matching.py` for features 007/008 — no database,
no Prefect context.

**Rationale**: the defect this feature guards against (a group's newly created
researcher being invisible to the next group, or the reverse — a researcher
never reused because there is no shared list to check) is a pure logic
question about what list identity gets read and mutated, independent of the
database and of Prefect. It reproduces in-process in milliseconds, matching
the same reasoning the project already applied when guarding the similar
merge/dedup regression in feature 008.
