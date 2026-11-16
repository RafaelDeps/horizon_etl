# Contract: Person Matching and Researcher Resolution

This feature exposes no external API, CLI or file format. This is the internal
interface that ETL code and tests rely on.

## `PersonMatcher.match_or_create(name, email=None, strict_match=False) -> Optional[Person]`

| Aspect | Contract |
|---|---|
| Result | For every input and every cache state, the same person (or `None`) as the implementation before spec 016. |
| Step order | Email → canonical → exact raw name → normalised (first raw name in cache order) → invariant → fuzzy → create. Unchanged. |
| Fuzzy | Same candidates (distinct normalised keys, first-seen order), each mapped to the last raw name; `token_sort_ratio`; a match is accepted when the rounded score is ≥ 90; strict mode accepts only a rounded 100. |
| Cost | Steps 1–2.5: O(1) per call. Fuzzy: one pass over pre-processed candidates with an early cutoff. No per-call re-normalisation of cached names. |
| Side effects | The same cache and e-mail registrations as today, written through `_cache_name`. |
| Logs | Today's lines unchanged, plus the counters behind `log_match_summary`. |

## `PersonMatcher.preload_cache()`

Same behaviour. All derived structures are rebuilt from the loaded persons.

## `PersonMatcher.log_match_summary(label: str) -> None`

Emits exactly one INFO line in the data-model.md format. Counters start at 0 for
each `PersonMatcher` instance.

## `normalize_participant_name(...)` (`src/core/logic/person_identity.py`)

Same signature and output for every input. It is memoised. Callers must not rely
on it being called (or not called) any given number of times.

## `resolve_researcher_by_name(all_researchers, *, name, identification_id=None)`

Same result for every input (first candidate with the strictly highest score).
It records one lookup and the winning tier, or unresolved.

## `log_researcher_resolution_summary(label: str) -> None` (`src/core/logic/researcher_resolution.py`)

Emits one INFO line in the data-model.md format and resets the counters.

## Lattes flows

- `ingest_lattes_projects_flow`: calls
  `ingest_researcher_data(json_file, quote(entity_manager), quote(parser), quote(researcher_index), quote(project_loader))`.
  At the end it logs `log_match_summary("lattes_projects")` (on
  `project_loader.person_matcher`) and
  `log_researcher_resolution_summary("lattes_projects")`.
- `ingest_lattes_advisorships_flow`: calls
  `ingest_advisorships_file_task(json_file, quote(researcher_index), quote(project_loader))`.
  At the end it logs `log_match_summary("lattes_advisorships")` and
  `log_researcher_resolution_summary("lattes_advisorships")`.
- SigPesq persist tasks: after the existing `Team lookup [...]` line, they log
  `loader.person_matcher.log_match_summary("sigpesq_projects" | "sigpesq_advisorships")`.
