# Research: Small fixes batch

**Feature**: `036-small-fixes-batch` | **Date**: 2026-11-12

All measurements are read-only, on the local database after the second run of
branch 035 (`db/horizon.db`, 18,429 persons, 11,876 advisorships, rule version
5), on the 435 curricula of `data/lattes_json/` and on the copy of the
database taken before branch 035 (`data/_backup_2026-11-11_pre035/`). Only
counts and public names are quoted; no CPF or phone number was read.

## R1. Where the student name comes from

- **Finding**: the student of a Lattes advisorship is read in two places of
  `src/adapters/sources/lattes_parser.py` (`_parse_items` and
  `_parse_generic_advisorships`): `item.get("orientando") or
  item.get("nome_do_orientado")`. The text goes unchanged to
  `LattesAdvisorshipMappingStrategy.map_row` (`student_names`, and the
  item's identity key), then to `AdvisorshipHandler._student_person`, which
  asks the `PersonMatcher` for the person and creates one when none matches.
- **Finding**: both parser paths keep an item only `if title and
  student_name`. An item with no student text is dropped today; it never
  becomes an advisorship.
- **Decision**: clean the name in the parser, with one pure function, so the
  strategy, the identity key, the matcher and the handler all see the clean
  name. This is where branch 034 put the institution rule.
- **Decision**: an item whose student text is not a name is kept, with no
  student (clarification of 2026-11-12). The parser's condition becomes "the
  item has a title and had a student text". An item with no student text at
  all is still dropped, as today.
- **Alternatives considered**: cleaning in the handler (the identity key and
  the 035 matching would still see the dirty text, and an incremental run and
  a rebuild could disagree); cleaning in the `PersonMatcher` (it would change
  names from every source, which the clarification excluded).

## R2. Exact counts in the curricula

11,601 advisorship items with a student text, 9,353 distinct texts. With the
rule of R3:

| Kind | Distinct texts | Items | What happens |
|------|----------------|-------|--------------|
| Name followed by the work title | 151 | about 152 | cut to the name |
| Name followed by the work title, several people before the full stop | 10 | 10 | left as today (several people) |
| Several people (`/`, `;`, "Co-orientador") | 148 | 148 | left as today |
| Not a name ("Turma \"C\" do 1º ano EBTT", "Acadêmicos do 6 periodo") | 4 | 4 | no person |
| Footnote number glued to the name ("Roseanne Gomes Gonçalves2") | 2 | 2 | number removed |
| Academic title ("Dr. Hamilton Carvalho Tolosa") | 1 | 1 | title removed |
| Link ("Silas Gambarine Soaresjavascript:void(0)") | 1 | 1 | link removed |
| Full stop after a one-word head ("Andre. \"ELABORAÇÃO ...") | 1 | 1 | left as today, counted |
| Needs no cleaning | 9,035 | about 11,280 | unchanged |

The spec's first estimate (240 work titles, 26 titles, 50 not a name) came
from a looser pattern over every person of the database, not only students.

Measured again with the final rule (tasks T003): work title 149 texts,
several people 317 texts. The 159 extra texts are comma lists ("A, B, C") or
surname-first forms ("Camata, Romulo"), which the table above counts as
"needs no cleaning"; they are stored as today in both cases.

## R3. The cleaning rule

- **Decision**: one pure function, `clean_student_name(raw)`, returning the
  name (or nothing) and the kinds of cleaning applied. Steps, in order:
  1. collapse spaces; an empty text gives no name, kind `empty`;
  2. remove a link: from `javascript:`, `http://`, `https://` or `www.` to
     the end, when something comes before it (kind `link`);
  3. a text with `/`, `;` or "co-orientador" is several people: returned as
     written (kind `several`);
  4. find the first full stop followed by a space that does not follow an
     initial (a token of one or two letters, or a token that itself holds a
     full stop, such as "S.N"). The part before it is the head. If the head
     has a comma or the word "e" between names, the text is several people
     and is returned as written (`several`). If the head has two words or
     more and no digit, the name is the head (`work_title`). Otherwise the
     text is kept whole (`uncut`);
  5. remove academic titles at the start and at the end, whole words only,
     with their full stop, gender mark and joining punctuation (`title`);
  6. remove digits glued to the end of the last word (`footnote`);
  7. if what is left has no letter, has a digit, or has one or two letters,
     there is no name (`not_a_name`).
- **Checked**: against the 9,353 distinct texts. Of the 161 texts with a work
  title, the 25 unusual heads (two words, more than six words, capitals) were
  read one by one: 15 are a real name, 10 hold several people and are left as
  today by step 4. No text that needs no cleaning is longer than 60
  characters, so no work title escapes the rule. Names with initials
  ("Eduarda Q. O. Senra", "MAURÍCIO G. PINHEIRO GUERRA") are not cut.
- **Spec refined**: the footnote number (2 texts) is removed instead of
  making the text "not a name", and a head with a comma or "e" is several
  people. Both follow the clarified rule "when unsure, leave as today".
- **Alternatives considered**: cutting at any full stop (breaks initials);
  using the item's title to find where the work title starts (the two texts
  differ: the field holds another title or a cut one).

## R4. Persons with extra text that are not Lattes advisorship students

With the same rule over every person of the database, 358 are flagged:

| Where the person is used | Kinds | Persons |
|--------------------------|-------|---------|
| Student of an advisorship | work title 160, several 147, not a name 6, title 1, link 1, uncut 1 | 316 |
| Advisor or co-advisor of a researcher's academic education, or nowhere else | title 27 ("Profª Drª ...", "Professora Dra"), not a name 14 ("Ph", "D", "1") | 41 |
| Member of a project team (Researcher or Coordinator) | not a name 8, several 1 | 9 |

- **Decision**: only the first group is in scope (clarification). The other
  two are registered in `docs/backlog.md` as a new entry: the advisor name of
  an academic education and the project team names keep their extra text.

## R5. Why the "JTC" fellowship has no sponsor

- **Finding**: `Fellowship.__init__` of the domain library sets
  `self.sponsor_id = sponsor_id` and then `self.sponsor = sponsor`. The ETL
  passes only `sponsor_id`, so `sponsor` is `None`, and assigning `None` to
  the relationship clears the foreign key when the row is written. Every new
  fellowship is stored without a sponsor.
- **Finding**: the sponsor appears later only by accident: when a second row
  uses the same fellowship, `_ensure_fellowship` finds it in the cache, sees
  `not fellowship.sponsor_id` and sets it. The two fellowships used by a
  single row have no sponsor in the database: "JTC" (CNPq in the report) and
  "PICTI" (Fapes in the report). The other 18 have one.
- **Finding**: in the next run the cache is filled from the database under
  `name::` (no sponsor). The row asks for `jtc::cnpq`, then for
  `jtc::id:3`; both miss, and a second "JTC" is created, again without a
  sponsor. "PICTI" was not stored twice only because its row was skipped as
  unchanged.
- **Decision**: in `_ensure_fellowship`, right after the fellowship is
  created, set its `sponsor_id` and update it when the row gave a sponsor
  (the same two lines the cache-hit branch already uses, which is known to
  store the sponsor). No library change.
- **Decision**: no extra lookup rule is needed for FR-014. With the sponsor
  stored, the preload registers `name::id:<sponsor>` and the row finds it; a
  row with no sponsor finds `name::`. A fallback "same name, stored without
  sponsor" would merge "PIBIC" of two sponsors if one of them were ever
  stored without one, so it is not added.
- **Backlog**: the constructor's behaviour is registered as a library limit.
- **Alternatives considered**: passing the sponsor object to the constructor
  (needs the organization entity loaded in the same session; the update is
  simpler and already proven); repairing the two stored rows in place (the
  rebuild of R9 does it).

## R6. Why a project PDF lands on an advisorship

- **Finding**: TD-038 said the enrichment "finds an advisorship by title".
  The enrichment already limits its title index to initiatives of type
  "Research Project" (`_load_research_project_names`). The cause is the
  stored type: `ProjectLoader` writes every row with its own
  `self.initiative_type`, which is always "Research Project". 11,367 of the
  11,876 advisorships are stored with that type (509 with "Advisorship"), so
  they are in the index.
- **Measured**: 4 advisorships hold PDF data today (ids 141, 171, 7250,
  8275; PJ 2449, 3879, 2804 by exact title, PJ 6020 by similar title). The
  ids of TD-038 (140, 170) were from the database before branch 035.
- **Decision**: the enrichment excludes from its title index, and from its
  code index, every initiative that has a row in `advisorships`. This is the
  fact that makes an initiative an advisorship, whatever its stored type.
- **Decision**: the stored type of advisorships is not changed here. It is
  a larger change (the exports and the dashboard may read the type) and is
  registered in `docs/backlog.md`.
- **Consequence**: the 4 PDFs match no research project. They follow the
  existing path of an unmatched PDF: `_ingest_new` does not create a project
  whose title is taken by another initiative (TD-020), so they are counted
  as skipped duplicates. The advisorships keep the description of their own
  source.
- **Alternatives considered**: correcting the type in the loader (out of
  scope, above); filtering by the stored type only (it is what fails today).

## R7. The order of the names in a SigPesq project row

- **Finding**: `ProjectLoader` asks `doc.unchanged(row_dict)` with the raw
  row; its hash covers every column as written.
- **Measured** on the database before branch 035, which holds two payloads
  for 26 of the 103 project rows: the only columns that differ are
  "Estudantes" (21 rows) and "Pesquisadores" (8 rows), and in all 29 cases
  the names are the same in another order.
- **Decision**: the mapping strategy may give the content to compare
  (`change_content(row)`); the loader uses it when the strategy has it,
  otherwise the row as today. `SigPesqProjectMappingStrategy` returns the row
  with "Estudantes" and "Pesquisadores" replaced by the sorted list of their
  names, split on `;` and stripped, as `_parse_names` already splits them.
  The payload stored for tracking stays the raw row.
- **Spec refined**: "Pesquisadores" is covered too, as the spec's edge case
  allowed when the same reordering is found.
- **Alternatives considered**: sorting inside `stable_hash` (it would change
  the hash of every document of every source); sorting the row itself (the
  tracking payload would no longer be the source row).

## R8. The run summary

- **Decision**: the parser returns, with each item, the kinds of cleaning
  applied to its student. The Lattes advisorship flow adds them up over the
  phase and logs one line next to the existing `log_match_summary`:
  `student names: title N, link N, work title N, footnote N, not a name N,
  several N, uncut N`. No new report file.

## R9. Existing databases and permanent ids

- **Finding**: a person without a Lattes id has a permanent id built from
  the name (rule `name`). About 155 persons change name, so their ids
  change; where the clean name already exists the two persons become one.
  The Lattes identity of an advisorship includes the student's name, so the
  ids of about 160 advisorships change too.
- **Decision**: `HORIZON_RULE_VERSION` goes from 5 to 6. The weekly's guard
  rebuilds an older database once. The id rules themselves do not change.
  Old ids are resolved by the existing candidate and alias history or
  reported as retired.
- **Finding**: the rebuild also removes the second "JTC", gives "JTC" and
  "PICTI" their sponsors and leaves no PDF data on advisorships.

## R10. Expected numbers after the rebuild

| What | Before | Expected |
|------|--------|----------|
| Persons with a work title, a link, a title or a footnote number, among advisorship students | about 155 | 0 |
| Persons created from a text that is not a name, among advisorship students | 4 | 0 |
| Persons, total | 18,429 | fewer, by up to about 160 (a clean name that already exists is the same person; the others are renamed) |
| Advisorships | 11,876 | about 11,876; the 4 items without a student may attach to an advisorship of the same title (branch 035, FR-008) |
| Advisorships without a student | 0 | up to 4 |
| Fellowships | 20 after a rebuild, 21 after the second run | 20 in both runs |
| Fellowships without a sponsor | 2 | 0 |
| Advisorships with PDF data | 4 | 0 |
| SigPesq project rows processed again for order only | 21 + 8 between two downloads | 0 |

## R11. Limits kept

- Fields with several people are stored as today (158 texts).
- One text with a one-word head before the full stop is stored as today.
- Persons with extra text from other fields (R4) are not cleaned.
- Advisorships keep the stored type "Research Project" (R6).
