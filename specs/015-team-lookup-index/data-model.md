# Data Model: Team Lookup Index

**Feature**: [spec.md](spec.md) · **Research**: [research.md](research.md)

There is no database schema change. Everything below is an in-memory,
ETL-only transient structure (constitution II: no new domain concept; `Team`
stays owned by `eo_lib` / `research_domain`).

## Persistent entities read (unchanged)

| Table | Columns used | Notes |
|---|---|---|
| `teams` | `id`, `name` | Includes research groups: `research_groups.id` → `teams.id` (joined-table inheritance). |

Columns written: none beyond what `TeamController.create_team(name, description)`
already writes.

## TeamRef

An immutable reference returned by `TeamSynchronizer.ensure_team`.

| Field | Type | Rule |
|---|---|---|
| `id` | `int` | Primary key of `teams`. Always set. |
| `name` | `str` | The team's stored name, verbatim (not normalised). `""` if the row has `NULL`. |

Callers MUST use only `id` and truthiness (FR-006). A `TeamRef` is always truthy.

## TeamLookup state (held by `TeamSynchronizer`)

| Field | Type | Meaning |
|---|---|---|
| `by_key` | `dict[str, TeamRef]` | `normalize_text(name)` → the team with the **lowest id** carrying that key (FR-002, FR-003). |
| `max_id` | `int` | Highest `teams.id` merged so far. `0` when the register is empty. |
| `loaded` | `bool` | `False` until the first `ensure_team` call builds the lookup. |
| `mode` | `"sql"` \| `"controller"` | `"sql"` when the controller exposes a real SQLAlchemy `Session`; `"controller"` otherwise (single `get_all()`, no incremental reads). |
| `stats` | counters | `loaded`, `hits`, `created`, `refreshes`, `refresh_found`, `failed` (FR-013). |

### Invariants

1. Every value in `by_key` refers to a row that existed in `teams` when it was
   merged.
2. `by_key` is only written by `merge(rows)` and by successful creation.
   `merge` uses first-writer-wins, and rows arrive in ascending id, so a key
   never moves to a higher id.
3. `max_id` only increases.
4. A failed creation changes neither `by_key` nor `max_id` (FR-005).

### State transitions of one `ensure_team(name, description)` call

```text
                 ┌──────────────┐
  first call ──▶ │ load (once)  │  sql: SELECT id,name FROM teams ORDER BY id
                 └──────┬───────┘  controller: get_all(), sorted by id
                        ▼
              key = normalize_text(name)
                        │
             ┌──────────┴──────────┐
         key in by_key          key missing
             │                      │
        hits += 1         mode == "sql"?  ── no ──┐
        return ref               │ yes            │
                       refreshes += 1             │
                       SELECT id,name FROM teams  │
                       WHERE id > max_id          │
                       ORDER BY id → merge        │
                                 │                │
                     ┌───────────┴────────┐       │
                 now found            still missing◀┘
                     │                     │
           refresh_found += 1       create_team(name, description)
           return ref                ┌──────┴───────┐
                                  success         raises
                                     │              │
                          merge created row   failed += 1, log warning
                          created += 1        lookup unchanged
                          return TeamRef      return None
```

## ProjectLoader reuse in `lattes_advisorships` (FR-008)

| Before | After |
|---|---|
| One `ProjectLoader(LattesAdvisorshipMappingStrategy(name))` per CV. Each one reloads initiatives, persons and roles and builds its own synchroniser and team lookup. | One `ProjectLoader(mapping_strategy=None)` per phase. Before each CV's `process_records`, set `loader.mapping_strategy = LattesAdvisorshipMappingStrategy(name)`. Caches and the team lookup live for the whole phase. |

## Log records (FR-013, FR-014)

**Summary**: one per loader, INFO level.

```text
Team lookup [<label>]: loaded=<n> hits=<n> created=<n> refreshes=<n> refresh_found=<n> failed=<n>
```

`<label>` is one of `sigpesq_projects`, `sigpesq_advisorships`, `lattes_projects`
or `lattes_advisorships`.

**Per CV**: one per CV, INFO level, Lattes phases only.

```text
Lattes <phase> CV <i>/<total> lattes_id=<id> took <seconds>s
```

These lines contain no person names, CPF, phone numbers or e-mails
(constitution V).
