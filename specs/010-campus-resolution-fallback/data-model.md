# Phase 1 Data Model: Campus Resolution

**Feature**: `010-campus-resolution-fallback` | **Date**: 2026-09-03

No table is created, altered, or dropped by this feature. Everything below
describes existing storage plus two new *values* written into an existing
tracking table.

## Existing entities used

### Campus — `organizational_units`

| Field | Notes |
|-------|-------|
| `id` | Primary key; also the deterministic tie-break key (R5) |
| `name` | 23 rows today: Serra, Vitória, Alegre, Vila Velha, Aracruz, Cefor, … |
| `organization_id` | IFES |

Referenced by `research_groups.campus_id`. This feature adds no foreign key of
its own to it.

### Initiative — `initiatives`

Holds both research projects (3,669) and advisorships (427) via
`initiative_type_id`. **Has no campus column, and this feature does not add
one** (research.md R1).

### Advisorship — `advisorships` / `advisorship_members`

`advisorship_members` carries `person_id` and `role_name`, with exactly two
role values in the current data: `Supervisor` (3,169 rows) and `Student`
(3,169 rows). This is the input to the fallback tier.

### Person — `persons`

No campus column. Campus is derived at export time only.

### Team linkage — `initiative_teams` → `teams` → `team_members`

The actual project-participation path (4,126 link rows).
`initiative_persons` exists but is **empty** and must not be relied on (R6).

## New values written into `attribute_assertions`

The table is unchanged; two new `attribute_name` values are recorded by
`ProjectLoader` through `tracking_recorder.record_attribute_assertions`.

| Column | Value |
|--------|-------|
| `source_record_id` | The SigPesq report row that stated the campus |
| `canonical_entity_type` | `initiative` or `advisorship` |
| `canonical_entity_id` | The initiative/advisorship id |
| `attribute_name` | `execution_campus_id` — and `execution_campus_name` |
| `value_json` | The resolved campus id (integer) / the raw stated name (string) |
| `is_selected` | `true` |
| `selection_reason` | `loader_selected_values` (the existing reason for this call site) |

**Validation rules**

- `execution_campus_id` is written only when the stated name resolved to an
  existing or newly created campus. An unresolvable name writes neither
  assertion and does not fail the row (FR-004).
- `execution_campus_name` is written whenever a non-empty name was stated, even
  if it did not resolve, so an unresolved name remains auditable.
- The pair is written regardless of whether the row named a research group
  (FR-001, FR-002) — that is the entire point of the change.

## Evidence model (export-time, in memory)

Campus attribution is a two-layer aggregation. Neither layer is persisted.

### Layer 1 — Direct evidence

A weighted count of `(entity, campus)` observations, exactly as today, extended
with the new sources:

| Evidence | Entity keyed | Weight |
|----------|--------------|--------|
| Campus is itself | `campus` | 1 |
| `research_groups.campus_id` | `research_group` | 1 |
| Group-linked initiative team | `initiative` | number of linked groups |
| **Asserted `execution_campus_id`** | `initiative`, `advisorship` | 1 |
| Group membership | `researcher` | 3 x number of group memberships (research.md R8) |
| **Team member of an initiative with an asserted execution campus** | `researcher` | number of such initiatives |
| Co-authored article of a group member | `article` | count |
| Group knowledge area | `knowledge_area` | count |

Group membership is weighted 3 against the execution campus weight of 1, so a
bare majority of executed projects cannot unseat the campus a person is
attached to; clear dominance still can.

The primary campus of an entity is the highest-weight campus in this layer,
ties broken by campus name, then campus id.

### Layer 2 — Inferred evidence (supervisor fallback)

Computed **after** Layer 1 is frozen, and only for people absent from Layer 1:

- For each advisorship, collect the Layer-1 campuses of its `Supervisor`
  members.
- Every member of that advisorship who has no Layer-1 campus receives one
  weighted observation per supervisor campus.
- The person's inferred campus is the highest-weight campus among those, ties
  broken by campus name, then campus id.

**Invariants**

1. A person present in Layer 1 is never affected by Layer 2 (FR-007).
2. Layer 2 reads only Layer-1 campuses, so an inferred campus can never be the
   input of another inference (FR-008) — no chains, no fixed-point iteration.
3. A person absent from both layers resolves to `null`; no placeholder and no
   real unit such as "Reitoria" is substituted (FR-010).
4. Both layers are order-independent, so two exports of an unchanged database
   agree exactly (SC-005).

## Downstream artifacts

`researchers_canonical.json` and the other canonical exports keep their current
shape: a `campus` object (or `null`). Consumers, including the Parquet exports
read by the dashboard, need no change.
