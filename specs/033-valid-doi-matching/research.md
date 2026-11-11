# Research: Only real DOIs identify an article

All measurements below come from the 435 curricula in `data/lattes_json` and
the database of the from-scratch weekly run of 2026-11-10 (branch 032), read
only.

## R1 - One rule, in `normalize_doi`

- **Decision**: `normalize_doi` in `src/core/logic/horizon_identity.py` becomes
  the single DOI rule: it returns the cleaned DOI when the value has DOI form
  and `None` otherwise. No second function is added.
- **Rationale**: every comparison of a DOI already goes through it:
  `_find_article` (matching), `article_decision` (permanent id
  `article:doi:<doi>`), `lattes_article_key` (tracking key of the curriculum
  item) and `ReferenceConsolidator` (duplicate audit). Changing it once keeps
  the incremental run, the rebuild and the audit on the same rule (FR-007).
- **Alternatives considered**: a new `valid_doi` function used only by
  `_find_article`. Rejected: the permanent id and the tracking key would still
  treat the Scopus link as a DOI, so two databases would disagree.

## R2 - What "DOI form" is

- **Decision**: after cleaning, the value must match
  `10.` + 4 to 9 digits (optionally `.digits` sub-registrants) + `/` + a
  non-empty suffix without spaces.
- **Rationale**: this is the syntax Crossref recommends for matching DOIs and
  it accepts all 3,048 values that are plain DOIs today. It rejects the ISSNs
  (`1982-9434`), a prefix without a suffix (`10.22410/`) and free text.
- **Alternatives considered**: accept any `10.<digits>/...`. Rejected: no real
  DOI in the data has a registrant shorter than 4 digits, and the looser form
  only lets test-style values through. Checking the DOI against doi.org or
  Crossref: rejected, out of scope (spec, Assumptions) and it would add a
  network dependency to ingestion.

## R3 - Cleaning steps and their order

- **Decision**: (1) trim; (2) when the text has a `doi=` link parameter, take
  its percent-decoded value and drop the rest; (3) lowercase; (4) remove a
  leading `http(s)://(dx.)doi.org/` or `doi:` label; (5) remove every
  whitespace character; (6) remove trailing `.`, `,` or `;`; (7) apply R2.
- **Rationale**: measured on the 3,174 items with a DOI field:

  | Outcome | Items | Example |
  |---------|-------|---------|
  | Valid, compared as today | 3,048 | `http://dx.doi.org/10.55905/cuadv17n3-055` |
  | Rejected, Scopus link with `doi=null` | 74 | `…citedby.url?…&doi=null&md5=…` |
  | Valid, DOI taken from the link | 33 | `…&doi=10.1186/1753-6561-8-s4-p29&md5=…` |
  | Valid, spaces removed | 10 | `10.3390 / fishes6030031` |
  | Rejected, other | 7 | `1982-9434`, `10.22410/`, a journal name in `doi=` |
  | Valid, trailing full stop removed | 2 | `10.1590/S0101-20612006000400005.` |

  The link parameter is read before the prefix is removed because the Scopus
  value is not a doi.org address.
- **Alternatives considered**: searching for a DOI anywhere in the text
  (`re.search`). Rejected: it would silently accept a DOI cut at the first
  space, which is a wrong DOI; removing the spaces keeps the whole value.

## R4 - The new rule creates no new wrong merge

- **Decision**: no title condition is added to DOI matching (FR-005).
- **Rationale**: grouping the journal items by cleaned DOI gives 21 groups
  with more than one title, against 23 under the old rule; the 2 that
  disappear are the Scopus `doi=null` link and the ISSN. No group is new or
  larger. The 33 DOIs taken from links and the 12 corrected ones join only
  items of the same work.
- **Alternatives considered**: requiring similar titles for a DOI match.
  Rejected: it would split the valid merges (Portuguese and English title,
  truncated title).

## R5 - What is stored and what is tracked

- **Decision**: `ingest_articles_task` computes the cleaned DOI once per item
  and uses it for the lookup, for the new article, for filling a missing DOI
  of an existing article, for the change log, for the attribute assertion and
  for the `doi_exact` / `title_year` match strategy. The item is recorded in
  `source_records` before that, with the raw value untouched.
- **Rationale**: FR-006 (the stored DOI is the cleaned DOI) and FR-008 (the
  raw value stays in the tracking data). Decided with the maintainer on
  2026-11-10: the stored and exported value is the bare DOI
  (`10.5007/2175-8077.2022.e79488`), not the address
  (`http://dx.doi.org/10.5007/…`) kept today.
- **Alternatives considered**: keep the address form for valid DOIs and fix
  only the wrong values. Rejected by the maintainer: one form for every
  article is preferred. Cleaning in the Lattes parser: rejected, the parser
  output is the tracked source payload and must stay as the curriculum
  wrote it.

## R6 - Consumers of the exported `doi`

- **Decision**: no consumer change is needed.
- **Rationale**: checked on 2026-11-10, read only.
  - Dashboard (`horizon_dashboard`): the three "Ver DOI" links use the value
    as a link when it starts with `http` and prepend `https://doi.org/`
    otherwise; the publication page strips the address and rebuilds it; the
    impact data is keyed by article id. Both forms work, and an empty DOI
    hides the link. Today 30 exported values are Scopus links, which open the
    Scopus citation page or build a broken link; they are fixed by this
    feature.
  - Scripts in this repository (`fetch_openalex_citations`, `analyze_venues`,
    `analyze_maturity`) extract `10.xxxx/…` from the text, and
    `etl_load_report` compares the export with the database, both written by
    the same rule.
- **Alternatives considered**: none; the check was to rule out a break.

## R7 - Reaching a database that already exists

- **Decision**: `HORIZON_RULE_VERSION` goes from 2 to 3. Nothing else is
  built.
- **Rationale**: `_reset_if_rule_version_changed`
  (`src/flows/pipelines/weekly_orchestrator.py`) already rebuilds once a
  database whose recorded version differs from the code's, and
  `rule_version_requires_reset` is tested (`tests/test_rule_version_guard.py`).
  Articles merged under a fake DOI cannot be split by an incremental run, and
  the constitution (Data Integrity, rule 3) requires this rebuild. The same
  guard works locally and in the weekly workflow, where the restored database
  of the previous run is rebuilt on the first run after the merge.
- **Alternatives considered**: an in-place repair that splits the 2 merged
  articles. Rejected: it needs the per-item history of authors and fields and
  would be a second ingestion path for a one-time case.

## R8 - Permanent ids

- **Decision**: no change to the id history code.
- **Rationale**: for the 3,048 plain DOIs the id `article:doi:<doi>` is the
  same string as today (the old rule already removed the address and the
  case). The ids that change are those of the 45 articles with a non-DOI or
  uncleaned value and of the works split from the 2 merged articles. The
  assigner keeps the id history from the previous database (or from the
  exported zip after a rebuild) and turns ids that no longer exist into
  aliases, as it did for the 1 -> 2 change. The validation records how many
  aliases the rebuild creates (quickstart, step 4).
- **Alternatives considered**: hand-written alias rules for the Scopus link
  id. Rejected: one old id cannot point to 67 works; the existing rules decide
  which article keeps it.

## R9 - Tests that use short fake DOIs

- **Decision**: fixtures that use values such as `10.1/x` as DOIs are changed
  to DOI form (`10.1000/x`); `10.1000/x` already used in other tests stays.
- **Rationale**: R2 rejects a registrant shorter than 4 digits. These are
  test values only (`tests/test_horizon_identity.py` line 248 is one); the
  tasks list every file found by a search for `"10\.\d{1,3}/`.
- **Alternatives considered**: loosening R2 to keep the fixtures. Rejected:
  the rule should follow the data, not the fixtures.
