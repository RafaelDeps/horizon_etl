# Findings: researcher/student name-variant duplication across ingestion and export

**Feature**: 008-guard-participant-merge | **Date**: 2026-09-08 | **Branch**: `fix/participant-name-variants`

## Observation

After a weekly run the same person can materialize as more than one participant
record when sources spell the full name differently. The reported exemplar:

| Raw name | Canonical key (R7) |
|---|---|
| `Paulo Sérgio Dos Santos Júnior` | `PAULO SERGIO dos SANTOS JUNIOR` |
| `Paulo Sérgio Santos Júnior` | `PAULO SERGIO SANTOS JUNIOR` |
| `Paulo Sérgio Santos Jr.` | `PAULO SERGIO SANTOS JR` |

These three spellings are the same physical person, yet they produce **three
different keys** under the R7 key function: it changes particle *case* but never
omits a particle, and it never folds the `Jr.` abbreviation into `Júnior`.

The consolidated 176-group baseline (spec SC-001) only covers records whose R7
key is already equal. The variant class above is invisible to that pass, so it
was created silently and reached the exports unmerged.

## Where duplicates are created (ingestion paths)

The participant-facing loops resolve names through three distinct paths; all of
them fall back on name comparison, and none of them collapses the two
variant axes this finding documents:

1. `PersonMatcher.match_or_create` — advisorship/education participants
   (`initiative_handlers.py:290,300`) and team/initiative members
   (`initiative_linker.py`). Match order: email → canonical (exact) → raw →
   normalized → fuzzy `token_sort_ratio >= 90` (`person_matcher.py`). The
   `Júnior`↔`Jr.` pair scores ~73 % and even the fuzzy step does not connect it;
   a new person is created per spelling.
2. `resolve_or_create_researcher` / `resolve_researcher_by_name` — advisers and
   co-advisers in `lattes_projects` (`projects.py:551,564`), CNPq groups
   (`strategies/cnpq_sync.py:268`) and the campus spreadsheet
   (`strategies/sigpesq_excel.py:103`). Exact normalized equality only — no
   fuzzy fallback at all (`researcher_resolution.py`).
3. Lattes CV owners (`resolve_researcher_from_lattes`) — robust, because the
   Lattes id in `cnpq_url` fires first; name comparison is a fallback.

## Why consolidation could not rescue them

The weekly dedup phase (`consolidate_duplicates`, see `weekly_orchestrator.py`)
groups records by the **exact** canonical key (R6/R7) and only merges within a
group. Since the three spellings key differently, they land in different groups;
the phase merges the 176 exact-key groups but leaves the variant class alone.
The canonical exports (`canonical_exporter.py`) then emit one row per surviving
`persons`/`researchers` row, so the duplicate spellings appear in
`researchers_canonical.json` / `students_canonical.json`.

## Decision

Extend the shared key function `normalize_participant_name`
(`src/core/logic/person_identity.py`) with two opt-in dimensions, both
**exact-equality only** (no fuzzy similarity), and use them where matching or
consolidation groups by name:

- `canonical_suffixes=True` — folds the `Jr.` abbreviation into `JUNIOR`, so
  `Jr.` and `Júnior` share a key. **`FILHO`, `NETO` and `SOBRINHO` stay
  distinct**: those suffixes separate generations (father/son, grandfather/
  grandson) and folding them together would manufacture exactly the false-merge
  class the R8 veto exists to refuse.
- `drop_particles=True` — deletes the surname particles (`DE..Y`) from the key,
  so a record spelled with or without `dos`/`da`/`de` shares the key.
  Conflicting strong identifiers still veto the merge (R8 refuses homonyms
  whose Lattes URL or identification disagrees).

The base R7 output is unchanged (defaults keep the lower-cased particles and the
`JR` spelling); only the opted-in extended forms are new.

### Wired paths

| Path | Change |
|---|---|
| `person_identity.py` | key function gains the two opt-in dimensions |
| `person_matcher.py` | `invariant_canonicalize_name` = `canonical_suffixes + drop_particles`; new `_invariant_cache`, checked as an **exact** match between the normalized step and the fuzzy step; registered on creation and on preload |
| `person_consolidator.py` | duplicate grouping key becomes the invariant key |
| `researcher_resolution.py` | `resolve_researcher_by_name` gains the invariant exact-equality fallback (+90, below the R7 normalized match at +100) |

Export-side dedup needs no code change: the exports read whatever `persons`/
`researchers` hold, and the consolidation phase that precedes `export_canonical`
now merges the variant class before export.

## Guards kept in force

- Exact keys only: no name-based fuzzy merge is added at dedup time (R6).
- Conflicting strong identifiers still refuse a group (R8).
- Junk names are still refused (R13).
- `FILHO`/`NETO`/`SOBRINHO` are not equated to `JUNIOR` (father/son guard,
  documented in `person_identity.py`).

## Verification

- `tests/test_person_identity.py` — suffix folding, particle omission, the
  three-spelling trio collapsing to one key, and the father/son separation.
- `tests/test_person_matcher.py` — `match_or_create` resolves the trio to one
  person, and the strict policy still refuses merely-similar (fuzzy-only) names.
- `tests/test_person_consolidator.py` — the trio is one merged group; the
  `Filho`/`Júnior` pair is never grouped; the report keys are reported in the
  particle-invariant form.
- `tests/test_researcher_lookup_index.py` — `resolve_researcher_by_name`
  resolves the variant spelling to the existing record.

Full suite: 380 passed / 7 failed (6 pre-existing baseline failures plus the
weekly workflow cron probe, which expects the Saturday schedule while main still
runs the temporary 12-hour cron).