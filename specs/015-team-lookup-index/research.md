# Research: Team Lookup Index for the Lattes Ingestion Phases

**Feature**: [spec.md](spec.md) · **Date**: 2026-10-22

All measurements were taken against copies of the local database, never
`db/horizon.db` itself. Numbers come from
`docs/reports/2026-10-22-weekly-runtime-and-language-study.md` unless stated
otherwise.

## R1. Where the lookup lives

**Decision**: Inside `TeamSynchronizer` (`src/core/logic/team_synchronizer.py`).
It is built lazily on the first `ensure_team` call and lives as long as the
synchroniser, which means as long as its `ProjectLoader`. Each loader owns
exactly one synchroniser.

**Rationale**:
- `ensure_team` is the only team-matching entry point, and both callers in
  `InitiativeLinker` reach it through the loader's synchroniser.
- Putting the lookup there gives every phase the same single code path, as the
  2026-10-22 clarification requires (`sigpesq`, `lattes_projects` and
  `lattes_advisorships`).
- The lookup's lifetime is the loader's lifetime: once per phase for
  `lattes_projects` (one loader), and once per phase for `lattes_advisorships`
  after R7. `sigpesq` builds one per loader (projects, advisorships), so twice
  per phase.

**Alternatives considered**:
- *A module-level, process-wide cache.* Rejected: state would leak across tests
  and across phases run in one process (`weekly_inprocess`), and the lifetime
  would be harder to reason about.
- *A separate `TeamLookup` passed in from the flows.* Rejected: it changes every
  `ProjectLoader` construction site for no benefit, because the synchroniser
  already has the right scope.

## R2. How existing teams are read

**Decision**: One query, `SELECT id, name FROM teams ORDER BY id`, executed on
the team controller's SQLAlchemy session
(`team_controller._service._repository._session`), but only when that object is
a real `sqlalchemy.orm.Session`. In every other case (no attribute, `None`, or a
`MagicMock` in tests), fall back to a single `team_controller.get_all()` sorted
by `id`.

**Rationale**:
- **Cost.** The same rows take ~175 ms with plain SQL, against 1.5–1.9 s for
  `get_all()`, which eagerly joins members, persons and roles into ~3.7 M ORM
  objects. The new path also keeps those objects out of the session's identity
  map, which the comments in `project_loader.py` and `lattes/projects.py`
  identify as the cause of out-of-memory crashes on private runners.
- **Research groups stay included.** `ResearchGroup` uses joined-table
  inheritance from `Team` (`research_groups.id → teams.id`), so research groups
  are rows of `teams`. Today's scan therefore already considers research group
  names, and reading `teams` directly keeps exactly that behaviour.
- **Tests need the fallback.** A `MagicMock` controller exposes any attribute
  chain, including a fake `_session`, so an `isinstance(..., Session)` check is
  required. The existing tests (`test_ensure_team_matches_canonical_name`,
  `test_create_initiative_team_idempotent`) set `get_all.return_value` and must
  keep passing (FR-007).
- **There is precedent.** `load_researcher_index` in
  `src/core/logic/researcher_resolution.py` already reads with plain SQL on the
  controller's session from `src/core/logic/`, without importing adapters.

**Alternatives considered**:
- *Adding `lazy="selectin"` / `noload` to `Team.members` in `eo_lib`.*
  Rejected: FR-010 forbids changing external libraries (tracked upstream as a
  TD-009-style follow-up).
- *An ORM query with `noload` options on the session.* Viable, but it still
  builds ORM entities and adds them to the identity map, for no gain over two
  columns of plain SQL.

## R3. Picking up teams created outside the synchroniser

**Decision**: Keep `max_id`, the highest team id the lookup has seen. When a
lookup misses, run one incremental read,
`SELECT id, name FROM teams WHERE id > :max_id ORDER BY id`, merge the result,
and check again. Only if it still misses is a team created. The fallback mode
(no session) skips the incremental read, matching today's mock-based behaviour.

**Rationale**:
- Teams are created elsewhere in the same process: research groups are created
  by the SigPesq groups loader and by `cnpq_sync`, and a phase may run several
  loaders.
- Creation goes through `create_team` → `GenericSqlRepository.add`, which
  commits. A new row is therefore visible to a later `SELECT`, even from another
  session on the same SQLite file.
- The read uses the primary key, takes under a millisecond, and runs only on
  misses (≈ creations).

**Edge**:
- SQLite can reuse the highest `INTEGER PRIMARY KEY` value after that row is
  deleted.
- Teams are deleted only by `reference_consolidator` (phase
  `consolidate_duplicates`), which runs in its own subprocess after every phase
  that uses the lookup. No in-phase deletion exists, so `id > max_id` is
  complete. This is documented as an assumption in the spec.

**Alternatives considered**:
- *Re-reading the whole id/name list on every miss.* Rejected: ~175 ms per miss
  × ~11 000 creations per run, which brings the quadratic cost back.
- *Trusting only the in-memory lookup.* Rejected: it would duplicate teams
  created by other code, which FR-004 and acceptance scenario 1.5 rule out.

## R4. What `ensure_team` returns

**Decision**: An immutable `TeamRef(id: int, name: str)`, returned on hits and
also after creation (built from the created entity). On failure, `None`, as
today.

**Rationale**:
- Both callers (`create_initiative_team`, `add_members_to_initiative_team`) and
  `synchronize_members` use only `team.id` and truthiness.
- Returning one type keeps the contract simple and avoids holding ORM entities
  across CVs.
- This mirrors `ResearcherRef` from spec 007.

**Alternatives considered**:
- *`get_by_id` on hit, to return the full entity.* Rejected: that is one query
  plus a joined load per record, and no caller needs it.

## R5. Matching rule equivalence

**Decision**:
- The key is `normalize_text(name)`, the same function used today.
- The lookup is populated in ascending `id` order with "first writer wins"
  (`setdefault`).
- A lookup normalises the requested name and makes one dictionary probe.

**Rationale**:
- Today's loop returns the first team, in iteration order, satisfying
  `t_name == team_name or normalize_text(t_name) == normalize_text(team_name)`.
- Because `normalize_text` is a pure function, exact equality implies
  normalised equality, so the condition reduces to normalised equality alone.
- The first team in id order with the same key is exactly what `setdefault` over
  ascending ids keeps.
- Empty or `None` names normalise to `""` on both sides, as today.
- Today's iteration order is the implicit order of `get_all()`, which on SQLite
  is ascending `id` in practice. The spec makes that order explicit (FR-003). The
  controlled replay (SC-004) detects any divergence.
- The benchmark on 10 663 real teams and 361 real names gave 357/361 hits for
  both the current loop and the lookup.

## R6. Failure handling

**Decision**: If `create_team` raises, log the same warning as today, return
`None`, and leave the lookup unchanged (FR-005). `max_id` is not advanced.

**Rationale**: This is today's observable behaviour (the exception is caught
inside `ensure_team`). A later record asking for the same name will miss,
refresh and try again.

## R7. One `ProjectLoader` for `lattes_advisorships`

**Decision**:
- `ingest_lattes_advisorships_flow` builds one
  `ProjectLoader(mapping_strategy=None)` before the CV loop and passes it to
  `ingest_advisorships_file_task`.
- For each CV, the task sets
  `loader.mapping_strategy = LattesAdvisorshipMappingStrategy(json_name)` and
  then calls `process_records`, exactly as `lattes/projects.py` already does with
  `LattesProjectMappingStrategy`.
- The task keeps an optional `project_loader=None` parameter and builds its own
  loader when called alone (scripts and tests), mirroring
  `ingest_file_task` in `lattes/projects.py`.

**Rationale**:
- `ProjectLoader` only reads `self.mapping_strategy` at row-mapping time
  (`_process_row`, plus a tracking reason string), so swapping it between CVs
  is safe.
- Its initiative and person maps are mutated in place as rows are created
  (comment in `project_loader.py`), so later CVs see earlier CVs' records. That
  is acceptance scenario 2.2.
- Profiled cost avoided: ~5.8 s per CV (`_ensure_existing_initiatives` and
  `preload_cache`).

**Alternatives considered**:
- *Keeping per-CV loaders but sharing the caches.* Rejected: more surface, and
  identical in effect to reusing the loader.

## R8. Observability (FR-013, FR-014)

**Decision**:
- `TeamSynchronizer` keeps counters: `loaded`, `hits`, `created`, `refreshes`,
  `refresh_found`, `failed`. It exposes `log_lookup_summary(label)`, which emits
  one INFO line.
- The line is emitted at the end of each loader's work:
  - the `sigpesq` projects task and advisorships task (two lines in the `sigpesq`
    phase, one per loader);
  - the `lattes_projects` flow;
  - the `lattes_advisorships` flow.
- Each Lattes CV loop logs, at INFO, the CV's position, its Lattes ID and its
  elapsed seconds.

**Rationale**:
- The counters make FR-004 observable: did refreshes ever find a team created
  elsewhere?
- The per-CV durations make SC-003 checkable from the run log alone.
- The CV is identified by its Lattes ID and position, not by the file name,
  because file names embed the person's name. That keeps new log lines at the
  minimum personal data (constitution V).
- The spec's "one line per phase" is met per loader. `sigpesq` has two loaders,
  so it emits two lines (labelled `sigpesq_projects`, `sigpesq_advisorships`).
  Each line is self-contained, and merging them would need cross-task state for
  no diagnostic gain.

## R9. Risk: Prefect parameter resolution overhead in the Lattes CV loops

**Finding**:
- In the `lattes_projects` profile, `prefect.task_engine._resolve_parameters` /
  `visit_collection` cost ~1 s per CV.
- The cause is that Prefect walks the `researcher_index` list (~7 600 entries) on
  every task call.
- Over ~435 CVs that is ~4–7 min per Lattes phase, outside the profiler. That is
  meaningful against the 20-minute targets (SC-001, SC-002).

**Decision**:
- Not part of the two mandatory changes.
- It is a **conditional task**: after the first post-change timing run, if
  either Lattes phase exceeds ~15 min, wrap the large parameters with
  `prefect.utilities.annotations.quote(...)`. Prefect then passes them through
  without traversal.
- The change stays in the ETL flows (no library change).

**Rationale**: Measure first. The other costs drop by orders of magnitude, and
this one may stay within budget.

## R10. How equivalence is proven (SC-004)

**Decision**:
- A controlled replay, as clarified on 2026-10-22, with the procedure in
  [quickstart.md](quickstart.md).
- Persistence runs against frozen inputs inside a throwaway Prefect flow, so
  constitution III holds and the source portals are not contacted:
  - `persist_research_groups`, `persist_projects` and `persist_advisorships`,
    from the same `data/raw/sigpesq/` files;
  - then the two Lattes flows, from a snapshot taken just before
    `lattes_projects`, on the same `data/lattes_json/`.
- Each step is run once on the base commit and once on the feature branch, and
  the results are compared.
- Comparison: entity counts plus name-based link sets (initiative ↔ team, and
  team ↔ person ↔ role). Names are used instead of ids because ids may shift if
  creation order changes.

**Rationale**: A full `make weekly-flows` re-downloads all sources, so its
inputs differ between runs and cannot isolate the code change.

## R11. Memory and scale

The lookup holds about 11 000 `(key, TeamRef)` pairs today, around a few MB, and
scales linearly. Per-record cost is constant: one normalisation, one dictionary
probe, and at most one primary-key range read on a miss. The edge case "large
registers" is therefore satisfied without further design.
