# Data Model: One advisorship per student when titles repeat

No table, column or export field is added or changed. This document describes
the existing rows the rule reads and the in-memory structures it adds.

## Stored rows (unchanged schema)

| Table | Fields the rule reads | Notes |
|-------|----------------------|-------|
| `initiatives` | `id`, `name`, `start_date`, `end_date` | `name` is unique (domain library). An advisorship is an `initiatives` row with a row of the same id in `advisorships`. |
| `advisorships` | `id` | Tells which initiatives are advisorships. `cancelled` and `cancellation_date` stay written as today. |
| `advisorship_members` | `advisorship_id`, `person_id`, `role_name` | One `Student` and one `Supervisor` row per advisorship. |
| `persons` | `id`, `name` | Name of the Student member. |
| `source_field_claims` | `entity_id`, `value_json` for `entity_type = 'advisorship'` and `field` in `start_date`, `end_date` | The dates each source document said (branch 030). Read once to widen the years. |
| `horizon_meta` | rule version | 4 before, 5 after. |

## Names

| Form | Example | When |
|------|---------|------|
| Bare title | `Estágio Supervisionado Obrigatório` | The first advisorship written with that title. |
| Distinct name | `Estágio Supervisionado Obrigatório \| Orientacao Maria Silva \| 2020` | Every later advisorship of the title; `\| sigpesq <Id>` is added for a SigPesq row. Format unchanged. |

**Base title**: the name without its suffix, that is, the text before the last
` | Orientacao`. A name without the marker is its own base title.

## In-memory structures (new)

### StoredAdvisorship

One advisorship as the rule sees it.

| Field | Type | Source |
|-------|------|--------|
| `id` | int | `initiatives.id` |
| `name` | str | `initiatives.name` |
| `student_id` | int or None | Student member's `person_id` |
| `student_name` | str | Student's name after `normalize_text`; empty when there is none |
| `years` | (first, last) or None | Years of `start_date` and `end_date`, widened with every start and end date claimed for the advisorship in `source_field_claims`; widened in the run with the years of each item attached |

### Advisorship index

`base title -> list of StoredAdvisorship`. One per `ProjectLoader`, filled on
first use from one query, updated after each advisorship item is written,
dropped by `reset_caches`.

### Item side

| Value | Source |
|-------|--------|
| title | `project_data["title"]` |
| student person | `person_matcher.match_or_create(student_names[0], email=student_emails[0], strict_match=True)`, the call the handler already makes |
| student name | `normalize_text(student_names[0])` |
| years | years of `project_data["start_date"]` and `project_data["end_date"]` |

## Rules

- **Same student**: same person id, or equal non-empty normalized names.
- **Years differ**: both ranges exist and share no year.
- **Match**: same base title, same student, years do not differ (contract).
- **One student per advisorship**: an item never replaces the Student of an
  advisorship of another student (FR-006).

## State changes of one item

```text
item (title, student, years)
  ├─ identity key seen in this process ──────────────► update that advisorship
  ├─ a stored advisorship matches (contract) ────────► update it, name kept
  └─ none matches ───────────────────────────────────► create
        ├─ bare title free ──► name = title
        └─ bare title taken ─► name = title | Orientacao student | year | sigpesq Id
```

## Permanent ids

Rules unchanged (`initiative_decision`). Each advisorship takes the id of its
own best source key. On the rebuild, an id published by a merged advisorship
stays with the advisorship that owns its key; the others get new ids; an id no
advisorship owns is reported as retired.
