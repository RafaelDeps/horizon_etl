# Feature Specification: Every professional activity is kept, with the right institution

**Feature Branch**: `034-keep-professional-activities`

**Created**: 2026-11-11

**Status**: Draft

**Input**: User description: "Keep every Lattes professional activity and read the institution's name, acronym and country correctly. Different activities of one researcher at the same institution and start year become one row today, and the institution's name, acronym and country are swapped when the name has a comma. An activity is a repeat only when it equals a stored one in every stored field; name, acronym and country are read from the full institution text; the permanent id follows the corrected fields. State how the fix reaches a persistent database."

## Background

A Lattes curriculum lists the researcher's professional activities: where they
worked, in which period, with which bond, classification, work regime and
role. Two defects change what reaches the database.

**Defect 1: different activities become one.** An activity is taken for a
repeat of a stored one when the researcher, the institution, the start year
and the kind are the same. The kind is the same for every item ("Atuação
profissional"), so in practice the institution and the start year decide. The
first item is kept and the others are dropped, even when they describe another
period, bond or classification.

**Defect 2: the institution's name, acronym and country are swapped.** The
curriculum data arrives with the institution text already cut at each comma,
so a name that has commas is cut in the wrong places:

| Field | What arrives for "Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo, IFES, Brasil" | What it should be |
|-------|------------------------------|-------------------|
| Name | Instituto Federal de Educação | Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo |
| Acronym | Ciência e Tecnologia do Espírito Santo | IFES |
| Country | IFES | Brasil |

The full institution text arrives intact, so the three fields can be read from
it. Some texts end with a full stop ("..., UFES, Brasil.").

The permanent id of an activity is built from the institution name, the start
year, the end year, the role and the bond, so it carries the cut name: an IFES
activity is identified by "instituto federal de educacao".

Measured on the 435 curricula of the 2026-11-10 local run:

- 13,439 activity items in the curricula, 13,420 of them with an institution;
  7,855 rows in the database.
- Of the 5,565 items dropped, 2,923 differ from the kept row in a stored field
  and 2,642 are exact repeats (nearly all without period and start year).
- In the groups that lose data, the field that differs is the period in 1,241
  groups, the end year in 822, the current flag in 360, the classification in
  217, the bond in 136 and the work regime in 54.
- 5,534 curriculum items arrive with name, acronym and country swapped; 2,260
  database rows store "IFES" as the country.

## Clarifications

### Session 2026-11-11

- Q: What happens to curriculum items that carry only the institution (no period, start year, end year, bond, classification, work regime or role; 2,634 items, 1,386 rows today)? → A: Keep one such row per institution only when the curriculum has no other activity at that institution (163 rows); when it has one, the institution-only item adds nothing and is not stored (1,223 rows today).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every different activity of a researcher is stored (Priority: P1)

As a consumer of the exported data, I want every professional activity listed
in a curriculum to exist as its own record, so that a researcher's career is
complete: every period, bond and classification at an institution, not only
the first one listed.

**Why this priority**: this is data loss. 2,923 activities listed in the
curricula are missing from the database today.

**Independent Test**: ingest one curriculum with two activities at the same
institution and the same start year that differ in the period; two activities
exist afterwards, each with its own period.

**Acceptance Scenarios**:

1. **Given** a curriculum with two activities at the same institution and start year but different periods, **When** it is ingested, **Then** two activities exist, each with its own period.
2. **Given** a curriculum with two activities at the same institution and start year that differ only in the bond, the classification, the work regime, the role, the end year or the current flag, **When** it is ingested, **Then** two activities exist.
3. **Given** a curriculum that lists the same activity twice, equal in every stored field, **When** it is ingested, **Then** one activity exists.
4. **Given** a curriculum with several items for one institution that carry only the institution, and no other activity at that institution, **When** it is ingested, **Then** one activity exists for that institution.
5. **Given** a curriculum with an item that carries only the institution and another activity at the same institution with a period or any other filled field, **When** it is ingested, **Then** only the filled activity exists for that institution.
6. **Given** the 435 curricula of the 2026-11-10 run, **When** the database is rebuilt from scratch, **Then** no curriculum activity with a filled field that differs from every stored activity of its researcher is missing (2,923 today) and the database holds about 9,555 activities (7,855 today).

---

### User Story 2 - Name, acronym and country of the institution are the right ones (Priority: P1)

As a consumer of the exported data, I want the institution's name, acronym and
country to be what the curriculum says, so that I can group activities by
institution or by country without finding "IFES" among the countries.

**Why this priority**: it is wrong data in 2,260 stored rows, including every
activity at the institution the project is about.

**Independent Test**: ingest an activity whose institution text is "Instituto
Federal de Educação, Ciência e Tecnologia do Espírito Santo, IFES, Brasil";
the stored name is the full name, the acronym is "IFES" and the country is
"Brasil".

**Acceptance Scenarios**:

1. **Given** an institution text whose name has commas, followed by an acronym and a country, **When** the activity is ingested, **Then** the name keeps its commas, and the acronym and the country are the last two parts.
2. **Given** an institution text of the form "name, acronym, country" without commas in the name ("Universidade Federal do Espírito Santo, UFES, Brasil"), **When** it is ingested, **Then** the three fields are stored as today.
3. **Given** an institution text that ends with a full stop ("..., UFES, Brasil."), **When** it is ingested, **Then** the country is "Brasil" and the activity is the same as one written without the full stop.
4. **Given** an institution text with a name and an acronym only ("Quimivale Industrial Ltda, QUIMI"), **When** it is ingested, **Then** the acronym is stored and the country is empty.
5. **Given** an institution text with a name and a country only ("Cia Níquel Tocantins - Grupo Votorantim, Brasil"), **When** it is ingested, **Then** the country is stored and the acronym is empty.
6. **Given** an institution text with one part only, **When** it is ingested, **Then** the name is that text and the acronym and the country are empty.
7. **Given** the 435 curricula of the 2026-11-10 run, **When** the database is rebuilt from scratch, **Then** no activity stores an acronym or a piece of the name as the country (2,260 rows store "IFES" today).

---

### User Story 3 - The permanent id of an activity follows the corrected data (Priority: P2)

As a consumer who keeps references to activities, I want each activity to have
its own permanent id built from the right institution, so that two activities
of one researcher never share an id and an id does not depend on a cut name.

**Why this priority**: the ids are a published contract; with more rows per
researcher, an id that ignores the fields that tell two activities apart would
produce many colliding ids.

**Independent Test**: build ids for two activities of one researcher at the
same institution that differ only in the period; the two ids are different and
neither needs a collision suffix.

**Acceptance Scenarios**:

1. **Given** two activities of one researcher that differ in any stored field, **When** permanent ids are assigned, **Then** the ids are different without a collision suffix.
2. **Given** an activity at an institution whose name has commas, **When** its permanent id is assigned, **Then** the id is built from the full institution, not from the first piece of the name.
3. **Given** the 435 curricula of the 2026-11-10 run, **When** the database is rebuilt from scratch, **Then** the number of activities whose id needs a collision suffix is not higher than today (114).
4. **Given** an activity id published before the change, **When** the database is rebuilt, **Then** the old id still resolves to the activity as an alias, or is reported as retired; it does not disappear without a record.

---

### User Story 4 - A database filled before the fix is repaired, and nothing else moves (Priority: P3)

As the maintainer of the persistent database, I want the fix to reach a
database that was filled before it and to change only professional activities,
so that the weekly run does not keep the dropped activities missing and no
other data is affected.

**Why this priority**: the rule alone fixes new databases; without this story
the persistent database of the weekly run would keep the old rows.

**Independent Test**: start a run on a database written under the old rules;
it is rebuilt before use; afterwards the numbers of User Stories 1 and 2 hold
and a second run over the same inputs writes no activity change.

**Acceptance Scenarios**:

1. **Given** a database written under the old rules, **When** a run starts, **Then** the database is recognised as written under older rules and is rebuilt before use, as the constitution requires for a change of the identity rules.
2. **Given** a database rebuilt under the new rules, **When** a second run processes a curriculum that did not change, **Then** no professional activity is created, changed or removed.
3. **Given** a database rebuilt under the new rules and an incremental database that received the same curricula under the new rules, **When** they are compared, **Then** they hold the same activities.
4. **Given** the rebuild, **When** the other kinds of data are counted, **Then** awards, academic educations, articles, technical productions, projects and advisorships have the counts of the run before the change, except for curricula that changed between downloads.

---

### Edge Cases

- An activity item without an institution text: it is skipped, as today (19 items).
- A curriculum downloaded again that now has a filled activity at an institution it listed only by name before: the institution-only row is removed, by the existing rule for items a curriculum no longer carries.
- An institution text that arrives already cut in the curriculum data ("Universidade Federal de", 480 items): it is stored as it arrives; the missing part cannot be recovered here.
- An institution text whose last part is written in capitals and could be an acronym or a country abbreviation ("..., EUA"): the rule that tells an acronym from a country is fixed in the plan and measured on the 435 curricula; an unclear part is never copied into two fields.
- An institution name that itself contains commas and has no acronym ("Imper - Imperial, Comércio, Industria e Serviços Ltda., Brasil"): the name keeps every part before the country.
- An institution text with a full stop inside the name ("... Ltda., IMPER, Brasil."): only the full stop at the very end of the text is removed.
- Two activities that differ only in upper and lower case or in accents of a text field: they are different stored values and stay two rows; merging near-equal rows is the subject of TD-023 and is out of scope.
- An activity whose period is "Atual": the end year is empty and the current flag is set, as today.
- A researcher whose curriculum is downloaded again with one activity removed: the activity is removed from the database by the existing rule for items a curriculum no longer carries.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat a curriculum activity as a repeat of a stored activity of the same researcher only when the two are equal in every stored field: institution, name, acronym, country, period, start year, end year, bond, classification, work regime, role, kind and current flag.
- **FR-002**: An activity that is not a repeat under FR-001 MUST be stored as its own record; exact repeats MUST stay one record.
- **FR-002a**: An item that carries only the institution (no period, start year, end year, bond, classification, work regime or role) MUST be stored, once per researcher and institution, only when the curriculum has no other activity at that institution; otherwise it MUST NOT be stored. The institution is compared after FR-004.
- **FR-003**: The institution's name, acronym and country MUST be read from the full institution text, from the end: the country, then the acronym when the part has the form of an acronym, and everything before as the name, with its commas.
- **FR-004**: A full stop at the end of the institution text MUST be ignored, in the three fields and in the stored institution text, so the same institution written with and without it is one value.
- **FR-005**: When the institution text has no country or no acronym, that field MUST be empty; a part of the text MUST NOT be stored in a field it does not belong to, and no part is stored in two fields.
- **FR-006**: The permanent id of an activity MUST be built from the corrected institution and from every field that can tell two activities of one researcher apart, so two different stored activities do not share an id.
- **FR-007**: The same rules MUST apply where activities are read from the curriculum, where they are compared with the stored ones and where their permanent ids are built, so an incremental run and a rebuild from the same curricula give the same activities and the same ids.
- **FR-008**: The curriculum item as downloaded MUST stay unchanged in the stored curriculum files; nothing from the source is altered.
- **FR-009**: Because this changes how activities are identified, the recorded version of the identity rules MUST change, and a database recorded under the earlier version MUST be rebuilt before use, as the constitution requires.
- **FR-010**: Permanent ids published before the change MUST stay resolvable as aliases of the activities that replace them, or be reported as retired; none is dropped without a record.
- **FR-011**: Processing a curriculum that did not change a second time on a database built under the new rules MUST write no professional activity change.
- **FR-012**: The lists of tasks ("atividades") and of courses taught ("disciplinas") that some activity items carry are out of scope and MUST be registered in the backlog, together with the institution texts that arrive already cut.
- **FR-013**: The feature MUST work in a local run and in the GitHub Actions weekly workflow, with no new setting.
- **FR-014**: The change MUST be made inside this project only: no change to third-party libraries and no Docker change.

### Key Entities

- **Professional activity**: one bond of a researcher with an institution, with a period (start year, end year or current), a bond type, a classification, a work regime and a role. A researcher may have several at the same institution.
- **Curriculum activity item**: one professional activity as listed in one researcher's Lattes curriculum.
- **Institution text**: the institution as written in the curriculum, in the order name, acronym, country, separated by commas; the name may itself contain commas.
- **Permanent id**: the published identifier of an activity, derived from its researcher and from the activity's own data.
- **Identity rule version**: the recorded version of the rules that decide when two records are the same entity; a database is valid only for the version it was built with.

## Success Criteria *(mandatory)*

### Measurable Outcomes

Measured on a from-scratch weekly run over the curricula of 2026-11-10 (435).
The run downloads part of the curricula again, so the targets that are counts
are approximate and the targets that are zero are exact:

- **SC-001**: 0 curriculum activities with a filled field that differ from every stored activity of their researcher are missing from the database (2,923 before).
- **SC-002**: The database holds one activity per different curriculum item with a filled field (about 9,392) plus one per institution that a curriculum lists only by name (about 163): about 9,555 (7,855 before). 0 institution-only rows exist beside a filled activity of the same researcher and institution (1,223 before).
- **SC-003**: 0 activities store an acronym or a piece of the name as the country (2,260 rows store "IFES" before); the IFES example stores the full name, the acronym "IFES" and the country "Brasil".
- **SC-004**: The number of activities whose permanent id needs a collision suffix is not higher than before (114).
- **SC-005**: The counts of awards, academic educations, articles, technical productions, projects and advisorships are the same as in the run before the change, except for items of curricula that were downloaded again and changed.
- **SC-006**: A second run writes no professional activity change for the curricula that did not change.
- **SC-007**: A database built before the change is never used incrementally: it is rebuilt first, in the local run and in the weekly workflow.

## Assumptions

- A rebuild is the way the fix reaches an existing database. Activities already dropped cannot be restored by an incremental run that skips unchanged curricula, and the constitution (Data Integrity & Persistent Incremental Ingestion, rule 3) already requires a rebuild when the identity rules change. No in-place repair is built.
- This branch starts from branch 033, whose change of the identity rules is not yet in the main branch; the two changes reach a persistent database with one rebuild if they are released together.
- The weekly run of the fork and any upstream run happen only with the maintainer's approval; the rebuild they need is part of that approval.
- "Every stored field" means the fields the database keeps for an activity today. Two items that differ only in the lists of tasks or courses, which are not stored, are exact repeats and stay one record.
- The items that carry only the institution (2,634) hold no information beyond it in the stored fields; 334 of them carry a list of tasks and 57 a list of courses, which are out of scope. Not storing such an item beside a filled activity at the same institution loses nothing that is stored today.
- The form of an acronym (a short part written in capitals, such as "IFES", "UFES", "QUIMI") is defined precisely in the plan and checked against the institution texts of the 435 curricula.
- Rows that differ only in case or accents stay separate; merging them belongs to TD-023.
- Only professional activities from Lattes curricula are in scope; no other source supplies them today.
