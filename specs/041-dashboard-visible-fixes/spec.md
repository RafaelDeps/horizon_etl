# Feature Specification: Dashboard-Visible Data Fixes and Slack Notices on Main Only

**Feature Branch**: `041-dashboard-visible-fixes`

**Created**: 2026-11-17

**Status**: Draft

**Input**: User description: "Fix the data errors that are easy to spot on the dashboard (without changing any key rule), and limit the Slack weekly notices to the main branch." (full description in the `/speckit-specify` request of 2026-11-17)

## Context

A review of the published exports on the RafaelDeps fork main (commit `c5ffe55`, 2026-11-17) listed data errors that anyone browsing the dashboard notices at once: "people" called "Dr" or "Prof", one person whose name is two students joined by "/", a person who collaborates with themselves, a coordinator listed twice in one team, titles with "?" where a dash should be, articles from year 0, and dates that end before they start. This spec fixes these errors where they are made, at ingestion. A curriculum is reprocessed only when its content or the rule version changes, so the fixes raise the rule version and the persistent database is rebuilt once, as in spec 036; the id rules themselves do not change.

Errors that need a change to the id rules (advisorships of different students merged into one, one person under two spellings, Lattes advisorships stored with the project type, keys of knowledge areas, organizations and productions, Lattes × SigPesq advisorships whose titles differ only in case) are left to later specs.

The same spec also limits the Slack notices added in spec 040 to the main branch. This spec and the next ones need many weekly runs on feature branches, and those runs must not post to the shared channel.

Figures below come from the published exports of 2026-11-17 and the local database of 2026-11-16.

## Clarifications

### Session 2026-11-17

- Q: How should the 3 SigPesq workplans that end before they start be shown? → A: Keep them as they are; the error is in the source, not in the ETL.
- Q: How should the article with an empty title be exported? → A: Keep it as it is; the error is in the source, not in the ETL.
- Q: May this spec raise the rule version and rebuild the database once? → A: Yes. A rebuild is accepted; limiting the Slack notices to main exists precisely so the extra runs do not disturb the channel.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Weekly runs on feature branches stay quiet in Slack (Priority: P1)

A maintainer validates a spec by running the GitHub Actions weekly on its feature branch, several times. Today each run posts a start and an end message to the shared channel. After this change, only runs on main post; runs on any other branch post nothing and say so in their log.

**Why this priority**: Every later validation in this spec and in the next specs depends on it; without it the channel gets noise from every test run.

**Independent Test**: Run the weekly once on the feature branch and once on main (after merge); the channel gets messages only from the main run.

**Acceptance Scenarios**:

1. **Given** a weekly run on a branch other than main, **When** the run starts and ends, **Then** no Slack message is sent and the log of both notice steps says Slack was skipped because of the branch.
2. **Given** a weekly run on main, **When** the run starts and ends, **Then** the start and end messages are sent exactly as in spec 040.
3. **Given** a weekly run on a branch other than main, **When** it finishes, **Then** its result (passed, failed or cancelled) is the same as it would be without the notice steps.

---

### User Story 2 - The people list shows only real people with whole names (Priority: P1)

A dashboard user opening the people page or a team sees only real people, each under their own name. Today they find "people" named "Dr", "Prof", "Profa", "Ph", "D", "1" or "-", one person named "Gladston Campos/Niase Borjaille", and people named with a whole citation ("Ederson de Souza. Nitretação a plasma em ferro fundido…").

**Why this priority**: These are the first errors anyone notices, and they make the whole dataset look unreliable.

**Independent Test**: After an ingestion, list all people and check for title or fragment names, names joining several people with "/", and names carrying a citation.

**Acceptance Scenarios**:

1. **Given** a Lattes project team whose member list is split into a fragment such as "Dr", "Prof", "Ph" or a single letter, **When** the team is ingested, **Then** no person is created or linked for the fragment, and the real members are linked as before.
2. **Given** a Lattes advisorship whose student field is "Gladston Campos/Niase Borjaille", **When** it is ingested, **Then** the advisorship has two students, "Gladston Campos" and "Niase Borjaille", each a person of their own.
3. **Given** a Lattes advisorship whose student field is "Ederson de Souza. Nitretação a plasma em ferro fundido… (orientador: …", **When** it is ingested, **Then** the student is the person "Ederson de Souza".
4. **Given** a person that existed only because of one of these fragments or joined names, **When** the fix runs on the persistent database, **Then** that person's horizon_id stays resolvable under the horizon_id contract (an alias to the real person, or retired with a reason), and never just disappears.

---

### User Story 3 - Teams and graphs show each relation once and never a self-relation (Priority: P2)

A dashboard user opening a project sees each team member once, and the collaboration graph never shows a person linked to themselves.

**Why this priority**: Visible on single pages, but each affects few records (1 repeated team member, 9 self-edges per graph).

**Independent Test**: After an export, check that no initiative team lists the same person twice and that no collaboration graph has an edge from a person to the same person.

**Acceptance Scenarios**:

1. **Given** an initiative where two documents give the same coordinator with start years 2019 and 2020, **When** it is exported, **Then** the team lists that coordinator once, with the earlier start date (2019).
2. **Given** a Lattes advisorship whose student resolves to the same person as the supervisor, **When** the graphs are built, **Then** no edge links that person to themselves, and the person's other edges are unchanged.

---

### User Story 4 - Titles, years and dates read correctly (Priority: P2)

A dashboard user reads project, production and article titles without a stray "?" and sees no article from year 0.

**Why this priority**: Very visible in lists and timelines, but cosmetic compared with fake people. Dates and titles that are wrong in the source itself are not changed.

**Independent Test**: After an export, search titles for a "?" between two words and articles for years outside 1950–2027.

**Acceptance Scenarios**:

1. **Given** a Lattes title such as "Implantação de um Laboratório de Análise de Solos no Ifes ? Campus Ibatiba", where the downloaded curriculum already holds a literal "?" in place of a lost character, **When** it is ingested, **Then** the title reads "Implantação de um Laboratório de Análise de Solos no Ifes – Campus Ibatiba".
2. **Given** a real question in a title, such as "Ifes Portas Abertas: por qual delas entrar?", **When** it is ingested, **Then** the question mark is kept.
3. **Given** an article whose year is 0 or outside 1950–2027, **When** it is exported, **Then** it is shown without a year, never with a fake one.
4. **Given** a SigPesq workplan cancelled before it began (start 2025-12-01, end 2025-11-30), **When** it is exported, **Then** its dates are kept exactly as the source gives them (the error is in the source, not in the ETL).
5. **Given** an article with an empty title in the source (1 today, with a DOI and a journal), **When** it is exported, **Then** it is kept as it is (the error is in the source, not in the ETL).

---

### Edge Cases

- A real one-word name (for example "Graciela", "Adikto" or "Rhian"): kept as a person; only the title and fragment words listed in FR-004 are refused.
- A name containing "/" that is one person (for example "Ana Maria/Silva" written with a slash as a separator inside one name): split only when each part is itself a name of at least two words; otherwise kept as written.
- A student field that holds only a citation with no recognisable name before ". ": the advisorship keeps no student rather than a citation as a person.
- A fragment person that is also linked to other records (for example "Dr" used as the advisor of an academic degree): every link to it is removed together with it, and the record it was linked to keeps its other data.
- A title with " ? " that the same curriculum also writes correctly elsewhere: both end up with the same text, since the key ignores punctuation.
- A "?" at the end of a title or right after a word ("entrar?"): kept; only a "?" with a space on both sides between two words is replaced.
- A Slack notice on main when the secret is missing: unchanged from spec 040 (skipped with a warning).
- A run started by the schedule: it always runs on main, so it always notifies.

## Requirements *(mandatory)*

### Functional Requirements

**Slack notices**

- **FR-001**: The weekly's start and end Slack notices MUST be sent only when the run's branch is main.
- **FR-002**: On any other branch, both notice steps MUST send nothing and MUST write a log notice saying Slack was skipped because of the branch, naming the branch.
- **FR-003**: Skipping the notices MUST NOT change the run's result, and on main the messages MUST be the same as in spec 040.

**People**

- **FR-004**: Ingestion MUST NOT create or link a person whose whole name is a title or a fragment: "Dr", "Dra", "Drª", "Prof", "Profa", "Profª", "Ph", "PhD", "MSc", "Me", "Licenciatura", a single letter, "-", "xxx", or digits only (compared ignoring case, accents and a trailing dot).
- **FR-005**: A Lattes advisorship student field that joins several names with "/" MUST give one student per name, each a person of their own, when every part is a name of at least two words.
- **FR-006**: A Lattes advisorship student field that holds a citation (a name followed by ". " and further text, or text containing "orientador:" or "coorientador:") MUST keep only the leading name as the student.
- **FR-007**: A person who existed only because of FR-004 to FR-006 MUST stay resolvable under the horizon_id contract: an alias to the real person when one is identified, otherwise retired with a recorded reason. No horizon_id may vanish without a record.

**Teams and graphs**

- **FR-008**: An exported initiative team MUST list each person once, with the earliest start date given by any document and the union of their roles.
- **FR-009**: The collaboration and relationship graphs MUST NOT contain an edge from a person to the same person.

**Titles, years and dates**

- **FR-010**: In initiative, production and article titles from Lattes, a "?" with a space on each side between two words MUST be replaced by an en dash ("–"). Any other "?" MUST be kept.
- **FR-011**: An article year outside 1950–2027 (including 0) MUST be exported as no year. The database keeps the year as the source gives it, and a failing article MUST never stop the rest of its curriculum from being ingested.
- **FR-012**: Dates that end before they start and empty titles that come that way from the source (3 SigPesq workplans, 1 article today) MUST be kept as the source gives them; this spec does not change them.
- **FR-013**: (removed in clarification: the titleless article is a source error and stays as it is; see FR-012)

**Constraints**

- **FR-014**: The rule version MUST go up by one (6 to 7), so a database written under the previous version is rebuilt once before use and an incremental run and a rebuild give the same entities. The id rules themselves (which fields form each natural key) MUST NOT change; the replacement in FR-010 leaves keys unchanged because keys already ignore punctuation.
- **FR-015**: No fix may drop a real record: the only records removed are the fake people of FR-004 to FR-006.
- **FR-016**: All counts in the exports other than people MUST be equal to or higher than before the change; the people count MUST drop by at most the number of fake people removed plus the number added by FR-005.
- **FR-017**: No change to third-party libraries or Docker; nothing goes upstream; the LGPD rules (no CPF or phone numbers in exports) are unchanged.
- **FR-018**: docs/operations/automation.md and tests/test_weekly_etl_workflow.py MUST describe and test FR-001 to FR-003.

### Key Entities

- **Person**: someone named in a source. Gains rules for names that are titles, fragments, several people joined by "/", or citations.
- **Initiative team member**: a person's place in an initiative team, with roles and a start date; one entry per person.
- **Collaboration edge**: a link between two different people in the exported graphs.
- **Title**: the text of an initiative, production or article as shown; a lost character becomes an en dash.
- **Slack notice**: the start and end messages of the GitHub Actions weekly, now only on main.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Weekly runs on any branch other than main send 0 Slack messages; runs on main send 2 (start and end).
- **SC-002**: The published exports have 0 people named with a title or fragment from FR-004 (49 one-word people today, most of them fragments).
- **SC-003**: The published exports have 0 people whose name joins several people with "/" (55 today) and 0 people whose name holds a citation (5 today).
- **SC-004**: The published exports have 0 initiative teams listing the same person twice (1 today) and 0 self-edges in any graph (9 per collaboration graph today).
- **SC-005**: The published exports have 0 titles with a "?" between two spaced words (237 initiatives, 57 productions and 80 articles today), while titles ending in a real question keep it.
- **SC-006**: The published exports have 0 articles with a year outside 1950–2027 (3 today); the 3 workplans ending before they start and the 1 titleless article stay as the source gives them.
- **SC-007**: Every horizon_id published before the change is still resolvable after it (directly, through an alias, or listed as retired with a reason).
- **SC-008**: Every other count in the exports is equal to or higher than in the exports before the change.

## Assumptions

- The "?" in Lattes titles is already in the downloaded curricula (checked: the raw JSON holds a literal "?"), so the original character cannot be recovered; a dash is the most frequent lost character in these titles ("Ifes ? Campus Ibatiba", "NOVA VENÉCIA ? ES"), so an en dash is used.
- The crawler that downloads the curricula is a third-party library and is not changed; the fix is in the ETL.
- The fake people come only from Lattes (project teams and advisorship student fields) and, for 3 one-word names, from CNPq group pages; the same name rules apply to every source.
- The weekly scheduled run uses main, so it keeps notifying.
- Validation follows the batch rule: two local validations, then weekly runs on the RafaelDeps fork, with a run on the feature branch (no Slack message) and, after the merge, a run on main (both messages). No weekly run starts without the maintainer's go-ahead.
