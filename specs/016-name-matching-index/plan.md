# Implementation Plan: Name-Matching Index for Persons and Researchers

**Branch**: `019-name-matching-index` | **Date**: 2026-10-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/016-name-matching-index/spec.md`

## Summary

After spec 015, the Lattes phases still take 33 and 48 minutes. About 88% of
that is name matching that re-does work whose answer does not change between
lookups. The plan has five parts:

1. **`PersonMatcher` index.** Every write to `_persons_cache` goes through one
   method. That method maintains a first-raw-name-per-normalised-key map (the
   normalised exact step), plus an ordered list of distinct normalised keys with
   their pre-processed forms and a last-raw-name map (the fuzzy step). Both steps
   become O(1) bookkeeping and stop re-normalising 17 000 names per call.
2. **Fuzzy call.** `thefuzz.process.extractOne` is replaced by
   `rapidfuzz.process.extractOne` on the pre-processed candidates with
   `score_cutoff=89.5` and the same rounding. This gives the same decisions,
   proven on 466 real-name queries under both implementations with 0 mismatches.
3. **Researcher resolution.** `normalize_participant_name` is memoised. It is a
   pure function, so the resolution loop and its tie-breaking stay untouched.
4. **Prefect.** The large per-CV task parameters are passed with `quote(...)`
   (spec 015 T023).
5. **Observability and validation.** Per-loader `Person matching [...]` and
   per-phase `Researcher resolution [...]` summary lines. Validation is a
   controlled replay against the spec 015 replay outputs, plus a full timing run.

Details and evidence are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 in CI; 3.14 in the local venv.

**Primary Dependencies**: thefuzz 0.22.1 (only its `utils.full_process` is still used), rapidfuzz 3.14.5 (called directly for the fuzzy step), Prefect 3.6.23 (`quote`), loguru. No new dependency.

**Storage**: SQLite; no schema change; a single writer, as today.

**Testing**: pytest. The equivalence tests use a frozen copy of the pre-016 matcher as the oracle and run under both rapidfuzz implementations. Controlled replay and timing run per [quickstart.md](quickstart.md).

**Target Platform**: Linux (GitHub-hosted `ubuntu-latest` and the maintainer's machine).

**Project Type**: Batch ETL (Prefect flows run as subprocess phases).

**Performance Goals**:
- `lattes_projects` < 20 min (33.1 today);
- `lattes_advisorships` < 20 min (48.5 today);
- last-50 / first-50 per-CV ratio ≤ 1.2 (1.38 today).

**Constraints**:
- Identical matching results and tie-breaking;
- no change to external libraries;
- no persisted state between runs.

**Scale/Scope**: ~17 000 distinct normalised person keys, ~7 600 researchers and ~435 CVs per run. The new structures hold a few MB.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Result |
|---|---|---|
| **I. Ports & Adapters** | Changes are in `src/core/logic/` (`person_matcher.py`, `person_identity.py`, `researcher_resolution.py`) and in `src/flows/lattes/` and `src/flows/sigpesq/`. No adapter import is added to core logic. | PASS |
| **II. Domain-First Data Modeling** | No new domain concept and no schema change. The new structures are ETL-only in-memory indexes over existing caches. | PASS |
| **III. Prefect Flow Orchestration** | No new ingestion path. Flows only change how parameters are passed (`quote`) and add summary logs. The Telegram hooks are untouched. | PASS |
| **IV. Audit-Driven Data Quality** | Adds audit signals: hits per matching step, fuzzy matches, strict rejections, creations, creation failures, researcher tiers. Equivalence is proven by the controlled replay. | PASS |
| **V. LGPD Compliance** | The new lines carry counts and labels only. No names, CPF, phone numbers or e-mails. Existing log lines are unchanged. | PASS |
| **Data Integrity & Clean-State Ingestion** | Works from a fresh database. Caches are rebuilt per loader and per phase subprocess. | PASS |
| **Quality gates** | Tests are added for the matcher, researcher resolution and flow quoting. `make ci-check` already fails repository-wide on pre-existing formatting (spec 015 report §6); the touched files will be clean. | PASS (pre-existing repo-wide failures documented) |

**Post-design re-check**: unchanged; all PASS.

## Findings during planning

1. **The CNPq phase does not call `match_or_create`.** This was corrected in the
   spec during `/speckit-clarify`. The affected callers are the `sigpesq` and
   both Lattes project loaders.
2. **`RAPIDFUZZ_IMPLEMENTATION=fallback` is ignored by rapidfuzz** (research.md
   R5). rapidfuzz only recognises `cpp` and `python`, so the workflow's AVX2
   workaround (commit `e0d137e`) has no effect, and CI runs the native AVX2
   code. This is **out of scope** and left for the maintainer to decide. The
   tests here cover both implementations, so this feature is correct either way.

## Project Structure

### Documentation (this feature)

```text
specs/016-name-matching-index/
├── spec.md
├── plan.md              # This file
├── research.md          # R1–R10
├── data-model.md        # PersonMatcher state, invariants, step flow, log records
├── quickstart.md        # Tests, controlled replay, timing run
├── contracts/
│   └── name-matching.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks (not created here)
```

### Source Code (repository root)

```text
src/
├── core/logic/
│   ├── person_matcher.py        # CHANGED: _cache_name, first/last maps, fuzzy view,
│   │                            #          rapidfuzz call with cutoff 89.5, counters,
│   │                            #          log_match_summary()
│   ├── person_identity.py       # CHANGED: memoised normalize_participant_name
│   └── researcher_resolution.py # CHANGED: resolution counters,
│                                #          log_researcher_resolution_summary()
└── flows/
    ├── lattes/projects.py       # CHANGED: quote() task params; summary lines
    ├── lattes/advisorships.py   # CHANGED: quote() task params; summary lines
    ├── sigpesq/projects.py      # CHANGED: person-matching summary line
    └── sigpesq/advisorships.py  # CHANGED: person-matching summary line

tests/
├── test_person_matcher_index.py          # NEW: oracle-based equivalence, cache mutations,
│                                         #      fuzzy view, strict mode, summary
├── test_researcher_resolution_cache.py   # NEW: memoisation equivalence, ties, tiers, summary
└── test_lattes_task_quoting.py           # NEW: per-CV tasks receive quoted params
```

**Structure Decision**: The existing single-project layout. No new modules
outside `tests/`.

## Implementation outline (for `/speckit-tasks`)

1. **Oracle.** Copy the pre-016 `match_or_create` steps 2 and 3 and the
   `resolve_researcher_by_name` loop into the test modules as frozen reference
   functions.
2. **Equivalence tests (failing first).**
   - Normalised hits with duplicate keys.
   - A re-registered raw name.
   - The fuzzy view (order = first-seen, value = last).
   - Strict mode.
   - An empty processed query.
   - Randomised real-style names, run under both rapidfuzz implementations.
3. **`_cache_name` and the derived structures** in `person_matcher.py`; route the
   preload and the step 1.5, 2, 2.5 and creation writes through it.
4. **Steps 2 and 3** read the new structures. The fuzzy call becomes
   `rapidfuzz.process.extractOne(..., processor=None, score_cutoff=89.5)` with
   `int(round(score))` and the same thresholds. Keep today's log messages.
5. **Counters and `log_match_summary`.**
6. **Memoise `normalize_participant_name`** (bounded LRU on `(str(name), flags)`;
   `None` returns `""` without caching), with memoisation-equivalence tests.
7. **Researcher resolution counters** and
   `log_researcher_resolution_summary`, with tie and tier tests.
8. **Flows.** `quote(...)` on the large per-CV task parameters in both Lattes
   flows. Summary lines at the end of both Lattes flows and of both SigPesq
   persist tasks.
9. **Quoting test** (`tests/test_lattes_task_quoting.py`).
10. **Formatting and lint** on the touched files, and a full `pytest` with no new
    failures against the 6 pre-existing ones.
11. **Controlled replay** against the spec 015 outputs (quickstart §2).
12. **Full timing run**, spaced from other CNPq crawls (quickstart §3), and the
    validation report under `docs/reports/`.
13. **Backlog.** Close TD-013, and add the `RAPIDFUZZ_IMPLEMENTATION` finding as a
    new TD.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Four derived structures kept in step with `_persons_cache` | They make steps 2 and 3 O(1) bookkeeping while reproducing today's exact order and mapping semantics. | Memoising `normalize_name` alone keeps two 17 000-iteration Python loops and one 17 000-item `full_process` pass per call. |
| Calling `rapidfuzz` directly instead of `thefuzz` | It allows pre-processing candidates once and an early cutoff, which is where the fuzzy cost is. | `thefuzz.extractOne` always re-processes every choice. Its cutoff alone does not remove that cost. |
