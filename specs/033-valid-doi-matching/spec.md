# Feature Specification: Only real DOIs identify an article

**Feature Branch**: `033-valid-doi-matching`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Stop non-DOI values from merging different articles (fake DOI merge). The Lattes DOI field sometimes holds a Scopus link without a DOI, an ISSN, a Scopus link with the real DOI inside, or a DOI with spaces. Any string is accepted as a DOI today, so different works that share such a value become one article. Accept a value as a DOI only when it has DOI form after cleaning; otherwise treat the item as having no DOI. Keep valid same-DOI merges. State how the fix reaches a persistent database."

## Background

An article from a Lattes curriculum is recognised as an already stored article
in two ways: the same DOI (whatever the title), or, without a DOI, the same
title in the same year. The first rule trusts whatever text the curriculum
carries in its DOI field. That field is filled by hand or by import tools and
sometimes holds something else:

| What the field holds | Example | Today |
|----------------------|---------|-------|
| A Scopus link with no DOI | `http://www.scopus.com/scopus/inward/citedby.url?partnerID=…&doi=null&md5=f8a2d9f8…` | Used as a DOI |
| An ISSN | `1982-9434` | Used as a DOI |
| A Scopus link with the DOI inside | `…citedby.url?…&doi=10.1186/1753-6561-8-s4-p29&md5=…` | The whole link is used as the DOI |
| A DOI with spaces | `10.3390 / fishes6030031` | Used as written |

Every work that carries the same non-DOI text is taken for the same article.
Measured on a from-scratch weekly run of 2026-11-10 over 435 curricula:

- 110 curriculum items were attached to an article with another title.
- 69 different works are hidden inside 2 articles: 67 under the Scopus
  "doi=null" link and 2 under the ISSN.
- 45 articles store a DOI value that is not a DOI.

The same defect exists on the main branch (97 items) and on branch 022
(85 items); it is not a regression of a recent change.

The DOI rule itself is right and must stay: on the same database, 20 articles
carry more than one title under one valid DOI and each is one work (Portuguese
and English title, truncated title, encoding variants, one blank title).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Different works are no longer merged by a value that is not a DOI (Priority: P1)

As a consumer of the exported data, I want every work listed in a curriculum to
exist as its own article, so that a researcher's production is not undercounted
and no article shows authors who did not write it.

**Why this priority**: this is data loss. 69 works are missing from the exports
today and one article shows the authors of 67 unrelated works.

**Independent Test**: ingest two curricula whose article items have different
titles and the same Scopus "doi=null" link in the DOI field; two articles exist
afterwards, each linked only to its own author.

**Acceptance Scenarios**:

1. **Given** two curriculum items with different titles and the same Scopus link without a DOI, **When** both are ingested, **Then** two articles exist, each with its own title and its own authors.
2. **Given** two curriculum items with different titles and the same ISSN in the DOI field, **When** both are ingested, **Then** two articles exist.
3. **Given** two curriculum items with the same title, the same year and the same non-DOI value, **When** both are ingested, **Then** one article exists (matched by title and year, as any article without a DOI).
4. **Given** a stored article with a valid DOI and a curriculum item with the same title and year whose DOI field holds a non-DOI value, **When** the item is ingested, **Then** it is attached to the stored article and the stored DOI is unchanged.
5. **Given** the 435 curricula of the 2026-11-10 run, **When** the database is rebuilt from scratch, **Then** no curriculum item is attached to an article with another title because of a non-DOI value (110 today) and the hidden works (about 69) exist as their own articles.

---

### User Story 2 - A stored DOI is always a DOI (Priority: P2)

As a consumer of the exported data, I want the DOI of an article to be usable
as a DOI, so that I can link to the publication or cross it with other
databases without cleaning the value first.

**Why this priority**: it is wrong data rather than lost data, and it depends
on the same rule as User Story 1.

**Independent Test**: ingest items whose DOI field holds each kind of value in
the Background table; the stored DOI is the clean DOI when one can be read from
the value and empty otherwise.

**Acceptance Scenarios**:

1. **Given** an item whose DOI field is a link that carries a DOI in its `doi=` parameter, **When** it is ingested, **Then** the article stores that DOI alone, not the link.
2. **Given** an item whose DOI field is a DOI with spaces inside, **When** it is ingested, **Then** the article stores the DOI without spaces.
3. **Given** an item whose DOI field is a Scopus link with `doi=null`, an ISSN or any other text without DOI form, **When** it is ingested, **Then** the article stores no DOI.
4. **Given** two items for the same work, one with the plain DOI and one with a link that carries the same DOI, **When** both are ingested, **Then** one article exists.
5. **Given** the 435 curricula of the 2026-11-10 run, **When** the database is rebuilt from scratch, **Then** no article stores a DOI that is not in DOI form (45 today).

---

### User Story 3 - Valid DOI merges and everything else stay as they are (Priority: P2)

As the maintainer, I want the fix to change only the cases above, so that works
correctly recognised as one article stay one article and no other data moves.

**Why this priority**: a stricter rule that also split correct merges would
create duplicates, which is wrong data of another kind.

**Independent Test**: ingest two items with the same valid DOI and different
titles (one in Portuguese, one in English); one article exists.

**Acceptance Scenarios**:

1. **Given** two items with the same valid DOI and different titles, **When** both are ingested, **Then** one article exists.
2. **Given** two items with the same valid DOI written with different case or with and without the `doi.org` prefix, **When** both are ingested, **Then** one article exists.
3. **Given** the 435 curricula of the 2026-11-10 run, **When** the database is rebuilt from scratch, **Then** the articles that carry more than one title under one valid DOI (about 20) are still one article each.
4. **Given** the same rebuild, **When** every curriculum item is checked against the database, **Then** awards, languages, technical productions, projects and advisorships are all present, as before.

---

### User Story 4 - A database that already holds the wrong merges is repaired (Priority: P3)

As the maintainer of the persistent database, I want the fix to reach a
database that was filled before it, so that the weekly run does not keep the 69
works hidden forever.

**Why this priority**: the rule alone fixes new databases; without this story
the persistent database of the weekly run would keep the old merges.

**Independent Test**: start a run on a database written under the old rule; the
run does not proceed incrementally on it; after the rebuild the acceptance
numbers of User Stories 1 and 2 hold; the next run over the same inputs writes
nothing.

**Acceptance Scenarios**:

1. **Given** a database written under the old rule, **When** a run starts, **Then** the database is recognised as written under older rules and is rebuilt before use, as the constitution requires for a change of the identity rules.
2. **Given** a database rebuilt under the new rule, **When** a second run processes the same inputs, **Then** nothing is written.
3. **Given** a database rebuilt under the new rule and an incremental database that received the same inputs under the new rule, **When** they are compared, **Then** they hold the same articles.

---

### Edge Cases

- The DOI field holds a link whose `doi=` parameter is empty or `null`: no DOI.
- The DOI inside a link is percent-encoded (`10.1186%2F1753…`): it is decoded and used.
- The value is a DOI followed by other link parameters (`…&md5=…`): only the DOI part is kept.
- The value has a valid prefix but nothing after the slash (`10.1234/`): no DOI.
- The value is a DOI with surrounding spaces, a trailing full stop or a `doi:` label: the clean DOI is used.
- Two different works with the same title and year, both with a non-DOI value: they are one article, as two works without a DOI are today. This is the existing title-and-year rule and is out of scope.
- A curriculum item whose title is blank and whose DOI field is not a DOI: it matches nothing, as a blank title without a DOI does today.
- An article already published with a permanent id that is split by the rebuild: the old id stays resolvable; which of the resulting articles keeps it follows the existing permanent-id rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat a value as a DOI only when, after cleaning, it has DOI form: it starts with `10.`, followed by a registrant code, a slash and a non-empty suffix.
- **FR-002**: Cleaning MUST remove the `doi.org` / `dx.doi.org` address and a `doi:` label, ignore letter case, remove spaces inside and around the value, and, when the value is a link that carries a DOI in a `doi=` parameter, take that DOI (decoded) and drop the rest of the link.
- **FR-003**: A value that does not have DOI form after cleaning MUST count as "no DOI": it MUST NOT be used to recognise an article and MUST NOT be stored as the article's DOI.
- **FR-004**: An item without a DOI (including one under FR-003) MUST be matched by title and year exactly as items without a DOI are matched today.
- **FR-005**: Two items whose values clean to the same DOI MUST be recognised as the same article whatever their titles; no title-similarity condition is added to DOI matching.
- **FR-006**: The article's stored DOI MUST be the cleaned DOI.
- **FR-007**: The same rule MUST apply everywhere an article's DOI is compared, stored or used to build an identity, so that an incremental run and a rebuild from the same inputs give the same articles.
- **FR-008**: The value exactly as written in the curriculum MUST stay recorded in the tracked source record of the curriculum item, as it is today, so nothing from the source is lost. The value recorded as chosen for the article is the cleaned DOI.
- **FR-009**: Because this changes how articles are identified, the recorded version of the identity rules MUST change, and a database recorded under the earlier version MUST be rebuilt before use, as the constitution requires.
- **FR-010**: Processing the same inputs a second time on a database built under the new rule MUST write nothing.
- **FR-011**: The feature MUST work in a local run and in the GitHub Actions weekly workflow, with no new setting.
- **FR-012**: The change MUST be made inside this project only: no change to third-party libraries and no Docker change.

### Key Entities

- **Article**: a published work (journal article or conference paper) with a title, a year, an optional DOI and its authors. One article may be fed by items from several curricula.
- **Curriculum article item**: one work as listed in one researcher's Lattes curriculum, with the DOI field as the researcher filled it.
- **DOI**: the publication's persistent identifier. Only a value in DOI form is one.
- **Identity rule version**: the recorded version of the rules that decide when two records are the same entity; a database is valid only for the version it was built with.

## Success Criteria *(mandatory)*

### Measurable Outcomes

Measured on a from-scratch weekly run over the curricula of 2026-11-10 (435).
The run downloads part of the curricula again, so the targets that are counts
are approximate and the targets that are zero are exact:

- **SC-001**: 0 curriculum article items are attached to an article with another title because of a non-DOI value (110 before).
- **SC-002**: The works hidden today (about 69) exist as their own articles, each linked to the researchers whose curricula list them.
- **SC-003**: 0 articles store a DOI that is not in DOI form (45 before); every item whose link carries a real DOI stores that DOI.
- **SC-004**: The articles with more than one title under one valid DOI (about 20) are still one article each.
- **SC-005**: The counts of awards, languages, technical productions, projects and advisorships are the same as in the run before the change, except for items of curricula that were downloaded again and changed.
- **SC-006**: A second run writes nothing for the curricula that did not change.
- **SC-007**: A database built before the change is never used incrementally: it is rebuilt first, in the local run and in the weekly workflow.

## Assumptions

- A rebuild is the way the fix reaches an existing database. Articles already merged under a non-DOI value cannot be split by an incremental run, and the constitution (Data Integrity & Persistent Incremental Ingestion, rule 3) already requires a rebuild when the identity rules change. No in-place repair of merged articles is built.
- The weekly run of the fork and any upstream run happen only with the maintainer's approval; the rebuild they need is part of that approval.
- "DOI form" follows the public DOI syntax (prefix `10.` + registrant code + `/` + suffix). Values that follow the syntax but point to no publication are accepted; checking a DOI against an external service is out of scope.
- Journal articles and conference papers with the same title and year being recognised as one article (47 cases on the same database) is a separate defect of the title-and-year rule and is out of scope.
- Only DOIs of articles from Lattes curricula are in scope; no other source supplies an article DOI today.
- The 2 articles that hide the 69 works keep existing after the fix as whichever work legitimately owns the title; their extra authors go to the articles they belong to.
