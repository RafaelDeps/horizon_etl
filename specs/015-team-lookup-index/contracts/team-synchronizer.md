# Contract: `TeamSynchronizer` and the Lattes advisorships task

This feature exposes no external API, CLI or file format. The contract below is
the **internal interface** that other ETL code and the tests rely on. The
`synchronize_members` signature and behaviour are unchanged.

## `TeamSynchronizer.__init__(team_controller, roles_cache)`

Unchanged signature. It MUST NOT read the database. The lookup is built on the
first `ensure_team` call.

## `TeamSynchronizer.ensure_team(team_name: str, description: str) -> Optional[TeamRef]`

| Aspect | Contract |
|---|---|
| Match | Returns the lowest-id team whose `normalize_text(name)` equals `normalize_text(team_name)`. That covers exact matches. |
| Miss | **sql** mode: one incremental read of teams with `id > max_id` first. **controller** mode: no extra read. If it still misses: `team_controller.create_team(name=team_name, description=description)` (same arguments as today), then the new team is added to the lookup. |
| Return | A `TeamRef(id, name)` on hit or creation; `None` if creation raises. |
| Errors | Never raises. Failures are logged at WARNING with the same message as today: `Failed to manage team '<name[:50]>': <error>`. |
| Logs | `Created team: <name[:50]>...` at INFO on creation (unchanged). No per-lookup lines. |
| Reads per call | Steady state: zero queries on a hit; at most one primary-key range query on a miss. A full read of `id, name` happens at most once per instance (FR-001). |

## `TeamSynchronizer.log_lookup_summary(label: str) -> None`

Emits exactly one INFO line:

```text
Team lookup [<label>]: loaded=<n> hits=<n> created=<n> refreshes=<n> refresh_found=<n> failed=<n>
```

If the lookup was never built, all counters are 0.

## `ingest_advisorships_file_task(file_path, researcher_index, project_loader=None)` (`src/flows/lattes/advisorships.py`)

| Aspect | Contract |
|---|---|
| `project_loader` given | Reused. Its `mapping_strategy` is set to `LattesAdvisorshipMappingStrategy(<supervisor name>)` before `process_records`. |
| `project_loader` omitted | Builds its own `ProjectLoader`, which is today's behaviour, for standalone callers. |
| Other behaviour | Unchanged: supervisor resolution, skip rules, parsing and `source_file` passed to `process_records`. |

## `ingest_lattes_advisorships_flow()`

- Builds exactly one `ProjectLoader` per run (FR-008) and passes it to every
  task call.
- Logs each CV's duration at INFO (FR-014).
- Calls `log_lookup_summary("lattes_advisorships")` once at the end (FR-013).

## `ingest_lattes_projects_flow()` and the SigPesq persist tasks

- Loader construction is unchanged.
- Add `log_lookup_summary(...)` at the end, with labels `lattes_projects`,
  `sigpesq_projects` and `sigpesq_advisorships`.
- The Lattes projects loop adds the per-CV INFO duration line.
