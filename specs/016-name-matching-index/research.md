# Research: Name-Matching Index for Persons and Researchers

**Feature**: [spec.md](spec.md) · **Date**: 2026-10-22

Measurements were taken against the spec 015 replay database
(`feature_lattes.db`, 17 127 distinct normalised person keys), never against
`db/horizon.db`.

## R1. Where person-matching time goes today

`PersonMatcher.match_or_create` (`src/core/logic/person_matcher.py`) runs its
steps in this order:

| # | Step | Cost per call today |
|---|---|---|
| 1 | Email: dict probe | O(1) |
| 1.5 | Canonical key: dict probe | O(1) |
| 1.6 | Exact raw name: dict probe | O(1) |
| 2 | **Normalised exact**: loop over every `_persons_cache` key, calling `normalize_name` on each | O(n) normalisations |
| 2.5 | Invariant key: dict probe | O(1) |
| 3 | **Fuzzy**: rebuild `{normalize_name(n): n for n in names}` (O(n) normalisations), then `thefuzz.process.extractOne` (O(n) `full_process` + O(n) scorer calls) | O(n) × 3 |
| 4 | Create, plus cache updates | O(1) |

With n ≈ 17 000 and growing, each call that reaches step 2 pays roughly 51 000
string normalisations. That matches the profile: 5.4 M `normalize_name` calls in
30 CVs.

## R2. Normalised exact step (step 2): an incremental first-seen index

**Decision**:
- Keep `_first_by_norm: dict[str, str]`, which maps a normalised key to the
  **first raw name**, in cache iteration order, that has that key.
- Step 2 becomes `raw = _first_by_norm.get(normalized_input)`, then
  `person = _persons_cache[raw]`.

**Equivalence**: today's loop returns `_persons_cache[first raw name whose key
matches]`, reading the person *currently* stored under that raw name.
`_persons_cache` is a plain dict, so its iteration order is the insertion order
of raw keys, and re-assigning an existing key keeps its position. The first raw
name for a given key therefore changes only when a *new* raw key is inserted
and no earlier one has that key, which is exactly what
`setdefault(norm, raw)` on new-key insertion does. The person is read from
`_persons_cache` at lookup time, so a re-assigned value is seen, as today.

**Alternatives considered**:
- *Memoising `normalize_name` and keeping the loop.* Rejected for this step: it
  is still a 17 000-iteration Python loop per call.

## R3. Fuzzy step (step 3): an incrementally maintained candidate view

Today, for every fuzzy call, the code runs:

```python
normalized_to_original = {self.normalize_name(n): n for n in names_in_cache}
normalized_list = list(normalized_to_original.keys())
best_norm_match, score = process.extractOne(normalized_input, normalized_list, scorer=fuzz.token_sort_ratio)
```

Properties that must be reproduced (FR-003):
- **Order**: the list holds the distinct normalised keys in **first-seen**
  order of raw names. A dict keeps the position of a key's first insertion.
- **Mapping**: each key maps to the **last** raw name, in iteration order, that
  produced it. In a dict comprehension later assignments overwrite the value.

**Decision**:
- Maintain `_fuzzy_keys: list[str]`, `_fuzzy_processed: list[str]` and
  `_last_by_norm: dict[str, str]`.
- When a **new** raw key enters `_persons_cache`:
  - if its normalised key is unseen, append the key to `_fuzzy_keys` and append
    its pre-processed form to `_fuzzy_processed`;
  - in every case, set `_last_by_norm[norm] = raw`.

  A new raw key is always last in iteration order, so it becomes the "last" name
  for its key.
- Re-assigning an existing raw key changes neither order nor mapping, so it does
  nothing, as today.

## R4. The fuzzy comparison itself (FR-017)

`thefuzz.process.extractOne(query, choices, scorer=fuzz.token_sort_ratio)`
(thefuzz 0.22.1) does three things:
- pre-processes the query with `utils.full_process`;
- delegates to `rapidfuzz.process.extractOne` with a processor that applies
  `full_process(force_ascii=True)` to **every choice on every call**, and with
  the lowered scorer `rapidfuzz.fuzz.token_sort_ratio`;
- then **rounds** the winning float score to an int.

**Decision**: replace the call with
`rapidfuzz.process.extractOne(processed_query, _fuzzy_processed, scorer=rapidfuzz.fuzz.token_sort_ratio, processor=None, score_cutoff=89.5)`.
Round the returned score with `int(round(score))`, map the returned index back
to `_fuzzy_keys[idx]`, and then to `_last_by_norm[...]`. If the processed query is
empty, treat it as "no fuzzy match", which is today's outcome: every score is 0
and thefuzz logs a warning.

**Why 89.5 and not 90**: thefuzz chooses the winner on the **unrounded** score,
and the current code then tests the **rounded** score with `score >= 90`. A float
of 89.5 or more rounds to 90 or more. A cutoff of 89.5 therefore keeps exactly
the matches that pass today. Strict mode (accept only rounded 100) is applied
afterwards, unchanged. `rapidfuzz` returns the first choice with the highest
score, as thefuzz does, because thefuzz delegates to it.

**Empirical check**: real names, queries with dropped tokens, deleted
characters, shuffled tokens and nonsense, every decision compared in both
normal and strict mode:

| Implementation | Queries | Candidates | Mismatches | Old ms/query | New ms/query |
|---|---:|---:|---:|---:|---:|
| native (default) | 403 | 17 127 | **0** | 25.6 | 9.4 |
| pure Python (`RAPIDFUZZ_IMPLEMENTATION=python`) | 63 | 17 127 | **0** | 240.2 | 199.8 |

**Alternatives considered**:
- *Keep `thefuzz` and only pass `score_cutoff=89.5`.* Rejected: it still runs
  `full_process` on 17 000 choices per call.
- *Narrower candidate sets (for example, blocking by first token).* Rejected:
  that changes which candidates are compared, which FR-003 forbids.

## R5. Finding: `RAPIDFUZZ_IMPLEMENTATION=fallback` is not a valid value

**Outside this feature's scope; recorded for follow-up.**
- `rapidfuzz` 3.14.5 only recognises `cpp` and `python` (`rapidfuzz/process.py`,
  `fuzz.py`, `utils.py`). Any other value takes the default branch, which picks
  **AVX2** when the CPU supports it.
- With `RAPIDFUZZ_IMPLEMENTATION=fallback` set locally, `rapidfuzz.fuzz` resolved
  to `rapidfuzz.fuzz_cpp_avx2`.
- The workflow sets that value (commit `e0d137e`, "disable rapidfuzz AVX2 SIMD
  to prevent segfault in CI"), so that workaround probably has no effect. CI
  then runs the native implementation, not pure Python.

FR-010 still applies as written: results must be identical under both
implementations, and the tests exercise both. The variable is not changed in
this feature (spec scope). It is listed as a follow-up for the maintainer, since
the right fix (`cpp` with SSE2 only, or `python`) involves the segfault history.

## R6. Researcher name resolution: memoise the name-key function

`resolve_researcher_by_name` iterates candidates that are either `ResearcherRef`
records (Lattes) or ORM `Researcher` entities (`cnpq_sync`, `sigpesq_excel`).
For each candidate it calls `normalize_participant_name` once or twice.
Candidate names can change during a phase (`sync_researcher_ref`), and new
candidates are appended (`resolve_or_create_researcher`).

**Decision**: memoise `normalize_participant_name`
(`src/core/logic/person_identity.py`) on `(str(name), canonical_particles,
canonical_suffixes, drop_particles)` with a bounded LRU cache. `None` keeps
returning `""` without touching the cache. The function is pure: it depends only
on its arguments and module-level constants. Every caller, every candidate type
and every name change therefore gets identical results. The loop and the scoring
in `resolve_researcher_by_name` stay byte-for-byte the same, which preserves
tie-breaking (FR-006) by construction.

**Rationale**:
- A per-candidate precomputed field would have to be kept in step with
  `sync_researcher_ref` and with ORM entities that the ETL does not own. A
  key-function cache needs no invalidation.
- The remaining per-lookup cost is a loop over ~7 600 candidates with dict-hit
  normalisations: on the order of milliseconds, against ~1 s per lookup today.
- The same cache also speeds up every other name-key call (consolidation,
  `is_junk_name`, `PersonMatcher` steps 1.5 and 2.5 on inputs).

**Cache bound**: `maxsize=262_144`, about 4 flag combinations over the
~35 000 person and researcher names of a run, with headroom. Each phase is its
own subprocess, so the cache never outlives a phase.

**Alternatives considered**:
- *Precompute on `ResearcherRef`.* Rejected: it does not cover ORM-entity
  candidates and needs invalidation on renames.

## R7. Single mutation point for `_persons_cache`

Today `_persons_cache` is written at three places in `match_or_create` (steps 1.5,
2 and 2.5, and creation) and rebuilt in `preload_cache`. Outside the class it is
only **read**: `project_loader.py` uses `len(...)` and truthiness.

**Decision**: route every write through one private method,
`_cache_name(raw, person)`:
- if `raw` is a new key, update `_first_by_norm`, `_last_by_norm`, `_fuzzy_keys`
  and `_fuzzy_processed`;
- then assign `_persons_cache[raw] = person`.

`preload_cache` resets every structure and rebuilds through the same method.
That meets FR-004 by construction. Writes to the email, canonical and invariant
caches are unchanged.

## R8. Prefect parameter traversal (T023 from spec 015, FR-008)

**Decision**:
- `lattes_projects`: wrap `researcher_index`, `entity_manager`, `parser` and
  `project_loader` with `prefect.utilities.annotations.quote(...)` at the
  `ingest_researcher_data(...)` call.
- `lattes_advisorships`: wrap `researcher_index` and `project_loader` at the
  `ingest_advisorships_file_task(...)` call.

**Verified**: a task called with `quote(list)` and `quote(obj)` received the
original `list` (5 items) and the original object type. Prefect unwraps quoted
parameters before calling the task body.

**Measured overhead today**: `_resolve_parameters` 25.6 s for 30 CVs (~0.85 s per
CV) in the spec 015 profile.

## R9. Observability (FR-014–FR-016)

**Decision**:
- `PersonMatcher` keeps counters `email`, `canonical`, `exact`, `normalised`,
  `invariant`, `fuzzy`, `strict_rejected`, `created` and `create_failed`, and
  exposes `log_match_summary(label)`. The line is:

  ```text
  Person matching [<label>]: email=.. canonical=.. exact=.. normalised=.. invariant=.. fuzzy=.. strict_rejected=.. created=.. create_failed=..
  ```
- Researcher resolution keeps module-level counters, reset per phase, for
  lookups, the tiers 200, 150, 100 and 90, and unresolved. They are exposed
  through `log_researcher_resolution_summary(label)`.
- Both lines are logged where spec 015 logs `Team lookup [...]`. The researcher
  line is logged at the end of the two Lattes flows.
- Lines carry labels and counts only (FR-016).

**Tier counting detail**: today's loop adds scores per candidate. The counters
record the tier of the **winning** researcher's name component: 200 when
identification matches, else 150, 100 or 90 by the name rule. A winner that is
returned because of identification only counts as 200. Unresolved means `None`
was returned.

## R10. Validation (SC-004, per clarification 2026-10-22)

**Reference**: the spec 015 replay outputs, `feature_sigpesq.db` and
`feature_lattes.db`, kept with the frozen inputs and `pre_lattes.db` in the
spec 015 replay directory outside the repository. Only the spec 016 code is run:
- `sigpesq` persistence on a fresh database;
- the two Lattes phases on a copy of `pre_lattes.db`.

The results are compared with the spec 015 `compare.py`.

**Coverage**: `match_or_create` is called only by project loaders, which run in
`sigpesq`, `lattes_projects` and `lattes_advisorships`, so this replay covers
every caller. `cnpq_sync` reaches `resolve_or_create_researcher` and benefits
from R6. R6 is a pure memoisation, so it cannot change CNPq output; its unit
tests cover equivalence.
