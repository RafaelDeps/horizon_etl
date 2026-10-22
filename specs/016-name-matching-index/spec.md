# Feature Specification: Name-Matching Index for Persons and Researchers

**Feature Branch**: `019-name-matching-index`

**Created**: 2026-10-22

**Status**: Implemented

**Input**: User description: "Eliminate the per-lookup re-normalisation of every person and researcher name in name matching, the largest remaining cost in the Lattes phases after spec 015, so `lattes_projects` and `lattes_advisorships` each finish in under 20 minutes and `make weekly-flows` keeps shrinking toward the GitHub Actions 6-hour limit, while still running locally."

## Context

Spec 015 removed the per-record full read of the team register. The full weekly
run dropped from 8 h 04 min to 3 h 01 min, and the produced data stayed
identical (`docs/reports/2026-10-22-team-lookup-validation.md`). The two Lattes
phases still miss their targets:

| Phase | Before spec 015 | After spec 015 | Target |
|---|---:|---:|---:|
| `lattes_projects` | 81.0 min | 33.1 min | < 20 min |
| `lattes_advisorships` | 252.5 min | 48.5 min | < 20 min |

Per-CV time in `lattes_advisorships` still rises during the phase, from 5.65 s
(first 50 CVs) to 7.80 s (last 50).

### What the measurement showed

Profile of `lattes_projects` with the spec 015 code (30 CVs):

| Step | Share of phase time | What it does on every lookup |
|---|---:|---|
| Person matching (`PersonMatcher.match_or_create`) | ~62% | If the cheap dictionary lookups (email, canonical key, invariant key, exact raw name) miss, it **re-normalises every cached person name** (~17 000) to look for a normalised exact match. It then **re-normalises them all again** to build the candidate list for the fuzzy comparison. |
| Researcher name resolution (`resolve_researcher_by_name`) | ~26% | **Re-normalises every researcher name** (~7 600), twice for the particle- and suffix-invariant form, and scores each one. |
| Orchestration overhead (Prefect parameter resolution) | ~5% | Walks the ~7 600-entry researcher index passed to every CV task (~0.85 s per CV). This was task T023 of spec 015, deferred here. |

The name normalisation function was called **7.7 million times in 30 CVs**. The
person cache grows as people are created during the phase, so each lookup costs
more than the previous one. This is the same failure pattern as the team lookup
(spec 015) and the researcher register read (spec 007): work whose answer does
not change between records is repeated for every record.

### Where this matters

Person matching (`match_or_create`) is called only by the project loaders. Those
run in the `sigpesq`, `lattes_projects` and `lattes_advisorships` phases. The
`cnpq` phase does not use it. `consolidate_duplicates` uses only the name-key
helper functions, which this feature does not change. Researcher resolution is
used by both Lattes phases. The equivalence requirement applies to every one of
these phases.

## Clarifications

### Session 2026-10-22

- Q: What is the "old code" reference for the controlled replay (SC-004)? → A: The spec 015 code. Its replay outputs (`feature_sigpesq.db`, `feature_lattes.db`), produced from the same frozen inputs and the same pre-Lattes snapshot and proven identical to the pre-015 code, are reused as the reference. Only the spec 016 code is run. (Also corrected: the `cnpq` phase does not call `match_or_create`.)
- Q: Should person matching and researcher resolution log a per-phase summary? → A: Yes. Each loader logs one INFO line with person-matching hits per step (email, canonical, exact raw name, normalised, invariant, fuzzy), creations and failures. Each Lattes phase logs one INFO line with researcher resolutions per score tier.
- Q: Is the fuzzy comparison itself in scope? → A: Yes, but only result-equivalent optimisations (for example, passing the 90 threshold to the comparison as a cutoff). They must be proven by the FR-003/FR-010 tests and the replay. The comparison still considers the same candidates, scorer and thresholds.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Person matching stops re-normalising the whole cache per lookup (Priority: P1)

As the maintainer who runs the weekly pipeline, I want each cached person name
to be normalised once, when it enters the cache, and every lookup to use those
stored keys. Person matching should then cost the same at the end of a phase as
at the start, and give exactly the answers it gives today.

**Why this priority**: It is ~62% of what remains in the Lattes phases, and it
is the reason per-CV time still grows during `lattes_advisorships`.

**Independent Test**: Unit tests on person matching return the same person as
the current implementation for exact, normalised, invariant and fuzzy cases,
including duplicate normalised keys. A controlled replay of `sigpesq`
persistence and both Lattes phases is identical to the current code.

**Acceptance Scenarios**:

1. **Given** a cache that contains "José da Silva", **When** a lookup asks for
   "JOSE DA SILVA" (same normalised key, no canonical or raw hit), **Then** the
   same person as today is returned, without the cached names being normalised
   again.
2. **Given** several cached names that share one normalised key, **When** a
   lookup reaches the normalised exact step, **Then** the person returned is the
   first one in today's cache iteration order.
3. **Given** a lookup that reaches the fuzzy step, **When** candidates are
   compared, **Then** the candidate list has the same content and order as
   today, and each normalised key maps to the same original name as today (the
   last one inserted). The winner, the score threshold (90) and the strict-mode
   rule (only 100 accepted) are unchanged.
4. **Given** a person created during the phase, or a new name registered for an
   existing person after a match, **When** a later lookup uses that name or an
   equivalent spelling, **Then** it is found exactly as today.
5. **Given** the cache is reloaded from the database, **When** lookups resume,
   **Then** the stored keys reflect the reloaded cache only.

---

### User Story 2 - Researcher resolution stops re-normalising every researcher per lookup (Priority: P2)

As the maintainer, I want each researcher's normalised name forms to be computed
once per phase and reused by every resolution. The scoring and tie-breaking must
stay exactly as they are.

**Why this priority**: It is ~26% of what remains in the Lattes phases. It is
independent of person matching and can be delivered and validated on its own.

**Independent Test**: Unit tests show that resolution returns the same
researcher as the current scoring loop on fixtures with ties and with every
scoring tier. The Lattes controlled replay is identical.

**Acceptance Scenarios**:

1. **Given** researchers that tie on score, **When** a name is resolved,
   **Then** the first researcher in index order with the strictly highest score
   is returned, as today.
2. **Given** the scoring tiers (identification match 200, exact case-insensitive
   name 150, normalised name 100, particle- and suffix-invariant name 90),
   **When** each tier is exercised, **Then** the scores and the chosen researcher
   match the current behaviour.
3. **Given** a researcher created or updated during the phase, **When** a later
   CV resolves that researcher's name, **Then** it is found as it is today.

---

### User Story 3 - Lattes CV tasks stop paying orchestration overhead on large inputs (Priority: P3)

As the maintainer, I want the per-CV tasks of both Lattes phases to receive
their large shared inputs (the researcher index and the shared loader and entity
manager objects) without the orchestrator inspecting them on every call.

**Why this priority**: It is ~5% of what remains, around 0.85 s per CV. It is
cheap to do, but secondary to Stories 1 and 2.

**Independent Test**: A test shows that those inputs are passed in a form the
orchestrator does not traverse, and that the tasks still receive the same
objects. Phase behaviour is unchanged.

**Acceptance Scenarios**:

1. **Given** a Lattes phase run, **When** each CV task is invoked, **Then** the
   researcher index and the shared objects reach the task unchanged, and the
   orchestrator does not walk their contents.

---

### User Story 4 - The Lattes phases meet their time targets (Priority: P4)

As the maintainer, I want a full local `make weekly-flows` to show both Lattes
phases under 20 minutes, with flat per-CV time.

**Why this priority**: It is the outcome of Stories 1–3, verified by a full run
rather than built separately.

**Independent Test**: A full local run on the current inputs, compared with the
spec 015 validation run.

**Acceptance Scenarios**:

1. **Given** the current ~435 CVs, **When** `make weekly-flows` runs locally,
   **Then** every phase exits 0 and both Lattes phases finish in under 20
   minutes, with flat per-CV time.

### Edge Cases

- **Empty or whitespace-only names:** keep today's behaviour (match by email if
  one is given, otherwise no match and no creation).
- **Names that normalise to an empty key:** keep today's behaviour at every step
  (no normalised or fuzzy match on an empty input).
- **Duplicate normalised keys:** the normalised exact step returns the first
  entry in today's order. The fuzzy step maps each key to the last original name
  and keeps the first-seen position of the key, as today.
- **The same raw name registered again for another person:** today this replaces
  the cached person for that name while keeping the name's original position.
  The stored keys must reflect the same replacement.
- **Cache reload in the middle of a run:** every stored key is rebuilt from the
  reloaded cache.
- **Pure-Python fuzzy implementation:** CI sets
  `RAPIDFUZZ_IMPLEMENTATION=fallback`. Results must be identical with the
  pure-Python and the native implementation.
- **Researchers without a name or identification:** scoring treats them as
  today.
- **Large caches:** per-lookup cost must not grow with the number of cached
  names, except for the fuzzy comparison itself. That comparison still considers
  the whole candidate list, but may stop early through a result-equivalent cutoff
  (FR-017).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Person matching MUST compute each cached name's normalised key at
  most once per time the name enters or re-enters the cache: on preload, on
  creation, and on registering a matched name. Lookups MUST NOT re-normalise the
  cached names.
- **FR-002**: The normalised exact step MUST return the same person as today: the
  first cached entry, in the cache's iteration order, whose normalised key equals
  the input's.
- **FR-003**: The fuzzy step MUST pass to the fuzzy comparison the same
  candidate list as today, in the same order, with each normalised key mapped to
  the same original name (the last one inserted for that key). It MUST apply the
  same scorer, threshold (90) and strict rule (100).
- **FR-004**: The stored keys MUST stay consistent with every mutation of the
  person cache (preload, creation, match registration, reload). No lookup may
  observe stale keys.
- **FR-005**: Researcher name resolution MUST compute each researcher's
  normalised and invariant name forms at most once per phase run. It MUST NOT
  re-normalise every researcher on each lookup.
- **FR-006**: Researcher resolution MUST keep the scoring rules (200 / 150 / 100
  / 90) and return the first researcher, in index order, with the strictly
  highest score, as today.
- **FR-007**: Researchers created or updated during a phase MUST be resolvable by
  later CVs exactly as today.
- **FR-008**: The per-CV tasks of `lattes_projects` and `lattes_advisorships`
  MUST receive the researcher index and the shared loader and entity manager
  objects in a form the orchestrator does not traverse. The tasks MUST receive
  the same objects as before.
- **FR-009**: For the same inputs, the entities, links, memberships,
  advisorships, articles and educations produced MUST be identical to today's.
  This applies in every phase that uses person matching or researcher resolution
  (`sigpesq`, `lattes_projects`, `lattes_advisorships`).
- **FR-010**: Fuzzy results MUST be identical with the pure-Python fuzzy
  implementation used in CI and with the native one.
- **FR-011**: All changes MUST live in this repository's own code and tests. No
  external library may be modified, replaced or re-implemented: `eo_lib`,
  `research_domain`, `libbase`, `dgp_cnpq_lib`, `agent_sigpesq`, `scriptLattes`,
  `rapidfuzz`.
- **FR-012**: The change MUST work identically in the GitHub Actions weekly
  workflow (clean checkout, fresh SQLite database) and in local runs. It MUST
  write to the database from a single writer only, as today.
- **FR-013**: Automated tests MUST cover:
  - a normalised exact hit served without re-normalising the cache;
  - a name added by creation or by match registration, found by a later lookup;
  - a fuzzy candidate list and winner identical to the current implementation,
    on a fixture with duplicate normalised keys;
  - researcher resolution returning the same researcher as the current scoring
    loop, on fixtures with ties and with every scoring tier;
  - the Lattes per-CV tasks receiving their large inputs untraversed;
  - the person-matching and researcher-resolution summary lines and their
    counters (FR-014, FR-015).
- **FR-014**: At the end of each loader's work (the same points where spec 015
  logs `Team lookup [<label>]`), the system MUST log one INFO line with
  person-matching counters:
  - hits by email, canonical key, exact raw name, normalised key, invariant key
    and fuzzy match;
  - fuzzy candidates rejected by strict mode;
  - persons created;
  - creation failures.
- **FR-015**: At the end of `lattes_projects` and `lattes_advisorships`, the
  system MUST log one INFO line with researcher-resolution counters: lookups,
  resolved by score tier (200 identification, 150 exact case-insensitive name,
  100 normalised name, 90 invariant name), and unresolved.
- **FR-016**: The new summary lines MUST NOT contain person names, CPF, phone
  numbers or e-mails, only labels and counts. No per-lookup log lines may be
  added.
- **FR-017**: The fuzzy comparison MAY be optimised only in ways that provably
  keep the same decision for every input: the same winner when the best score is
  ≥ 90, the same "no match" when it is below 90, and the same strict-mode
  rejection for scores from 90 to below 100. Passing the 90 threshold to the
  comparison as a cutoff is an example. Any such optimisation MUST be covered by
  the FR-013 fuzzy equivalence tests, under both fuzzy implementations.

### Key Entities

- **Person cache**: the in-memory map from raw person name to person, already
  maintained by person matching. It gains a stored normalised key per name, kept
  in step with the map.
- **Fuzzy candidate view**: the ordered list of distinct normalised keys and the
  key → original-name map used by the fuzzy comparison. Its content and order
  must equal what today's per-lookup rebuild produces.
- **Researcher index entry**: the per-phase lightweight reference to a researcher
  (spec 007). It gains precomputed normalised and invariant name forms.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a full local `make weekly-flows` with the current ~435 CVs,
  `lattes_projects` finishes in under 20 minutes (spec 015 baseline: 33.1 min)
  and exits 0.
- **SC-002**: On the same run, `lattes_advisorships` finishes in under 20 minutes
  (spec 015 baseline: 48.5 min) and exits 0.
- **SC-003**: In `lattes_advisorships`, the mean per-CV time of the last 50 CVs is
  at most 1.2× that of the first 50 (spec 015 baseline: 1.38). It is measured
  from the per-CV duration lines in the run log.
- **SC-004**: A controlled replay of the spec 016 code is identical to the
  reference. The reference is the spec 015 replay outputs (`feature_sigpesq.db`,
  `feature_lattes.db`), which were proven identical to the pre-015 code. The
  replay covers `sigpesq` persistence (from a fresh database) and both Lattes
  phases (from the same pre-Lattes snapshot), with the same frozen inputs as
  spec 015. "Identical" means:
  - the same counts of teams, team memberships, initiatives, initiative–team
    links, advisorships and persons;
  - the same name-based link and membership sets.

  The procedure is the one in `specs/015-team-lookup-index/quickstart.md` §2.
- **SC-005**: The full weekly run completes in less time than the spec 015
  validation run (3 h 01 min), excluding the CNPq phase. The CNPq phase is
  excluded because its duration depends on portal behaviour outside this
  feature.
- **SC-006**: The existing test suite shows no new failures (the 6 failures that
  pre-date spec 015 may remain), and the tests listed in FR-013 pass.

## Assumptions

- The ~435-CV input set, the person cache size (~17 000 names) and the researcher
  index size (~7 600) are representative of current weekly runs.
- The fuzzy comparison keeps the same candidates, scorer and thresholds.
  Besides removing the per-lookup rebuild and re-normalisation, only
  result-equivalent optimisations of the comparison are allowed (FR-017). The
  fuzzy step is reached only on misses of the cheaper steps.
- Today's iteration order of the person cache (insertion order of raw names,
  with re-registered names keeping their original position) is the reference
  for all tie-breaking.
- No other code path mutates the person cache besides preload, creation and
  match registration. If planning finds one, it must keep the stored keys in
  step as well (FR-004).
- CNPq fetch concurrency, TD-008 (researcher register read per CNPq group) and
  the phase timeouts are out of scope; they are tracked as TD-014 and TD-015 in
  `docs/backlog.md`.
- The controlled replay reuses the spec 015 harness (frozen inputs, pre-Lattes
  snapshot, comparison script). That harness lives outside the repository.
- The spec 015 validation run
  (`docs/reports/2026-10-22-team-lookup-validation.md`) is the baseline for the
  time criteria.
