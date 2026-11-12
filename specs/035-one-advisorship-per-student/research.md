# Research: One advisorship per student when titles repeat

**Branch**: `035-one-advisorship-per-student` | **Date**: 2026-11-11

All measurements are read-only queries on the local `db/horizon.db` after the
second run of 2026-11-11 (rule version 4): 10,260 advisorships, 11,532 tracked
Lattes advisorship items and 705 tracked SigPesq advisorship rows. An item's
title is compared as written (trimmed); a student name is compared after
`normalize_text` (case and accents ignored).

## R1. Where the wrong match happens

**Finding**: `ProjectLoader._lookup_existing_initiative`
(`src/core/logic/project_loader.py`) resolves an advisorship item in this
order: (1) `existing_by_identity[identity_key]`; (2) `existing_by_name[title]`;
(3) `_lookup_existing_by_exact_name(title)`. Steps 2 and 3 accept any
advisorship with that title.

Two details make it worse than a plain title match:

- `_register_existing_initiative` stores every created or updated advisorship
  under its **bare title**, also when the row was stored under a distinct name.
  `existing_by_name[title]` is therefore "the last advisorship of that title
  written in this process", and the next item of the same title lands on it.
- `AdvisorshipHandler.create_or_update` then replaces the Student member of
  the matched row (`_sync_advisorship_member` keeps one member per role).

**Decision**: for `model_class is Advisorship`, steps 2 and 3 are replaced by
one rule that looks at the student and the years (R3, R4). Step 1 stays.

## R2. The source identity is not stored

**Finding**: `get_existing_initiative_identity` reads
`initiative.metadata["source_identity"]`. The handler sets `metadata` on the
Python object, but the `initiatives` table has no column for it (columns: id,
name, status, description, start_date, end_date, initiative_type_id,
organization_id, parent_id, enrichment_json), and the entity belongs to the
domain library. For an advisorship loaded from the database the function
returns the identity built from the name alone.

So the identity key recognises an advisorship only inside the process that
created it. In a later run, a curriculum or a SigPesq report that changed is
matched by title only.

**Decision**: the new rule must work from what the database holds: the name,
the Student member and the dates. It cannot rely on the identity key.

**Alternatives considered**:
- Persist the identity key in a new column: rejected, the table belongs to the
  domain library (no library change).
- Read the identity back from `source_records` / `entity_matches`: rejected.
  The constitution allows only the published id history to feed a run; the
  tracking tables are an output.

## R3. Who is "the same student"

**Finding**: the stored side has one Student member per advisorship
(`advisorship_members`, 10,260 rows, 0 advisorships without one). The item side
has `student_names[0]` and, for SigPesq, `student_emails[0]`. Both the create
and the update path already resolve the item's student with
`person_matcher.match_or_create(name, email, strict_match=True)`.

Among the 8,115 distinct normalized names of stored students, none belongs to
more than one person.

**Decision**: the item's student is resolved with the same matcher call the
handler already makes, and the two students are the same when the person is
the same **or** the normalized names are equal. The person comparison keeps a
SigPesq row matched by e-mail on its advisorship when the person's stored name
is spelled differently; the name comparison satisfies FR-002 directly.

**Alternatives considered**:
- Names only: rejected. A person matched by e-mail may carry another spelling,
  and the whole SigPesq report is processed again whenever it changes: every
  such row would become a second advisorship.
- Person only: rejected, FR-002 asks for the name comparison.

No extra person is created: the matcher call is the one `create_or_update`
makes for the same item right after.

## R4. Which years are compared

The clarification of 2026-11-11 says: the same title and student in two
different years are two advisorships. The spec left "which year" to the plan.

**Finding**:

| Fact | Count |
|------|-------|
| Lattes items with a start year | 11,532 of 11,532 |
| Lattes items whose end year differs from the start year | 0 |
| SigPesq rows with start and end dates | 705 of 705, usually over two calendar years |
| (title, student) pairs present in both sources | 171 |
| ... comparisons where the Lattes year equals the SigPesq **end** year | 99 |
| ... where it equals the SigPesq start year | 79 |
| ... where it is outside the SigPesq period | 12 |

A Lattes item carries one year. A SigPesq row carries a period, and the
curriculum often records the year the work ended. Comparing start years would
give the same advisorship twice for 99 of the 171 pairs.

**Decision**: an item's years are the range from its start year to its end
year (one year when it has only one). Two ranges **differ** when both exist
and share no year. A missing range never differs.

- Lattes against Lattes: equal to "the years are different" (one year each).
- Lattes against SigPesq: the Lattes year inside the SigPesq period matches.
- SigPesq against SigPesq, same student: 30 pairs have two rows; 29 overlap
  (the student left and came back, or the row was entered twice) and stay one
  advisorship, 1 becomes two.

The stored side uses the years of the advisorship's `start_date` and
`end_date`, widened by every start and end date a source document claimed for
it (`source_field_claims`, branch 030); inside a run the loader also remembers
the ranges of the items it attached (R6), because the stored dates are decided
at the end of the document.

The claims were added after the second local run (T024). The field merge
stores the dates of the newest document only: an advisorship holding a SigPesq
row of 08/2015-07/2016 and the curriculum's items of 2015 and 2016 ended with
the dates of 2016, and when the curriculum was processed again its 2015 item
no longer matched and was created a second time (5 advisorships). The claims
keep what each source said, so the stored years stay 2015-2016. On the
database of the first run, 155 advisorships have wider years with the claims.
The claims are database state the run already reads to merge fields; they are
not a tracking output.

`FR-001a` and one assumption of the spec were reworded to say "share no year"
instead of "are not equal".

**Alternatives considered**:
- Start year only: rejected, 99 duplicates across sources.
- Ignore the year across sources and use it only inside one source: rejected,
  the stored advisorship does not say which source wrote it (R2).

## R5. Expected result

Clustering every tracked item by (title, student, overlapping years):

| | Today | Expected |
|--|-------|----------|
| Advisorships | 10,260 | about 11,890 |
| Lattes (title, student) pairs | 11,285 | each with at least one advisorship |
| Lattes pairs with more than one year | 97 | 98 more advisorships (89 pairs inside one curriculum) |
| Lattes pairs listed in more than one curriculum | 136 | one advisorship each, except 11 whose curricula give different years |
| SigPesq (title, student) pairs | 675 | 676 advisorships |

The expected count is a prediction from the tracked items, not a run; the
rebuild downloads some curricula again.

## R6. Finding the candidates

**Finding**: the advisorships of one title are the row named exactly as the
title and the rows named `<title> | Orientacao ...` (652 today). The distinct
name is always the title plus a suffix that starts with ` | Orientacao`.

**Decision**: the loader keeps an index `base title -> stored advisorships`,
filled once per loader from one query (advisorship id, name, start and end
dates, Student member's person id and name) and updated after each item it
writes. The base title of a name is the text before the last ` | Orientacao`.
`reset_caches` drops the index with the others.

The index, not the database, answers inside a run, because Student members of
existing advisorships are written at the end of the phase (`defer_members`)
and the dates at the end of the document.

**Alternatives considered**:
- A `LIKE` query per item: rejected, 12,000 queries, and blind to deferred
  members.
- Keep `existing_by_name` for advisorships: rejected, it holds one row per
  title (R1).

## R7. Choosing among several candidates

**Decision** (the contract in `contracts/advisorship-matching.md`):

1. Candidates of the same student whose years do not differ. With several:
   first those whose years are known and overlap, then the earliest first
   year, then the row with the bare title, then the lowest row id.
2. Otherwise a candidate without a student (none exists today; kept for
   FR-008).
3. Otherwise no match: the handler creates a new advisorship.

An item without a student is matched to the bare-title row when there is one
(FR-008). No tracked item is in that situation: the Lattes items all carry a
student and the SigPesq strategy drops a row without one.

The lowest row id is only the last tie-break between rows that are equal in
student and years; it does not reach the permanent id (R9).

## R8. The name of a matched advisorship is kept

**Finding**: with a matched row, `create_or_update` calls
`_resolve_persisted_title(title, current_id=row.id)`. For a row stored under a
distinct name the bare title is in use by another row, so a new distinct name
is built from the incoming item and the row is renamed. The advisor's and the
co-advisor's curriculum, or SigPesq and Lattes, can give different suffixes
(another year, a SigPesq id), so the row would be renamed back and forth, and
a rename can hit the unique-name rule.

**Decision**: when the loader passes a matched advisorship whose base title is
the item's title, the handler keeps the stored name. A row matched by identity
whose title really changed is renamed as today. A new advisorship is named as
today: the bare title when free, otherwise
`<title> | Orientacao <student> | <year> | sigpesq <Id>`.

The distinct name cannot collide with a row the rule rejected: a row with the
same title, student name and start year is a match by R3 and R4.

Which advisorship of a title holds the bare title depends on which was written
first; the spec accepts that (Assumptions). The team of an advisorship is
named after the advisorship (`initiative.name[:200]`), so each new advisorship
gets its own team.

`_free_name_held_by_advisorship` (TD-029) is unchanged: a project still takes
the bare title and the advisorship receives a distinct name; the index is
keyed by base title, so the rename does not move the entry.

## R9. Permanent ids and the rule version

**Finding**: `initiative_decision` gives an advisorship the id of its best
source key: SigPesq workplan (592 advisorships), Lattes identity key (9,665),
PJ code (2, TD-038) and, last, type + name (1). The rules are not changed.

After the split each advisorship is fed by its own source records, so it gets
the id of its own key. A merged advisorship of today published the id of one
of its keys; `reconcile` gives that id to the advisorship that now owns the
key, and the other split advisorships receive new ids. Old ids are expected to
stay valid; any that does not is recorded as an alias or as retired by the
existing mechanism (FR-015), and the quickstart counts them.

The one advisorship identified by type + name is the only id that could
depend on a distinct name.

**Decision**: `HORIZON_RULE_VERSION` goes from 4 to 5 with a comment line for
branch 035. The existing guard of the weekly (`_reset_if_rule_version_changed`)
rebuilds an older database once. No id rule changes.

**Alternatives considered**:
- No version bump: rejected. The persistent database would keep the merged
  advisorships, and a rebuild would give different entities than the
  incremental database (constitution, Data Integrity rule 3).

## R10. What needs no change

- **Document skip (spec 021)**: the loader records, per item, the title looked
  up and the advisorship found (`initiative_reference_key(name)`), or
  `not_found`. An unchanged document is processed again only if its target is
  gone or a new initiative has a name close to a title it did not find. A
  distinct name is not close to the bare title, so the second run still skips
  unchanged documents (checked by SC-007).
- **Field merge (branch 030)**: status, dates, description and `cancelled` are
  claimed per advisorship. After the split a cancelled SigPesq row and the row
  of the new student claim on different advisorships (FR-010).
- **Members**: one Student and one Supervisor per advisorship, as today.
- **Exports and the dashboard**: same shape; names with the suffix are already
  exported.
- **Projects and other initiatives**: the new rule runs only for
  `model_class is Advisorship`.
- **SigPesq collection**: sequential, untouched.

## R11. Known limits (recorded, not solved here)

- **Order across sources**: "share a year" is not transitive. For 7
  (title, student) pairs present in both sources with more than one Lattes
  year, the result can depend on whether the SigPesq row or the Lattes items
  were stored first. The weekly always loads SigPesq before Lattes, in a
  rebuild and in an incremental run, so both give the same result unless a
  SigPesq row for such a pair first appears in a later report.
- **Advisor and co-advisor with different years**: 11 pairs become two
  advisorships (accepted in the clarification).
- **A student spelled differently in two curricula**: two advisorships (spec,
  Edge Cases).
- **Titles that differ only in case or punctuation**: 6 Lattes items are
  attached to an advisorship whose stored title is written another way (the
  same work listed twice in one curriculum; matched by the identity key inside
  the process). The index is keyed by the exact title, so the result depends
  on which spelling is processed first. Found in T024 (one advisorship was
  removed and created again in the second run).
- **Persons merged after the load**: 2 Lattes items are attached to an
  advisorship that, after `consolidate_duplicates` merged two persons, has a
  twin of the same title, student and years; when their curriculum is
  processed again they move to the twin.
- **`make ci-check`** fails on the repository before this branch (spec 033
  T026); touched files are checked with black, isort and flake8.
