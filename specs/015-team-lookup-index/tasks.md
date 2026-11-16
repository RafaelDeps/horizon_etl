---

description: "Task list for the team lookup index feature"
---

# Tasks: Team Lookup Index for the Lattes Ingestion Phases

**Input**: Design documents from `specs/015-team-lookup-index/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/team-synchronizer.md](contracts/team-synchronizer.md), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (FR-012, SC-006). Test tasks come before the implementation tasks in each story and must fail before the implementation lands.

**Organization**: Tasks are grouped by user story (US1 = team lookup, US2 = one `ProjectLoader` for advisorships, US3 = the weekly run fits in CI).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: The user story the task belongs to (US1, US2, US3)
- `$REPLAY` is a scratch directory **outside the repository** (for example `/tmp/replay-015`). Nothing under it is committed.
- **Base** means the code before this feature's changes (the branch tip before T008).
- **Feature** means the code with this feature's changes.

---

## Phase 1: Setup (replay baseline, captured before any code change)

**Purpose**: Freeze the inputs and produce the **base** results that SC-004 compares against. This must run on the base code, so it comes first.

- [X] T001 Copy `data/raw/sigpesq/` and `data/lattes_json/` to `$REPLAY/inputs/`, and write `git rev-parse HEAD` plus `git status --short` to `$REPLAY/BASE.txt` (record of the base code, including the uncommitted ×10 timeouts in `src/flows/pipelines/weekly_orchestrator.py`).
- [X] T002 [P] Write `$REPLAY/replay_sigpesq.py`, a throwaway Prefect `@flow` with no Telegram hooks. It calls, in order, `persist_research_groups()` (`src/flows/sigpesq/groups.py`), `persist_projects()` (`src/flows/sigpesq/projects.py`) and `persist_advisorships()` (`src/flows/sigpesq/advisorships.py`) against the `DATABASE_URL` from the environment. It never calls `SigPesqAdapter.extract`, so the portal is not contacted (quickstart §2.2).
- [X] T003 [P] Write `$REPLAY/compare.py <a.db> <b.db>`. It opens both SQLite files read-only and runs the three query groups of quickstart §2.4: counts of teams, team_members, initiatives, initiative_teams, advisorships and persons; the (initiative name, team name) link set; and the (team name, person name, role name) membership set. It prints count deltas and the first 20 differing rows of each set, and exits 0 only if everything is identical.
- [X] T004 Build the pre-Lattes snapshot with the **base** code. Run `make db-reset`. With `data/raw/sigpesq/` restored from `$REPLAY/inputs/`, run `$REPLAY/replay_sigpesq.py`, then `.venv/bin/python app.py cnpq_sync`. Copy the DB with the SQLite backup API to `$REPLAY/pre_lattes.db` (depends on T001, T002).
- [X] T005 Produce the **base** replay results:
  - SigPesq: `make db-init` on a fresh `DATABASE_URL=sqlite:///$REPLAY/base_sigpesq.db`, then `$REPLAY/replay_sigpesq.py`.
  - Lattes: copy `$REPLAY/pre_lattes.db` to `$REPLAY/base_lattes.db`, and with `DATABASE_URL` pointing at it and `data/lattes_json/` restored from `$REPLAY/inputs/`, run `.venv/bin/python app.py ingest_lattes_projects` and then `.venv/bin/python app.py lattes_advisorships`.
  - Record both phase durations in `$REPLAY/BASE.txt` (depends on T004).

**Checkpoint**: The base results exist. Code changes may start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None beyond Phase 1. The feature changes existing modules and adds no shared infrastructure. US1 and US2 touch different files and can start in parallel once Phase 1 is done.

---

## Phase 3: User Story 1 - Team matching stops re-reading the whole team register per record (Priority: P1) 🎯 MVP

**Goal**: `TeamSynchronizer.ensure_team` answers from a lookup built once per synchroniser (`SELECT id, name FROM teams ORDER BY id`, keyed by `normalize_text`, lowest id first). On a miss it refreshes incrementally (`id > max_id`) before creating. It returns a `TeamRef` and reports a per-loader summary. This applies in `sigpesq`, `lattes_projects` and `lattes_advisorships`.

**Independent Test**: The unit tests below pass, and the SigPesq controlled replay (T017) is identical to `$REPLAY/base_sigpesq.db`.

### Tests for User Story 1 ⚠️ (write first; they must fail before T008–T011)

- [X] T006 [P] [US1] In `tests/test_team_synchronizer.py`, add controller-mode tests: a fake `TeamController` with no SQLAlchemy session, exposing `get_all()` and `create_team()`. Cover:
  - an exact-name hit returns that team's id and `create_team` is not called;
  - `"Conecta Fapes"` matches a stored `"Conecta FAPES"`;
  - with stored teams `(7, "Projeto X")` and `(3, "PROJETO X")`, a lookup of `"projeto x"` returns id 3;
  - a miss calls `create_team(name=..., description=...)` with today's arguments, and the next lookup of an equivalent name returns the created id without creating again;
  - when `create_team` raises, `None` is returned and a later lookup of the same name calls `create_team` again;
  - `get_all()` is called exactly once across 50 `ensure_team` calls;
  - the returned object is a `TeamRef` exposing `.id` and `.name`.

  Keep `test_ensure_team_matches_canonical_name` unchanged.
- [X] T007 [P] [US1] Create `tests/test_team_lookup_sql.py` for sql mode: a real in-memory SQLAlchemy `Session` (`create_engine("sqlite://")`) with a minimal `teams(id INTEGER PRIMARY KEY, name TEXT)` table, attached to a fake controller as `_service._repository._session`. The fake `create_team` inserts and commits a row. Cover:
  - the initial load reads all ids and names once;
  - a row inserted directly into `teams` (simulating a research group created elsewhere) after the first lookup is found by the incremental refresh, so no `create_team` call and `refresh_found == 1`;
  - after creation, the next lookup is a hit with no extra SQL range read (count the statements with an `after_cursor_execute` event listener);
  - `log_lookup_summary("x")` emits exactly one line, `Team lookup [x]: loaded=.. hits=.. created=.. refreshes=.. refresh_found=.. failed=..`, with the expected counters (capture with a loguru sink).

### Implementation for User Story 1

- [X] T008 [US1] In `src/core/logic/team_synchronizer.py`:
  - add a frozen `@dataclass TeamRef(id: int, name: str)`;
  - add lookup state to `TeamSynchronizer.__init__`, with no database access: `_by_key: dict[str, TeamRef]`, `_max_id = 0`, `_loaded = False`, `_mode: Optional[str] = None`, and `_stats` with the counters `loaded`, `hits`, `created`, `refreshes`, `refresh_found` and `failed` (data-model.md, "TeamLookup state").
- [X] T009 [US1] In `src/core/logic/team_synchronizer.py`, add four private methods (research.md R2, R3, R5):
  - `_session()`: return `team_controller._service._repository._session` only if it is an instance of `sqlalchemy.orm.Session`, else `None`; guard attribute errors.
  - `_merge(rows)`: iterate rows in ascending id; `setdefault(normalize_text(name), TeamRef(id, name or ""))`; advance `_max_id`.
  - `_load()`:
    - sql mode: `session.execute(text("SELECT id, name FROM teams ORDER BY id"))`;
    - controller mode: a single `get_all()`, sorted by `id`, reading `.name` or `dict["name"]` exactly as the current loop does.
  - `_refresh()`: sql mode only, `SELECT id, name FROM teams WHERE id > :max_id ORDER BY id`; returns the number of rows merged.

  Depends on T008.
- [X] T010 [US1] Rewrite `TeamSynchronizer.ensure_team` in `src/core/logic/team_synchronizer.py` per contracts/team-synchronizer.md:
  1. load on first call;
  2. probe `normalize_text(team_name)` → on a hit, `hits += 1` and return the `TeamRef`;
  3. on a miss in sql mode, `_refresh()` and probe again → on a hit, `refresh_found += 1`;
  4. still missing → `create_team(name=team_name, description=description)`, merge the created row, `created += 1`, and return its `TeamRef`.

  On an exception, keep the exact warning `Failed to manage team '<name[:50]>': <e>`, `failed += 1`, return `None`, and leave `_by_key` and `_max_id` untouched. Keep the `Created team: ...` INFO line and remove the per-lookup DEBUG line. Depends on T009.
- [X] T011 [US1] Add `TeamSynchronizer.log_lookup_summary(label: str)` in `src/core/logic/team_synchronizer.py`. It emits one INFO line in the data-model.md format and all-zero counters if the lookup was never built. Depends on T008.
- [X] T012 [P] [US1] In `src/flows/sigpesq/projects.py`, call `loader.team_synchronizer.log_lookup_summary("sigpesq_projects")` at the end of `persist_projects()`, after `loader.process_file(...)` and inside the same path where `loader` exists. Depends on T011.
- [X] T013 [P] [US1] In `src/flows/sigpesq/advisorships.py`, call `loader.team_synchronizer.log_lookup_summary("sigpesq_advisorships")` at the end of `persist_advisorships()`, after the loader finishes processing. Depends on T011.
- [X] T014 [US1] In `src/flows/lattes/projects.py`, inside `ingest_lattes_projects_flow` (the loop over `json_files` near line 939):
  - before each CV, take `time.perf_counter()`;
  - after `ingest_researcher_data(...)`, `_expire_lattes_sessions(session)` and `gc.collect()`, log at INFO `Lattes lattes_projects CV <i>/<total> lattes_id=<id> took <s>s`, with the Lattes ID parsed from the file name the same way as `ingest_advisorships_file_task` (`basename(...).replace(".json", "").split("_")[-1]`). Never log the file name (FR-014, constitution V);
  - after the loop, call `project_loader.team_synchronizer.log_lookup_summary("lattes_projects")`.

  Depends on T011.
- [X] T015 [US1] Run `.venv/bin/python -m pytest -q tests/test_team_synchronizer.py tests/test_team_lookup_sql.py tests/test_team_management.py tests/test_ingest_lattes_projects_flow.py`. All must pass, including the unchanged `test_ensure_team_matches_canonical_name` and `test_create_initiative_team_idempotent` (FR-007). Depends on T006, T007, T010–T014.
- [X] T016 [US1] Feature replay for SigPesq. Run `make db-init` on a fresh `DATABASE_URL=sqlite:///$REPLAY/feature_sigpesq.db`, run `$REPLAY/replay_sigpesq.py` with the feature code and `data/raw/sigpesq/` from `$REPLAY/inputs/`, then run `$REPLAY/compare.py $REPLAY/base_sigpesq.db $REPLAY/feature_sigpesq.db`. It must exit 0. Save the two `Team lookup [sigpesq_*]` lines. Depends on T005, T015.

**Checkpoint**: Team matching uses the lookup everywhere, and SigPesq persistence is proven identical.

---

## Phase 4: User Story 2 - Advisorships phase reuses one project loader for all CVs (Priority: P2)

**Goal**: `ingest_lattes_advisorships_flow` builds one `ProjectLoader(mapping_strategy=None)` per run and swaps in `LattesAdvisorshipMappingStrategy(<supervisor>)` for each CV, as `lattes_projects` does with `LattesProjectMappingStrategy`.

**Independent Test**: The flow test (T017) passes, proving one loader per run and a per-CV strategy, and the Lattes replay (T021) is identical to the base.

### Tests for User Story 2 ⚠️ (write first)

- [X] T017 [P] [US2] Create `tests/test_lattes_advisorships_loader_reuse.py`:
  - **Flow run:** patch `src.flows.lattes.advisorships.ProjectLoader`, `load_researcher_index`, `resolve_researcher_from_lattes` (returning a supervisor with a distinct `.name` per CV), `ResearcherController` and `LattesParser.parse_advisorships` (non-empty). Write 3 CV JSON files named `<n>_<Name>_<16digits>.json` to `tmp_path`, `chdir` there so `data/lattes_json/` is found, and call the flow's underlying function (`ingest_lattes_advisorships_flow.fn`).
  - **Assertions:** `ProjectLoader` is constructed exactly once; `process_records` is called 3 times; before each call, `mapping_strategy` is a `LattesAdvisorshipMappingStrategy` built with that CV's supervisor name; `team_synchronizer.log_lookup_summary` is called once with `"lattes_advisorships"`.
  - **Standalone call:** calling `ingest_advisorships_file_task` directly without `project_loader` builds its own loader.

### Implementation for User Story 2

- [X] T018 [US2] In `src/flows/lattes/advisorships.py`, add `project_loader: Optional[ProjectLoader] = None` to `ingest_advisorships_file_task`. In step 3, if a loader is given, set `project_loader.mapping_strategy = LattesAdvisorshipMappingStrategy(json_name)` and call `project_loader.process_records(advisorships, source_file=file_path)`. Otherwise keep today's behaviour (`ProjectLoader(mapping_strategy=...)`). Supervisor resolution, skip rules and parsing stay unchanged.
- [X] T019 [US2] In `ingest_lattes_advisorships_flow` (`src/flows/lattes/advisorships.py`):
  - before the loop, build one `ProjectLoader(mapping_strategy=None)` (import `ProjectLoader` from `src.core.logic.project_loader`);
  - pass it to every `ingest_advisorships_file_task(json_file, researcher_index, project_loader)` call;
  - around each call, log at INFO `Lattes lattes_advisorships CV <i>/<total> lattes_id=<id> took <s>s` (Lattes ID from the file name, never the file name itself);
  - after the loop, call `project_loader.team_synchronizer.log_lookup_summary("lattes_advisorships")`.

  Depends on T018.
- [X] T020 [US2] Run `.venv/bin/python -m pytest -q tests/test_lattes_advisorships_loader_reuse.py tests/test_team_synchronizer.py tests/test_team_lookup_sql.py`. All must pass. Depends on T017, T019 (and T010 for the synchroniser).
- [X] T021 [US2] Feature replay for Lattes:
  1. Copy `$REPLAY/pre_lattes.db` to `$REPLAY/feature_lattes.db`.
  2. With `DATABASE_URL` pointing at it and `data/lattes_json/` from `$REPLAY/inputs/`, run `.venv/bin/python app.py ingest_lattes_projects` and then `.venv/bin/python app.py lattes_advisorships` with the feature code, teeing both runs' output to `$REPLAY/feature_lattes.log`.
  3. Run `$REPLAY/compare.py $REPLAY/base_lattes.db $REPLAY/feature_lattes.db`. It must exit 0.
  4. Record both phase durations against `$REPLAY/BASE.txt`.

  Depends on T005, T016, T020.

**Checkpoint**: Both Lattes phases use the lookup and a single loader, and their results are proven identical to the base.

---

## Phase 5: User Story 3 - The weekly run fits in CI (Priority: P3)

**Goal**: Confirm the end-to-end outcome on a full `make weekly-flows`: SC-001, SC-002, SC-003 and SC-005.

**Independent Test**: The full local run exits 0 on every phase and meets the timing criteria, measured from its own log.

- [X] T022 [US3] Run `make weekly-flows > logs/weekly_015_validation.log 2>&1` (run it in the background; it takes hours). Extract:
  - every phase's duration from the `=== Weekly pipeline summary ===` block and the `▶ phase` / `finished` lines;
  - the four `Team lookup [...]` lines;
  - SC-003: the mean of the first 50 and of the last 50 `Lattes lattes_advisorships CV i/N ... took Xs` lines.

  Pass when:
  - `lattes_projects` < 20 min;
  - `lattes_advisorships` < 20 min;
  - last-50 / first-50 ≤ 1.5;
  - the total is < 4 h 02 min;
  - all 19 phases exit 0.

  Depends on T021.
- [ ] T023 [US3] **DEFERRED to the next spec (TD-013), by maintainer decision on 2026-10-22; condition was met (Lattes phases 33 and 48 min).** Conditional (research.md R9). Only if T022 shows `lattes_projects` or `lattes_advisorships` above ~15 min: in `src/flows/lattes/projects.py` and `src/flows/lattes/advisorships.py`, wrap the large task arguments with `prefect.utilities.annotations.quote(...)`, so Prefect stops traversing them: `researcher_index`, and `project_loader` / `entity_manager` where passed. Re-run T015 and T020, then repeat T022. Otherwise mark the task as not needed and record the measured durations.
- [X] T024 [US3] Write `docs/reports/2026-10-<dd>-team-lookup-validation.md` in English:
  - base vs feature replay results (T016, T021), with the `compare.py` output summary;
  - full-run phase table vs the 2026-10-22 baseline (T022);
  - the four lookup summary lines;
  - the SC-003 computation;
  - whether T023 was needed;
  - every difference found, with its cause.

  Depends on T022 (and T023 if run).

**Checkpoint**: All success criteria are verified and documented.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T025 Run `make ci-check` (flake8, black, isort, mypy, pytest) and fix anything it reports in the touched files: `src/core/logic/team_synchronizer.py`, `src/flows/lattes/projects.py`, `src/flows/lattes/advisorships.py`, `src/flows/sigpesq/projects.py`, `src/flows/sigpesq/advisorships.py` and the three test files (SC-006).
- [X] T026 [P] Update `docs/backlog.md`:
  - add a resolved entry for the team-lookup quadratic cost (link spec 015 and the T024 report);
  - add follow-ups: revisit the ×10 phase ceilings in `src/flows/pipelines/weekly_orchestrator.py` using the T022 durations; make the CNPq phase concurrent; report the `lazy="joined"` collections on `Team.members` / `TeamMember.person` upstream to `eo_lib`, in the style of TD-009.
- [X] T027 [P] Update `docs/flows-and-entrypoints.md` (or the closest existing operations doc) with one paragraph on the new `Team lookup [...]` and per-CV log lines: what each counter means and how to read SC-003 from a run log.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: runs first, on the base code. T002 and T003 can run in parallel; T004 needs T001 and T002; T005 needs T003 and T004.
- **Foundational (Phase 2)**: empty.
- **US1 (Phase 3)**: needs Phase 1 only for its replay task (T016). The tests and implementation can start right after T001.
- **US2 (Phase 4)**: implementation (T017–T020) is independent of US1's files. Its replay (T021) needs US1 complete (T016), because the Lattes replay must run the full feature code.
- **US3 (Phase 5)**: needs US1 and US2.
- **Polish (Phase 6)**: T025 after all code tasks; T026 and T027 after T024.

### User Story Dependencies

- **US1 (P1)**: no dependency on other stories. It is the MVP and removes most of the 333 min.
- **US2 (P2)**: its code and tests are independent of US1. Its replay validation runs on top of US1.
- **US3 (P3)**: verification only; depends on US1 and US2.

### Within Each User Story

- Tests are written first and must fail (T006, T007 before T008–T011; T017 before T018–T019).
- In US1: T008 → T009 → T010; T011 after T008; T012, T013 and T014 after T011.
- Replays only after the story's tests pass.

### Parallel Opportunities

- T002 ∥ T003 (separate scratch scripts).
- T006 ∥ T007 (separate test files).
- T012 ∥ T013 (separate SigPesq flow files).
- The US2 tests and implementation (T017–T019) ∥ the US1 implementation (T008–T014): different files.
- T026 ∥ T027 (separate docs).

---

## Parallel Example: User Story 1

```bash
# Tests first, in parallel (different files):
Task: "Controller-mode lookup tests in tests/test_team_synchronizer.py"   # T006
Task: "SQL-mode lookup tests in tests/test_team_lookup_sql.py"           # T007

# After T011, summary hooks in parallel (different files):
Task: "Lookup summary in src/flows/sigpesq/projects.py"                  # T012
Task: "Lookup summary in src/flows/sigpesq/advisorships.py"              # T013
```

## Parallel Example: User Story 2 (alongside US1)

```bash
Task: "Loader-reuse flow test in tests/test_lattes_advisorships_loader_reuse.py"  # T017
# while US1 works on src/core/logic/team_synchronizer.py (T008–T011)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: freeze the inputs and produce the base results (T001–T005).
2. Phase 3: lookup tests → implementation → SigPesq replay identical (T006–T016).
3. **Stop and validate**: US1 alone removes the per-record full read in every phase. Optionally run the Lattes replay at this point to see the gain before US2.

### Incremental Delivery

1. US1 → SigPesq replay identical → MVP.
2. US2 → Lattes replay identical, with both phases timed.
3. US3 → full weekly run, success criteria report, and R9 only if needed.
4. Polish → `make ci-check`, backlog and docs.

---

## Notes

- Never modify `eo_lib`, `research_domain`, `libbase`, `dgp_cnpq_lib` or any other installed library (FR-010).
- Do not change the phase timeouts in `src/flows/pipelines/weekly_orchestrator.py` in this feature (spec assumptions).
- Do not touch Docker (rebuild or compose changes) as part of these tasks.
- Replay scripts and DB snapshots live in `$REPLAY` and are never committed.
- New log lines must not contain person names, file names that embed names, CPF, phone numbers or e-mails.
