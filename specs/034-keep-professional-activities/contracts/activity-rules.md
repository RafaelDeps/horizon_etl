# Contract: professional activity rules

**Module**: `src/core/logic/professional_activity_rules.py` (new, pure, no I/O)

Both functions depend only on their arguments. The same input always gives
the same output, whatever the database holds and whatever order curricula
are processed in.

## `split_institution(text) -> (institution, name, acronym, country)`

Reads the three institution fields from the full institution text.

Steps:

1. `None` or a text with nothing but spaces and full stops: returns
   `("", None, None, None)`.
2. Trim the text and remove full stops and spaces at the end. The result is
   `institution`.
3. Split `institution` on commas, trim each part, drop empty parts. The
   name is always the text before the comma that precedes the parts taken as
   acronym or country, trimmed and otherwise as written (its own commas and
   spacing are kept).
4. One part: `name` is that part.
5. The last part has no lowercase letter: `acronym` is the last part, `name`
   is the text before it.
6. The last part has a lowercase letter and there are three parts or more:
   `country` is the last part, `acronym` the part before it, `name` the text
   before them.
7. The last part has a lowercase letter and there are two parts: when the
   last part, without case and accents, is in the known country names,
   `country` is the last part and `name` the first; otherwise `name` is the
   whole text.
8. A field not set by the step that applied is `None`.
9. `institution` is cut at 500 characters, `name` at 255, `acronym` at 100,
   `country` at 100.

Examples:

| Text | name | acronym | country |
|------|------|---------|---------|
| `Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo, IFES, Brasil` | `Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo` | `IFES` | `Brasil` |
| `Universidade Federal do Espírito Santo, UFES, Brasil` | `Universidade Federal do Espírito Santo` | `UFES` | `Brasil` |
| `Universidade Federal do Espírito Santo, UFES, Brasil.` | `Universidade Federal do Espírito Santo` | `UFES` | `Brasil` |
| `Universidade de Brasília, UnB, Brasil` | `Universidade de Brasília` | `UnB` | `Brasil` |
| `Suwannee American Cement, SAC, Estados Unidos` | `Suwannee American Cement` | `SAC` | `Estados Unidos` |
| `Imper - Imperial, Comércio, Industria e Serviços Ltda., IMPER, Brasil.` | `Imper - Imperial, Comércio, Industria e Serviços Ltda.` | `IMPER` | `Brasil` |
| `Quimivale Industrial Ltda, QUIMI` | `Quimivale Industrial Ltda` | `QUIMI` | `None` |
| `Cia Níquel Tocantins - Grupo Votorantim, Brasil` | `Cia Níquel Tocantins - Grupo Votorantim` | `None` | `Brasil` |
| `zAgile, Inc` | `zAgile, Inc` | `None` | `None` |
| `Universidade Federal de` | `Universidade Federal de` | `None` | `None` |
| `Rádio Universitária 104,7, UNI` | `Rádio Universitária 104,7` | `UNI` | `None` |

In every row `institution` is the text without the final full stop. The last
row shows that a comma inside the name is kept as written.

Properties:

- No part of the text is returned in two of the three fields.
- `split_institution(institution)` applied to its own `institution` output
  returns the same four values.

## `distinct_activities(items) -> list`

Takes the activity items of one curriculum, each already with the four
institution fields of `split_institution`, and returns the items to store,
in their first order of appearance.

1. An item equal to an earlier item in the 13 stored fields (`institution`,
   `institution_name`, `institution_acronym`, `institution_country`,
   `period`, `start_year`, `end_year`, `bond`, `classification`,
   `work_regime`, `role_function`, `activity_type`, `current`) is dropped.
2. An item is institution-only when `period`, `start_year`, `end_year`,
   `bond`, `classification`, `work_regime` and `role_function` are all empty.
3. An institution-only item is dropped when another item of the list with the
   same `institution` is not institution-only.

Examples (one curriculum, one institution):

| Items | Returned |
|-------|----------|
| A (2010–2012), B (2010–2015) | A, B |
| A (2010–2012), A again | A |
| institution-only, institution-only | one institution-only |
| institution-only, A (2010–2012) | A |
| A (2010–2012), institution-only at another institution | A, the institution-only item |

## Callers

- `LattesParser.parse_professional_activities` returns
  `distinct_activities` of its items, each built with `split_institution`.
- `ingest_professional_activities_task` treats a stored row of the researcher
  as the same activity only when the 13 fields are equal.
- `child_decision` hashes `institution`, `period`, `start_year`, `end_year`,
  `bond`, `classification`, `work_regime`, `role_function` and `current`,
  and adds the old-rule id as a candidate (research R8).
