# Research: Every professional activity is kept, with the right institution

**Feature**: `034-keep-professional-activities` | **Date**: 2026-11-11

All numbers were measured on 2026-11-11 over the 435 curricula in
`data/lattes_json/` and the database of the 2026-11-10 local run, with a
prototype of the rules below (no code of the project was changed).

## R1. Where the rules live

- **Decision**: a new pure module `src/core/logic/professional_activity_rules.py`
  with two functions: `split_institution(text)` and
  `distinct_activities(items)`. `LattesParser.parse_professional_activities`
  calls both; `ingest_professional_activities_task` and the id rule use the
  fields they produce.
- **Rationale**: the rules are business rules, so they belong in
  `src/core/logic/` (Constitution I). An adapter may import core logic; the
  core does not import the adapter. One module gives one place to test.
- **Alternatives considered**: keeping the logic inside the parser (an adapter
  would then hold a business rule); doing it in the flow task (the parser would
  keep returning the swapped fields to any other caller).

## R2. Reading name, acronym and country from the institution text

- **Decision**: `split_institution` works on the full text (`instituicao`):
  1. Strip spaces and remove full stops and spaces at the very end.
  2. Split on commas; trim each part; drop empty parts.
  3. One part: it is the name; no acronym, no country.
  4. The last part has no lowercase letter ("QUIMI", "MULTI", "E"): it is the
     acronym; everything before it is the name; no country.
  5. The last part has a lowercase letter and there are three parts or more:
     the last part is the country, the part before it is the acronym, and the
     text before them is the name, as written.
  6. The last part has a lowercase letter and there are two parts: when the
     last part is a known country name it is the country and the first part is
     the name; otherwise both parts are the name and the other two fields are
     empty.
- **Rationale** (measured, 13,420 items):

  | Shape | Items | What the data shows |
  |-------|-------|---------------------|
  | 1 part | 461 | Names, most of them cut by the library ("Universidade Federal de") |
  | 2+ parts, last part without lowercase | 129 | The last part is always an acronym, some cut ("MULTI", "GO", "E") |
  | 3+ parts, last part with lowercase | 12,821 | The last part is always a country (Brasil 12,714, then 21 other names); the part before it is always an acronym, in capitals in 12,700 items and mixed in 121 ("UnB", "IF Goiano", "PUC-Rio") |
  | 2 parts, last part with lowercase | 9 | 3 are "name, Brasil"; 6 are a name cut in two ("zAgile, Inc", "Nanobrax, Soluções Tecnológicas Prest") |

  Countries are never written in capitals, which is what makes step 4 safe.
  In the three-part shape the acronym needs no test of form, so mixed-case
  acronyms are kept.
- **Known country names (step 6)**: a constant with the 22 country names found
  in the three-part texts of the 435 curricula (Brasil, Estados Unidos,
  Portugal, França, Peru, Alemanha, Espanha, Argentina, Grã-Bretanha,
  Colômbia, Canadá, África do Sul, Inglaterra, Holanda, Japão, Itália, Índia,
  Suíça, Escócia, Noruega, Barein, Paraguai), compared without case and
  accents. A name outside the list stays in the institution name, so nothing
  is lost and nothing lands in a wrong field (FR-005).
- **Result of the prototype**: country "Brasil" in 8,918 of 9,555 rows, empty
  in 555, 21 other countries in the rest; 0 rows with "IFES" as the country.
- **Alternatives considered**: trusting the library fields when the text has
  three parts (it is the four-part texts that break, but one rule for every
  shape is simpler to test); a full list of the world's countries (not needed
  for the three-part shape and the two-part shape has 9 items); testing the
  form of the acronym in the three-part shape (would reject "UnB").
- **Known limits**: "NIP do Brasil - Estudos e Projetos, NIP, S" (1 item, the
  country cut to "S") stores "S" as the acronym and "..., NIP" in the name; a
  name with commas and no acronym before the country ("A, B, Brasil") would
  store "B" as the acronym. No item of the second kind exists in the 435
  curricula.

## R3. What a repeat is

- **Decision**: after `split_institution`, an item is a repeat of another item
  of the same curriculum, or of a stored row of the same researcher, when the
  13 stored fields are equal: `institution`, `institution_name`,
  `institution_acronym`, `institution_country`, `period`, `start_year`,
  `end_year`, `bond`, `classification`, `work_regime`, `role_function`,
  `activity_type`, `current`. Comparison is exact (after the parser's own
  trimming and the column limits of R6).
- **Rationale**: FR-001. The four institution fields all derive from the text,
  so in practice the text and the nine other fields decide.
- **Measured**: 13,420 items give 10,778 different items; the old key gave
  7,855.
- **Alternatives considered**: comparing without case and accents (only 3
  pairs differ that way; merging near-equal rows is TD-023).

## R4. Items that carry only the institution

- **Decision**: `distinct_activities` drops an item whose seven detail fields
  (`period`, `start_year`, `end_year`, `bond`, `classification`,
  `work_regime`, `role_function`) are all empty when the same curriculum has
  an item with a filled detail field at the same institution text (after R2,
  step 1). Otherwise one such item per institution is kept. `current` and
  `activity_type` do not count as detail: `current` is false for these items
  and the type is constant.
- **Rationale**: clarification of 2026-11-11 (FR-002a). Measured: 2,634 such
  items; 1,223 institutions already have a filled activity in the same
  curriculum, 163 appear only this way.
- **Why in the parser step and not in the ingestion**: the decision depends on
  the other items of the same curriculum and on nothing in the database, so
  it is derived only from the source (Constitution, Data Integrity rule 2).
  When a curriculum downloaded again gains a filled activity at an
  institution it listed only by name, the institution-only row is no longer
  carried and the existing rule of spec 021 removes it.

## R5. The ingestion compares every stored field

- **Decision**: `ingest_professional_activities_task` builds its `seen`
  dictionary from the 13 fields of each stored row of the researcher (R3)
  instead of `(institution, start_year, activity_type)`, and looks each item
  up with the same 13 fields. A stored row that matches is carried; an item
  with no match is created and carried.
- **Rationale**: FR-001, FR-002, FR-011. A curriculum processed again finds
  every item in `seen` and writes nothing. The items arrive already distinct
  from `distinct_activities`, so one curriculum never creates two equal rows.
- **Alternatives considered**: deleting and re-creating the researcher's rows
  on every pass (would rewrite rows and change database ids on unchanged
  inputs, against Data Integrity rule 2).

## R6. Column limits

- **Decision**: the parser cuts `institution` at 500 characters (as today),
  `institution_name` at 255, `institution_acronym` at 100 and
  `institution_country` at 100, the limits of the domain entity.
- **Rationale**: SQLite does not enforce the limits, PostgreSQL would cut or
  refuse; cutting before the comparison keeps the parsed item equal to the
  stored row on both. Measured: no name reaches 255 characters today.

## R7. The permanent id

- **Decision**: in `_CHILD_PARTS` (`src/core/logic/horizon_identity.py`) the
  fields of `professional_activity` become `institution`, `period`,
  `start_year`, `end_year`, `bond`, `classification`, `work_regime`,
  `role_function`, `current`. The query of the id store
  (`src/adapters/database/horizon_id_store.py`) selects these columns.
- **Rationale**: FR-006. These are the fields that can differ between two
  stored rows of one researcher: the three derived institution fields follow
  from `institution`, and `activity_type` is constant. The hash still ignores
  case and accents (`normalize_text`), as every other id.
- **Measured**: 3 collision groups (6 rows) among the 9,555 rows, the three
  pairs that differ only in case or accents; today 114 rows carry a collision
  suffix (SC-004).
- **Alternatives considered**: keeping `institution_name` (two campuses or two
  institutions that share the first words of the name would collide);
  leaving `period` out (1,241 groups differ only there).

## R8. Old ids

- **Decision**: `child_decision` adds, for a professional activity, one extra
  candidate per parent: the id the row had under the old rule, built from the
  first comma part of the institution text (what the library gave as the
  name), `start_year`, `end_year`, `role_function` and `bond`. The existing
  `reconcile` step turns a candidate owned by exactly one current id into an
  alias; an old id that several new rows share, or that no row has, is
  recorded as `retired`.
- **Rationale**: FR-010 and Constitution, Data Integrity rule 4. No new alias
  mechanism is needed.
- **Measured** on the 7,855 old rows: 5,871 old ids resolve to one new id;
  761 are shared by several new rows (the activities that were collapsed) and
  1,223 belong to institution-only rows that are no longer stored; these
  1,984 are reported as retired.
- **Alternatives considered**: pointing a shared old id at the first of the
  new rows (which one is "first" depends on the order of the curriculum, and
  an alias that points to one of several equally valid targets is a guess);
  no legacy candidate (all 7,855 ids retired).

## R9. Reaching an existing database

- **Decision**: `HORIZON_RULE_VERSION` goes from 3 to 4. The existing guard
  of the weekly (`_reset_if_rule_version_changed`) rebuilds a database
  recorded under another version once, before the phases.
- **Rationale**: FR-009 and Data Integrity rule 3. Rows already collapsed
  cannot be restored by an incremental run, because unchanged curricula are
  skipped.
- **Note**: branch 033 (version 3) is not in the main branch yet. A database
  under version 2 that receives both branches is rebuilt once.

## R10. What consumes the fields

- **Decision**: no change to the exporter or to the export shape.
  `professional_activities_canonical.json` keeps its fields; the values of
  name, acronym and country change, `institution` loses a final full stop, and
  the file has about 9,555 rows instead of 7,855.
- **Checked**: the dashboard (`horizon_dashboard/src/lib/researcher-lattes-extras.ts`)
  reads `institution` and the period fields of this file; it does not read
  name, acronym or country. `PersonConsolidator` only moves the rows of a
  merged person to the winner and needs no change.

## R11. Out of scope, registered in the backlog

- The `atividades` list (3,580 items) and the `disciplinas` list (54 items):
  the table of the domain library has no column for them.
- 480 institution texts that arrive already cut from the library.
