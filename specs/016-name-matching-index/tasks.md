---

description: "Task list for the name-matching index feature"
---

# Tasks: Name-Matching Index for Persons and Researchers

**Input**: Design documents from `specs/016-name-matching-index/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/name-matching.md](contracts/name-matching.md), [quickstart.md](quickstart.md)

**Tests**: Requested by the spec (FR-013, SC-006). Test tasks come first in each story and must fail before the implementation.

**Organization**: Tasks are grouped by user story:
- **US1**: `PersonMatcher` index and fuzzy call;
- **US2**: researcher resolution;
- **US3**: Prefect `quote`;
- **US4**: time targets.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: The user story the task belongs to (US1–US4)
- `$REPLAY` is the spec 015 replay directory **outside the repository**, currently `/tmp/claude-1000/-home-rafael-horizon-etl/326c8482-b2cb-4ce7-918a-b95d4469a905/scratchpad/replay`. It holds `inputs/`, `pre_lattes.db`, the references `feature_sigpesq.db` and `feature_lattes.db`, `prep_run.sh`, `env.sh`, `replay_sigpesq.py` and `compare.py`. Nothing under it is committed.

---

## Phase 1: Setup

**Purpose**: Confirm that the spec 015 replay assets still exist, and freeze the pre-016 algorithms as test oracles.

- [X] T001 Verify that `$REPLAY/feature_sigpesq.db`, `$REPLAY/feature_lattes.db`, `$REPLAY/pre_lattes.db`, `$REPLAY/inputs/sigpesq/` and `$REPLAY/inputs/lattes_json/` (435 files), plus `$REPLAY/compare.py`, `prep_run.sh`, `env.sh` and `replay_sigpesq.py`, all exist. If any reference database is missing, stop and report: the reference would have to be rebuilt with the spec 015 code (quickstart.md §2 depends on it).
- [X] T002 Create `tests/_name_matching_oracle.py`, holding **verbatim copies** of today's algorithms as frozen reference functions:
  - `oracle_normalised_exact(persons_cache, normalize, normalized_input)`: the step 2 loop of `PersonMatcher.match_or_create` in `src/core/logic/person_matcher.py`;
  - `oracle_fuzzy(persons_cache, normalize, normalized_input, strict_match)`: the step 3 dict comprehension plus `thefuzz.process.extractOne(..., scorer=fuzz.token_sort_ratio)` with the `>= 90` and strict `< 100` rules. Returns the original name or `None`, plus whether strict mode rejected;
  - `oracle_resolve_researcher_by_name(all_researchers, *, name, identification_id)`: the current body of `resolve_researcher_by_name` in `src/core/logic/researcher_resolution.py`, calling an **unmemoised** copy of `normalize_participant_name` (also copied verbatim from `src/core/logic/person_identity.py`).

  Add a module docstring stating that these copies must never be edited (spec 016).

**Checkpoint**: The reference exists and the oracles are frozen.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. US1, US2 and US3 touch different files, and each depends only on Phase 1.

---

## Phase 3: User Story 1 - Person matching stops re-normalising the whole cache per lookup (Priority: P1) 🎯 MVP

**Goal**: `PersonMatcher` keeps `_first_by_norm`, `_last_by_norm`, `_fuzzy_keys` and `_fuzzy_processed` in step with `_persons_cache` through a single `_cache_name` writer. Step 2 and step 3 read them. Step 3 calls `rapidfuzz.process.extractOne` on pre-processed candidates with `score_cutoff=89.5`. Counters and `log_match_summary` are added. See data-model.md.

**Independent Test**: `tests/test_person_matcher_index.py` passes under both rapidfuzz implementations, and the SigPesq replay (T012) is identical to `$REPLAY/feature_sigpesq.db`.

### Tests for User Story 1 ⚠️ (write first; they must fail before T006–T009)

- [X] T003 [P] [US1] Create `tests/test_person_matcher_index.py`. Use a `PersonMatcher` with a fake `person_controller` (`get_all()` returning objects with `.name` and empty `.emails`; `create_person(name, emails)` returning a new object with an incrementing `.id`). Cover:
  - **Normalised exact:** after a preload with `["José da Silva", "JOSE DA SILVA", "Maria Souza"]`, `match_or_create("jose  da   silva")` returns the same person as `oracle_normalised_exact`, the first raw name in order. Patch `PersonMatcher.normalize_name` with a counting wrapper and assert the cached names are not re-normalised: the count does not grow with the cache size.
  - **Re-registered raw name:** a name already in `_persons_cache` is re-assigned to another person. The order is unchanged, and the next normalised hit returns the current value, as the oracle does.
  - **Creation and match registration:** a person created by one call, or a new spelling registered by a step 1.5/2/2.5 hit, is found by a later call with an equivalent spelling.
  - **Fuzzy view:** a fixture where two raw names share a normalised key with a third key in between. Assert `matcher._fuzzy_keys` equals `list({norm(n): n for n in cache})`, and `_last_by_norm` equals that comprehension's values.
  - **Fuzzy decision:** for at least 2 000 generated queries (dropped token, deleted character, shuffled tokens, nonsense, empty after processing) over a cache of at least 3 000 synthetic Brazilian-style names, the new `match_or_create` returns the same person as the oracle-driven expectation, in normal and strict mode.
  - **Counters:** `log_match_summary("x")` emits one INFO line, `Person matching [x]: email=.. canonical=.. exact=.. normalised=.. invariant=.. fuzzy=.. strict_rejected=.. created=.. create_failed=..`, with the expected counts. Capture it with a loguru sink.
  - **Preload reset:** a second `preload_cache()` rebuilds every derived structure from scratch.
- [X] T004 [P] [US1] In `tests/test_person_matcher_index.py`, add a test that re-runs the fuzzy-decision case in a subprocess with `RAPIDFUZZ_IMPLEMENTATION=python`, using `subprocess.run([sys.executable, "-c", ...], env=...)`. The variable is read at import, so a subprocess is required. The test asserts 0 mismatches against the oracle (FR-010).

### Implementation for User Story 1

- [X] T005 [US1] In `src/core/logic/person_matcher.py`, add in `__init__`:
  - `_first_by_norm: Dict[str, str]`;
  - `_last_by_norm: Dict[str, str]`;
  - `_fuzzy_keys: List[str]`;
  - `_fuzzy_processed: List[str]`;
  - `_stats` with keys `email`, `canonical`, `exact`, `normalised`, `invariant`, `fuzzy`, `strict_rejected`, `created` and `create_failed`.

  Add `_cache_name(self, raw: str, person) -> None`:
  - if `raw not in self._persons_cache`: `k = self.normalize_name(raw)`; `self._first_by_norm.setdefault(k, raw)`; if `k` is not yet in `_last_by_norm`, append `k` to `_fuzzy_keys` and `utils.full_process(k, force_ascii=True)` (from `thefuzz`) to `_fuzzy_processed`; then `self._last_by_norm[k] = raw`;
  - finally `self._persons_cache[raw] = person`.
- [X] T006 [US1] In `src/core/logic/person_matcher.py`, route every write to `_persons_cache` through `_cache_name`: `preload_cache` (reset the four structures together with `_persons_cache`), step 1.5, step 2, step 2.5, the fuzzy hit and creation. After this, `grep "_persons_cache\[" src/core/logic/person_matcher.py` must show writes only inside `_cache_name`. Depends on T005.
- [X] T007 [US1] Rewrite step 2 in `match_or_create`: `raw = self._first_by_norm.get(normalized_input)`; if `raw is not None`, `person = self._persons_cache[raw]`, and keep today's side effects in the same order (`self._cache_name(name, person)`, `self._register_email(email, person)`) and `_stats["normalised"] += 1`. Add the counter increments for steps 1, 1.5, 1.6 and 2.5. Depends on T006.
- [X] T008 [US1] Rewrite step 3 in `match_or_create`:
  - when `self._fuzzy_keys and normalized_input`: `q = utils.full_process(normalized_input, force_ascii=True)`; if `q` is empty, skip, emitting the same warning thefuzz logs today if one is wanted; otherwise call `rapidfuzz.process.extractOne(q, self._fuzzy_processed, scorer=rapidfuzz.fuzz.token_sort_ratio, processor=None, score_cutoff=89.5)`;
  - if there is a result: `best_norm_match = self._fuzzy_keys[idx]`, `score = int(round(raw_score))`, and apply exactly today's `if score >= 90` / strict `< 100` logic and log messages (`Fuzzy match '...' ignored due to strict matching policy`, `Fuzzy match found: ...`);
  - on a hit, use `original_name = self._last_by_norm[best_norm_match]`;
  - count `fuzzy` and `strict_rejected`;
  - remove the `from thefuzz import fuzz, process` import if it becomes unused, and keep `from thefuzz import utils`.

  Depends on T007.
- [X] T009 [US1] In `src/core/logic/person_matcher.py`, count `created` and `create_failed` in step 4. Add `log_match_summary(self, label: str)`, which emits the single INFO line from data-model.md. Depends on T008.
- [X] T010 [P] [US1] In `src/flows/sigpesq/projects.py` and `src/flows/sigpesq/advisorships.py`, right after the existing `loader.team_synchronizer.log_lookup_summary(...)` line, add `loader.person_matcher.log_match_summary("sigpesq_projects")` and `loader.person_matcher.log_match_summary("sigpesq_advisorships")` respectively. Depends on T009.
- [X] T011 [US1] Run `.venv/bin/python -m pytest -q tests/test_person_matcher_index.py tests/test_team_management.py tests/test_project_loader_matching.py tests/test_sigpesq_advisorship_mapping.py`. Everything must pass. Depends on T003, T004, T009, T010.
- [X] T012 [US1] SigPesq replay:
  1. `D=$($REPLAY/prep_run.sh /home/rafael/horizon_etl s016_sigpesq); source $REPLAY/env.sh; export DATABASE_URL=sqlite:///$REPLAY/s016_sigpesq.db` (fresh file);
  2. from `$D`: `PYTHONPATH=$D .venv/bin/python db/create_db.py`, then `PYTHONPATH=$D .venv/bin/python $REPLAY/replay_sigpesq.py > $REPLAY/logs/s016_sigpesq.log 2>&1`;
  3. `.venv/bin/python -I $REPLAY/compare.py $REPLAY/feature_sigpesq.db $REPLAY/s016_sigpesq.db` must print `RESULT: IDENTICAL`.

  Save the `REPLAY ...s` timings and the two `Person matching [sigpesq_*]` lines. Depends on T011.

**Checkpoint**: Person matching uses the index everywhere, and SigPesq is proven identical.

---

## Phase 4: User Story 2 - Researcher resolution stops re-normalising every researcher per lookup (Priority: P2)

**Goal**: `normalize_participant_name` is memoised. `resolve_researcher_by_name` gains counters and `log_researcher_resolution_summary`. Its loop and scoring are untouched.

**Independent Test**: `tests/test_researcher_resolution_cache.py` passes, and the Lattes replay (T024) is identical.

### Tests for User Story 2 ⚠️ (write first)

- [X] T013 [P] [US2] Create `tests/test_researcher_resolution_cache.py`:
  - **Memoisation equivalence:** for at least 5 000 generated names (accents, particles, `Jr.`, punctuation, honorifics, `None`, non-str inputs such as `123`), and every flag combination (`canonical_particles` True/False, `canonical_suffixes` True/False, `drop_particles` True/False), `normalize_participant_name` equals the oracle copy from `tests/_name_matching_oracle.py`, including on repeated calls.
  - **Ties:** a fixture of `ResearcherRef` records where several candidates tie on score, so the first in order wins. `resolve_researcher_by_name` returns the same object (`is`) as `oracle_resolve_researcher_by_name`.
  - **Tiers:** one fixture per scoring tier (identification 200, exact casefold 150, normalised 100, invariant 90) and one with no match.
  - **Mixed types:** a list mixing `ResearcherRef` and plain objects with `.name` and `.identification_id`, mimicking ORM entities, returns the same as the oracle.
  - **Renames:** after mutating a candidate's `.name` (as `sync_researcher_ref` does), the result matches the oracle.
  - **Summary:** `log_researcher_resolution_summary("x")` emits one INFO line, `Researcher resolution [x]: lookups=.. tier200=.. tier150=.. tier100=.. tier90=.. unresolved=..`, with the expected counts, then resets them.

### Implementation for User Story 2

- [X] T014 [US2] In `src/core/logic/person_identity.py`, rename the current body to a private `_normalize_participant_name_uncached(text: str, canonical_particles, canonical_suffixes, drop_particles)` that receives `str(name)`. Wrap it with `functools.lru_cache(maxsize=262_144)`. Keep the public `normalize_participant_name(name, canonical_particles=True, canonical_suffixes=False, drop_particles=False)` with the same signature and docstring: it returns `""` for `None`, and otherwise calls the cached function with `str(name)` and the flags. Do not change `is_junk_name`.
- [X] T015 [US2] In `src/core/logic/researcher_resolution.py`, add module-level counters (`lookups`, `tier200`, `tier150`, `tier100`, `tier90`, `unresolved`) and `log_researcher_resolution_summary(label: str)`, which logs the INFO line from data-model.md and resets the counters. In `resolve_researcher_by_name`, without changing the loop, the scoring or the return value:
  - increment `lookups`;
  - when returning `None`, increment `unresolved`;
  - otherwise increment the tier of the **winner**: 200 if its identification matched; else 150 if its name matched case-insensitively; else 100 if its normalised name matched; else 90. Recompute the winner's name tier after the loop, for the winner only.

  Depends on T014.
- [X] T016 [US2] Run `.venv/bin/python -m pytest -q tests/test_researcher_resolution_cache.py tests/test_ingest_lattes_projects_flow.py tests/test_loader_mapping.py`. `test_loader_mapping.py::test_research_group_loader_mapping` fails before this change too (spec 015 report §6) and must not get worse. Depends on T013, T015.

**Checkpoint**: Researcher resolution no longer re-normalises names, and it is proven equivalent in unit tests.

---

## Phase 5: User Story 3 - Lattes CV tasks stop paying orchestration overhead on large inputs (Priority: P3)

**Goal**: Large per-CV task parameters are passed with `prefect.utilities.annotations.quote`, and both Lattes flows log the new summaries.

**Independent Test**: `tests/test_lattes_task_quoting.py` passes, and the existing Lattes flow tests still pass.

### Tests for User Story 3 ⚠️ (write first)

- [X] T017 [P] [US3] Create `tests/test_lattes_task_quoting.py`:
  - **Projects:** patch `src.flows.lattes.projects.ingest_researcher_data` with a `MagicMock`, and patch the controllers and loaders used by `ingest_lattes_projects_flow`: `InitiativeController`, `PersonController`, `EntityManager`, `LattesParser`, `ResearcherController`, `load_researcher_index`, `ProjectLoader`, `_resolve_sqlalchemy_engine`, `_expire_lattes_sessions`, `tracking_recorder.run_context`, and the `Base.metadata.create_all` call via `eo_lib.domain.base.Base`. Write two CV files under `tmp_path/data/lattes_json/`, `chdir` there, and call `ingest_lattes_projects_flow.fn()`. Assert that the `researcher_index`, `entity_manager`, `parser` and `project_loader` arguments of every call are `prefect.utilities.annotations.quote` instances whose `.unquote()` is the original object.
  - **Advisorships:** do the same for `ingest_lattes_advisorships_flow` with `ingest_advisorships_file_task`, checking `researcher_index` and `project_loader`. Reuse the patching approach of `tests/test_lattes_advisorships_loader_reuse.py`.
  - **Summaries:** both flows call `person_matcher.log_match_summary` and `log_researcher_resolution_summary` once with their phase label.

### Implementation for User Story 3

- [X] T018 [US3] In `src/flows/lattes/projects.py` (`ingest_lattes_projects_flow` loop):
  - change the call to `ingest_researcher_data(json_file, quote(entity_manager), quote(parser), quote(researcher_index), quote(project_loader))` (`from prefect.utilities.annotations import quote`);
  - after the existing `log_lookup_summary("lattes_projects")`, add `project_loader.person_matcher.log_match_summary("lattes_projects")` and `log_researcher_resolution_summary("lattes_projects")` (import from `src.core.logic.researcher_resolution`).
- [X] T019 [US3] In `src/flows/lattes/advisorships.py` (`ingest_lattes_advisorships_flow` loop):
  - change the call to `ingest_advisorships_file_task(json_file, quote(researcher_index), quote(project_loader))`;
  - after `log_lookup_summary("lattes_advisorships")`, add `project_loader.person_matcher.log_match_summary("lattes_advisorships")` and `log_researcher_resolution_summary("lattes_advisorships")`;
  - update `tests/test_lattes_advisorships_loader_reuse.py` only if its assertions read the raw arguments. The behaviour it checks (one loader, per-CV strategy) must stay the same.
- [X] T020 [US3] Run `.venv/bin/python -m pytest -q tests/test_lattes_task_quoting.py tests/test_lattes_advisorships_loader_reuse.py tests/test_ingest_lattes_projects_flow.py`. All must pass. Depends on T017–T019.

**Checkpoint**: All code changes are done, and every story's tests pass.

---

## Phase 6: User Story 4 - The Lattes phases meet their time targets (Priority: P4)

**Goal**: Prove SC-001–SC-005 with the controlled replay and a full timing run.

**Independent Test**: The replay comparison prints `IDENTICAL`, and the full-run log meets the timing criteria.

- [X] T021 [US4] Run `.venv/bin/black` and `.venv/bin/isort` on every touched file and new test file. Run `.venv/bin/flake8` on them and confirm that no warning is new compared with `git show HEAD:<file>` (spec 015 already accepted the E402 pattern of `src/flows/lattes/projects.py`).
- [X] T022 [US4] Run the full suite: `.venv/bin/python -m pytest -q tests --ignore=tests/integration -p no:cacheprovider`. Only the 6 pre-existing failures listed in `docs/reports/2026-10-22-team-lookup-validation.md` §6 may fail. Depends on T021.
- [X] T023 [US4] Re-run the SigPesq replay of T012 with the final code. It must still print `RESULT: IDENTICAL`. Depends on T022.
- [X] T024 [US4] Lattes replay:
  1. `D=$($REPLAY/prep_run.sh /home/rafael/horizon_etl s016_lattes); source $REPLAY/env.sh; cp $REPLAY/pre_lattes.db $REPLAY/s016_lattes.db; export DATABASE_URL=sqlite:///$REPLAY/s016_lattes.db`;
  2. from `$D`, time `PYTHONPATH=$D .venv/bin/python app.py ingest_lattes_projects` and `PYTHONPATH=$D .venv/bin/python app.py lattes_advisorships`, logging both to `$REPLAY/logs/s016_lattes_*.log`. Run them **in the background**: together they take tens of minutes;
  3. `.venv/bin/python -I $REPLAY/compare.py $REPLAY/feature_lattes.db $REPLAY/s016_lattes.db` must print `RESULT: IDENTICAL`.

  Record both durations against spec 015 (30.7 min and 47.4 min in its replay) and the summary lines. Depends on T023.
- [X] T025 [US4] Full timing run. Start it only if no full CNPq crawl ran in the previous few hours: the spec 015 validation got 85 connection resets that way. Run `make weekly-flows > logs/weekly_016_validation.log 2>&1` in the background, with `HORIZON_TELEGRAM_BOT_TOKEN=`, `TELEGRAM_BOT_TOKEN=`, `HORIZON_TELEGRAM_CHAT_ID=` and `TELEGRAM_CHAT_ID=` exported empty. From the log, extract:
  - each phase's duration;
  - the four `Person matching [...]` and two `Researcher resolution [...]` lines;
  - SC-003 (mean of the last 50 / first 50 `Lattes lattes_advisorships CV ... took Xs`).

  Pass when:
  - `lattes_projects` < 20 min;
  - `lattes_advisorships` < 20 min;
  - the ratio is ≤ 1.2;
  - the total excluding `cnpq` is < 104.5 min;
  - all phases exit 0.

  Depends on T024.
- [X] T026 [US4] Write `docs/reports/2026-10-<dd>-name-matching-validation.md` in English, in the same structure as `docs/reports/2026-10-22-team-lookup-validation.md`:
  - a success-criteria table;
  - the replay results (T012/T023, T024);
  - the full-run phase table against the spec 015 run;
  - the summary lines;
  - the SC-003 computation;
  - every difference found, with its cause;
  - the `RAPIDFUZZ_IMPLEMENTATION=fallback` finding (research.md R5).

  Depends on T025.

**Checkpoint**: All success criteria are verified and documented.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T027 [P] Update `docs/backlog.md`:
  - mark TD-013 as Fixed by spec 016, with a link to the T026 report;
  - add TD-017, "`RAPIDFUZZ_IMPLEMENTATION=fallback` is not a valid rapidfuzz value": only `cpp` / `python` are recognised, so the AVX2 workaround of commit `e0d137e` in `.github/workflows/weekly-etl.yml` has no effect. Leave the fix to the maintainer (`cpp` with SSE2, or `python`), noting the segfault history.
- [X] T028 [P] Update `docs/flows-and-entrypoints.md` (the "Team lookup and per-CV timing logs" subsection added by spec 015) with the `Person matching [...]` and `Researcher resolution [...]` lines and the meaning of each counter. Use real values from T025.
- [X] T029 Mark T001–T028 as done in this file, and set `specs/016-name-matching-index/spec.md` **Status** to `Implemented`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001, then T002.
- **Foundational (Phase 2)**: empty.
- **US1 (Phase 3)**, **US2 (Phase 4)** and **US3 (Phase 5)** can start after Phase 1. They touch different source files: `person_matcher.py`; `person_identity.py` and `researcher_resolution.py`; the Lattes flows. The one exception is T018/T019, which call the summary functions added by T009 and T015, so they come after those.
- **US4 (Phase 6)**: needs US1, US2 and US3 complete.
- **Polish (Phase 7)**: after T026.

### User Story Dependencies

- **US1 (P1)**: independent. It is the MVP and the largest share, ~62%.
- **US2 (P2)**: independent of US1. Its replay validation is part of T024.
- **US3 (P3)**: depends on T009 and T015 for the summary calls. The quoting part is independent.
- **US4 (P4)**: verification of US1–US3.

### Within Each User Story

- Tests first (T003/T004 before T005–T009; T013 before T014–T015; T017 before T018–T019).
- In US1: T005 → T006 → T007 → T008 → T009 → T010.

### Parallel Opportunities

- T003 ∥ T004 ∥ T013 ∥ T017 (separate test files; T004 extends T003's file, so write T003 first if one person does both).
- The US1 implementation (`person_matcher.py`) ∥ the US2 implementation (`person_identity.py`, `researcher_resolution.py`).
- T010 (SigPesq flows) ∥ T014–T015.
- T027 ∥ T028.

---

## Parallel Example: User Stories 1 and 2

```bash
Task: "Oracle-based PersonMatcher tests in tests/test_person_matcher_index.py"      # T003
Task: "Memoisation and resolution tests in tests/test_researcher_resolution_cache.py" # T013
Task: "Flow quoting tests in tests/test_lattes_task_quoting.py"                    # T017
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T001–T002).
2. US1: tests, index, fuzzy call, SigPesq replay identical (T003–T012).
3. **Stop and validate**: US1 alone removes ~62% of the remaining Lattes cost.

### Incremental Delivery

1. US1, then the SigPesq replay.
2. US2, with unit equivalence.
3. US3, with quoting tests.
4. US4: Lattes replay, full timing run, report.
5. Polish: backlog and docs.

---

## Notes

- Never modify `eo_lib`, `research_domain`, `libbase`, `dgp_cnpq_lib`, `agent_sigpesq`, `scriptLattes`, `thefuzz` or `rapidfuzz` (FR-011).
- Do not change `.github/workflows/weekly-etl.yml` (the `RAPIDFUZZ_IMPLEMENTATION` finding is a follow-up for the maintainer), the phase timeouts or Docker.
- Never edit `tests/_name_matching_oracle.py` after T002: it is the equivalence reference.
- Replays and full runs use databases outside the repository, except T025, which is the normal `make weekly-flows`. All of them run with Telegram disabled.
