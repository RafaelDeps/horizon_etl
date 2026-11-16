# Implementation Plan: Only real DOIs identify an article

**Branch**: `033-valid-doi-matching` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/033-valid-doi-matching/spec.md`

## Summary

The DOI field of a Lattes article sometimes holds a Scopus link, an ISSN or a
DOI with spaces. `normalize_doi` accepts any text, so every work that carries
the same non-DOI text is taken for one article: 110 curriculum items are
attached to an article with another title, 69 works are hidden inside 2
articles and 45 articles store a value that is not a DOI.

The fix makes `normalize_doi` (`src/core/logic/horizon_identity.py`) the single
DOI rule: it cleans the value (DOI inside a `doi=` link parameter, `doi.org`
prefix, `doi:` label, case, spaces, trailing punctuation) and returns it only
when it has DOI form; otherwise it returns `None`. Every place that compares a
DOI already calls this function, so matching, the article's permanent id, the
tracking key and the duplicate audit follow the new rule without their own
change. `ingest_articles_task` stores and tracks the cleaned DOI instead of the
raw text. Because the identity of an article changes, `HORIZON_RULE_VERSION`
goes from 2 to 3, and the existing guard of the weekly rebuilds a database
written under version 2 once, keeping old ids as aliases.

## Technical Context

**Language/Version**: Python 3.12 in GitHub Actions; the local `.venv` runs 3.14

**Primary Dependencies**: SQLAlchemy (raw `text()` SQL in the article lookup), Prefect (the `lattes_projects` flow, unchanged), standard library `re` and `urllib.parse` for the rule; no new dependency

**Storage**: SQLite `db/horizon.db`: `articles.doi`; `horizon_ids` / `horizon_id_aliases` / `horizon_meta` (rule version); tracking tables `source_records`, `entity_matches`, `attribute_assertions`, `entity_change_logs`

**Testing**: pytest: `tests/test_horizon_identity.py` (the rule and the article id), `tests/test_lattes_articles.py` (matching), `tests/test_article_fill.py` (what is stored), `tests/test_tracking_keys.py` (source key), `tests/test_article_consolidation.py` (duplicate audit), `tests/test_rule_version_guard.py` (rebuild guard); `make ci-check` before a merge

**Target Platform**: Linux, local runs and the GitHub Actions weekly workflow

**Project Type**: ETL pipeline (Prefect flows + domain logic)

**Performance Goals**: none new; the rule is a few string operations per article item (about 4,300 journal items per run)

**Constraints**: no new setting, Makefile target or workflow input; no Docker change; no change to third-party libraries; the Lattes parser keeps passing the raw value; no "similar titles" condition on DOI matching

**Scale/Scope**: 435 curricula, 4,340 journal items, 3,174 with a DOI field; about 126 items change (74 Scopus links without a DOI, 33 Scopus links with a DOI, 10 DOIs with spaces, 7 other non-DOI values, 2 trailing full stops); about 8,000 articles are rebuilt once

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Ports & Adapters | PASS | The rule is a pure function in `src/core/logic/`; the flow keeps its existing SQL lookup. No new port or adapter. |
| II. Domain-First Data Modeling | PASS | No entity or export shape changes. The `doi` field keeps its name and type; its value becomes the bare DOI. |
| III. Prefect Flow Orchestration | PASS | No new flow or script. The rebuild is the weekly's existing rule-version guard. |
| IV. Audit-Driven Data Quality | PASS | The raw value stays in `source_records`; `entity_matches` records `doi_exact` only for a real DOI; the duplicate audit uses the same rule. |
| V. LGPD Compliance | PASS | No personal data involved. |
| Data Integrity: 2. Idempotency | PASS | Keys still come only from source data; SC-006 checks that a second run writes nothing. |
| Data Integrity: 3. Re-creatable | PASS | The rule version changes (2 -> 3) and the database is rebuilt before use, as rule 3 requires. |
| Data Integrity: 4. Published identity history | PASS | Old article ids stay resolvable through the existing alias history; the history supplies no data. |
| Development Workflow | PASS | Tests before the change; full suite, black, isort, flake8 on touched files. |

Re-check after Phase 1: PASS, no violation to justify.

## Project Structure

### Documentation (this feature)

```text
specs/033-valid-doi-matching/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1-R9
├── data-model.md        # Phase 1: the DOI value and what it feeds
├── quickstart.md        # Phase 1: how to validate
├── contracts/
│   └── doi-rule.md      # Phase 1: contract of normalize_doi
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/
├── core/logic/
│   ├── horizon_identity.py        # normalize_doi becomes the strict rule; HORIZON_RULE_VERSION 2 -> 3
│   └── reference_consolidator.py  # no code change expected: it calls normalize_doi (checked by its tests)
└── flows/lattes/
    └── projects.py                # new _with_clean_doi; ingest_articles_task stores and tracks the cleaned DOI; _find_article docstring

tests/
├── test_horizon_identity.py       # contract of the rule; article id of non-DOI values
├── test_lattes_articles.py        # two works with one fake DOI stay two; links and spaces match the plain DOI
├── test_article_fill.py           # the item is stored with the cleaned DOI; a non-DOI value never fills the DOI
├── test_tracking_keys.py          # source key of an item with a non-DOI value
├── test_article_consolidation.py  # non-DOI values do not group articles in the duplicate audit
├── test_rule_version_guard.py     # a database written under version 2 needs a reset
└── (fixtures that use "10.1/x"-style DOIs are updated to DOI form)

docs/backlog.md                    # new entry for this defect, marked done at the end
```

**Structure Decision**: the existing single-project layout. All behaviour
lives in one pure function that the other modules already import; the flow
change is limited to passing the cleaned value where the raw one is passed
today.

## Complexity Tracking

No violation to justify.
