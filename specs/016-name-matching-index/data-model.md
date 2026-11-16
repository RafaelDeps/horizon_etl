# Data Model: Name-Matching Index

**Feature**: [spec.md](spec.md) · **Research**: [research.md](research.md)

There is no database schema change. Everything here is in-memory ETL state.
`Person` and `Researcher` stay owned by `eo_lib` / `research_domain`
(constitution II).

## PersonMatcher state

### Existing state (unchanged)

| Field | Type | Meaning |
|---|---|---|
| `_persons_cache` | `dict[str, Person]` | Raw name → person. Iteration order = insertion order of raw names. Re-assignment keeps the position. |
| `_emails_cache` | `dict[str, Person]` | Email keys → person. |
| `_canonical_cache` | `dict[str, Person]` | Canonical key → best-quality person. |
| `_invariant_cache` | `dict[str, Person]` | Invariant key → best-quality person. |

### New state

| Field | Type | Meaning | Maintained when |
|---|---|---|---|
| `_first_by_norm` | `dict[str, str]` | `normalize_name(raw)` → the **first** raw name, in `_persons_cache` order, with that key | A **new** raw key is cached: `setdefault` |
| `_last_by_norm` | `dict[str, str]` | `normalize_name(raw)` → the **last** raw name, in `_persons_cache` order, with that key | A **new** raw key is cached: assignment |
| `_fuzzy_keys` | `list[str]` | Distinct normalised keys in first-seen order (= today's `list(normalized_to_original)`) | A new raw key brings an **unseen** normalised key: append |
| `_fuzzy_processed` | `list[str]` | `full_process(key, force_ascii=True)` for each entry of `_fuzzy_keys`, same index | Appended together with `_fuzzy_keys` |
| `_stats` | counters | `email`, `canonical`, `exact`, `normalised`, `invariant`, `fuzzy`, `strict_rejected`, `created`, `create_failed` | On each outcome |

### Invariants

1. `_first_by_norm`, `_last_by_norm`, `_fuzzy_keys` and `_fuzzy_processed` equal
   what today's code would compute from `_persons_cache` at any moment:
   - `_first_by_norm[k]` is the first raw name `r`, in iteration order, with
     `normalize_name(r) == k`;
   - `_last_by_norm[k]` is the last such `r`;
   - `_fuzzy_keys` is the list of distinct keys, in first-seen order;
   - `_fuzzy_processed[i]` is `full_process(_fuzzy_keys[i], force_ascii=True)`.
2. The only writer of `_persons_cache` is `_cache_name(raw, person)`; for a new
   `raw` it updates the four structures before storing the person.
   `preload_cache` clears all of them and rebuilds through `_cache_name`.
3. Re-assigning an existing raw key changes only `_persons_cache[raw]`.

### `match_or_create(name, email, strict_match)` after the change

```text
1    email keys in _emails_cache            → stats.email      → return
1.5  canonical key in _canonical_cache      → stats.canonical  → _cache_name(name) → return
1.6  name in _persons_cache                 → stats.exact      → return
2    raw = _first_by_norm.get(norm(name))   → stats.normalised → _cache_name(name) → return _persons_cache[raw]
2.5  invariant key in _invariant_cache      → stats.invariant  → _cache_name(name) → return
3    if _fuzzy_keys and norm(name):
       q = full_process(norm(name)); if q:
         r = rapidfuzz.extractOne(q, _fuzzy_processed, token_sort_ratio, processor=None, score_cutoff=89.5)
         if r: score = round(r.score)
               if strict and score < 100: stats.strict_rejected (fall through to create)
               else: raw = _last_by_norm[_fuzzy_keys[r.index]] → stats.fuzzy → _cache_name(name) → return
4    create_person → _cache_name(name) + canonical/invariant/email updates → stats.created → return
     on exception → stats.create_failed → None
```

Every branch, side effect and log message is the same as today. The only
differences are the data structure each step reads and the counters.

## Researcher resolution

| Element | Change |
|---|---|
| `normalize_participant_name(name, canonical_particles, canonical_suffixes, drop_particles)` | Memoised on `(str(name), flags)` with an LRU cache of 262 144 entries. `None` returns `""` without caching. The output is unchanged. |
| `resolve_researcher_by_name` | Loop and scoring unchanged. Counters for lookups, tiers 200 / 150 / 100 / 90 and unresolved. |
| `ResearcherRef` | Unchanged. |

## Log records

**Person matching**: one INFO line per loader.

```text
Person matching [<label>]: email=<n> canonical=<n> exact=<n> normalised=<n> invariant=<n> fuzzy=<n> strict_rejected=<n> created=<n> create_failed=<n>
```

`<label>` is one of `sigpesq_projects`, `sigpesq_advisorships`,
`lattes_projects` or `lattes_advisorships`.

**Researcher resolution**: one INFO line per Lattes phase.

```text
Researcher resolution [<label>]: lookups=<n> tier200=<n> tier150=<n> tier100=<n> tier90=<n> unresolved=<n>
```

Both lines carry counts only: no names, CPF, phone numbers or e-mails (FR-016).
