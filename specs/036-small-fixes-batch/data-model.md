# Data Model: Small fixes batch

**Feature**: `036-small-fixes-batch`

No table, column or export field is added or changed. This file lists what
each fix reads and writes.

## 1. Student text and person (Fix 1)

| Thing | Where | Before | After |
|-------|-------|--------|-------|
| Student text | curriculum item, `orientando` or `nome_do_orientado` | as written | as written (the raw item is not changed) |
| Parsed item, `student_name` | output of `parse_advisorships` | the student text | the clean name, or `None` when the text is not a name |
| Parsed item, `student_name_kinds` | output of `parse_advisorships` | absent | tuple of the kinds applied (`title`, `link`, `work_title`, `footnote`, `not_a_name`, `several`, `uncut`); empty when nothing was done |
| Person | `persons.name` | the student text | the clean name; no row when there is no name |
| Advisorship member "Student" | `advisorship_members` | always present for a Lattes item | absent when the text is not a name |
| Lattes identity key of the item | in memory, feeds the permanent id | built with the student text | built with the clean name |

`CleanedName` (value returned by the rule): `name: Optional[str]`,
`kinds: tuple[str, ...]`.

Validation rules: see `contracts/small-fixes.md`, section 1.

## 2. Fellowship (Fix 2)

| Field | Rule |
|-------|------|
| `fellowships.name` | the programme in capitals, as today |
| `fellowships.value` | as today (merged from the claims of every row, branch 030) |
| `fellowships.sponsor_id` | the organization of the row's funding agency when the row gives one; set when the fellowship is created, not only when a second row uses it |

Identity of a fellowship inside a run (unchanged): name + sponsor, compared
without case and surrounding spaces. Same name with different sponsors: two
fellowships.

## 3. Project PDF and initiative (Fix 3)

| Thing | Before | After |
|-------|--------|-------|
| Title index of the enrichment | initiatives whose stored type is "Research Project" (includes 11,367 advisorships) | the same, minus every initiative with a row in `advisorships` |
| Code index of the enrichment | approved SigPesq project records and the initiative they point to | the same, minus every initiative with a row in `advisorships` |
| `initiatives.enrichment_json` of an advisorship | set on 4 advisorships | never set |
| `initiatives.description` of an advisorship | PDF text and "Programa: ..." written in turn | the description of its own source only |

The stored `initiative_type_id` of advisorships is not changed.

## 4. SigPesq project row (Fix 4)

| Thing | Before | After |
|-------|--------|-------|
| Content compared for "unchanged" | the row as read | the row with "Estudantes" and "Pesquisadores" as sorted lists of stripped names |
| Stored content hash of the document | hash of the row | hash of the compared content |
| Tracked payload (`source_records`) | the row as read | the row as read (unchanged) |
| What the row writes when processed | students and researchers in the order read | unchanged |

Every SigPesq project document gets a new hash once; the rebuild of the rule
version change covers it.

## 5. Rule version

| Field | Before | After |
|-------|--------|-------|
| `HORIZON_RULE_VERSION` | 5 | 6 |
| `horizon_meta` of a database built before | 5 | the weekly's guard rebuilds the database, then records 6 |
