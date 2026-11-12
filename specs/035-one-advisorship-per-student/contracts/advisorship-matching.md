# Contract: advisorship matching rules

Module: `src/core/logic/advisorship_matching.py` (new, pure: no database, no
I/O, standard library plus `normalize_text`).

## `base_title(name) -> str`

The title an advisorship name was built from.

| Input | Output |
|-------|--------|
| `"Iniciação Científica"` | `"Iniciação Científica"` |
| `"Iniciação Científica \| Orientacao Maria Silva \| 2020"` | `"Iniciação Científica"` |
| `"Estudo X \| Orientacao Ana \| 2019 \| sigpesq 2320"` | `"Estudo X"` |
| `"A \| Orientacao B \| Orientacao C \| 2020"` | `"A \| Orientacao B"` (last marker) |
| `"Estudo X \| Orientacao"` | `"Estudo X"` |
| `None`, `""` | `""` |

## `year_range(start, end) -> (first, last) or None`

`start` and `end` are a date, a datetime, an ISO date text, a year or None.

| start | end | Output |
|-------|-----|--------|
| 2019-08-01 | 2020-07-31 | (2019, 2020) |
| 2020-01-01 | None | (2020, 2020) |
| None | 2020-12-31 | (2020, 2020) |
| None | None | None |
| 2021-01-01 | 2020-12-31 | (2020, 2021) (ordered) |

## `years_differ(a, b) -> bool`

True only when both ranges exist and share no year.

| a | b | Output |
|---|---|--------|
| (2019, 2019) | (2020, 2020) | True |
| (2019, 2020) | (2020, 2020) | False |
| (2019, 2020) | (2020, 2021) | False |
| (2019, 2019) | None | False |
| None | None | False |

## `same_student(item_id, item_name, stored_id, stored_name) -> bool`

Names arrive normalized. True when both ids exist and are equal, or when both
names are non-empty and equal.

| item | stored | Output |
|------|--------|--------|
| id 7, "maria silva" | id 7, "maria s. silva" | True (same person) |
| id None, "maria silva" | id 9, "maria silva" | True (same name) |
| id 7, "maria silva" | id 9, "joao souza" | False |
| id None, "" | id 9, "joao souza" | False |

## `pick_match(item_student_id, item_student_name, item_years, candidates) -> StoredAdvisorship or None`

`candidates` are the stored advisorships with the item's base title.

1. Item with a student: among candidates of the same student whose years do
   not differ, return the first by this order: (a) years known on both sides
   and overlapping before a missing range; (b) earliest first year, a missing
   range last; (c) the candidate whose name is the bare title; (d) lowest id.
2. Item with a student and no result in 1: a candidate without a student
   (empty name and no id), by order (c), (d); else None.
3. Item without a student: the candidate whose name is the bare title; else
   None.

| Candidates (student, years, name) | Item (student, years) | Result |
|-----------------------------------|-----------------------|--------|
| A: ana, (2020, 2020), bare | bia, (2020, 2020) | None |
| A: ana, (2020, 2020), bare | ana, (2020, 2020) | A |
| A: ana, (2019, 2019), bare | ana, (2020, 2020) | None |
| A: ana, (2019, 2019); B: ana, (2020, 2020) | ana, (2020, 2020) | B |
| A: ana, (2019, 2020) | ana, (2020, 2020) | A |
| A: ana, None; B: ana, (2020, 2020) | ana, (2020, 2020) | B |
| A: ana, (2019, 2019); B: ana, (2021, 2021) | ana, None | A |
| A: no student, None, bare | ana, (2020, 2020) | A |
| A: ana, (2020, 2020), bare | no student, (2020, 2020) | A |
| A: ana, (2020, 2020), distinct name | no student, None | None |
| none | ana, (2020, 2020) | None |

## Loader and handler behaviour (integration contract)

- `ProjectLoader._lookup_existing_initiative`, for an advisorship item: the
  identity key seen in this process first; then `pick_match` over the index of
  the item's title. The lookups by exact and by stored name are not used for
  advisorships. Other initiative types are resolved as before.
- The years of a stored advisorship are those of its stored dates widened by
  every start and end date claimed for it in `source_field_claims`.
- After an advisorship item is written, its advisorship is in the index with
  its student and with years widened by the item's years.
- `AdvisorshipHandler.create_or_update` with a matched advisorship whose base
  title is the item's title keeps the stored name.
- `AdvisorshipHandler.create_or_update` without a matched advisorship names
  the new one as today.
- An item never changes the Student member of an advisorship of another
  student.
- `HORIZON_RULE_VERSION == 5`; a database recorded under 4 is reset by the
  weekly guard.
