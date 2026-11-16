---

description: "Task list for spec 033: only real DOIs identify an article (fake DOI merge)"
---

# Tasks: Only real DOIs identify an article

**Input**: Design documents from `specs/033-valid-doi-matching/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/doi-rule.md, quickstart.md

**Tests**: Included. The constitution's development workflow requires tests,
and the plan writes them before the change (they must fail first).

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)

Code: `src/core/logic/horizon_identity.py` (the rule and the rule version) and
`src/flows/lattes/projects.py` (what is stored). Tests:
`tests/test_horizon_identity.py`, `tests/test_lattes_articles.py`,
`tests/test_article_fill.py`, `tests/test_tracking_keys.py`,
`tests/test_article_consolidation.py`, `tests/test_rule_version_guard.py`.

---

## Phase 1: Setup

**Purpose**: Confirm the starting point.

- [X] T001 Run `.venv/bin/python -m pytest -q tests/test_horizon_identity.py tests/test_lattes_articles.py tests/test_article_fill.py tests/test_tracking_keys.py tests/test_article_consolidation.py tests/test_reference_consolidator.py tests/test_rule_version_guard.py` on branch `033-valid-doi-matching` and record that it passes before any change (baseline). Result (2026-11-10): 68 passed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The single DOI rule every story uses (contracts/doi-rule.md, research R1-R3).

- [X] T002 In tests/test_horizon_identity.py add `test_normalize_doi_contract`, one parametrized test with every row of the "Examples" table of contracts/doi-rule.md (19 inputs: plain DOI, doi.org / dx.doi.org address, `doi:` label, trailing full stop, spaces inside, Scopus link with the DOI in `doi=`, percent-encoded DOI in `doi=`, Scopus link with `doi=null`, empty `doi=`, free text in `doi=`, ISSN with and without the address, `10.22410/`, `10.1/x`, `not a doi`, blank, `None`), and `test_normalize_doi_is_idempotent` (for every example that gives a DOI, `normalize_doi(normalize_doi(x)) == normalize_doi(x)`). Keep the existing `test_normalize_doi_strips_url_prefixes_and_case`. Confirm the new tests fail. Result: 15 failed before T003, as expected.
- [X] T003 Rewrite `normalize_doi` in src/core/logic/horizon_identity.py following the 7 steps of contracts/doi-rule.md: blank -> `None`; take the percent-decoded value of a `doi=` link parameter when present (`urllib.parse.unquote`); lower case; remove the leading doi.org / dx.doi.org address (existing `_DOI_PREFIX`) or a `doi:` label; remove all whitespace; strip trailing `.`, `,`, `;`; return the value only when it matches a module-level `_DOI_FORM = re.compile(r"^10\.\d{4,9}(\.\d+)*/\S+$")`, else `None`. Update the docstring to say the function is the single DOI rule (spec 033) and that a value without DOI form is no DOI. T002 passes.
- [X] T004 Update the test values that are not in DOI form (research R9): in tests/test_article_consolidation.py replace `10.1/x`, `10.1/y`, `10.1/X`, `10.1/b`, `10.1/B` with `10.1000/x`, `10.1000/y`, `10.1000/X`, `10.1000/b`, `10.1000/B` (including the expected id `article:doi:10.1000/x` and the expected `survivor["doi"]`); in tests/test_horizon_identity.py line 248 replace `10.1/x` with `10.1000/x`; in tests/test_tracking_keys.py replace `https://doi.org/10.1/ABC` and the expected `|10.1/abc|` with `https://doi.org/10.1000/ABC` and `|10.1000/abc|`. Run `grep -rnE "10\.[0-9]{1,3}/" tests` and confirm nothing is left. Run the T001 command; all pass. Result: the only `10.1/x` left is the contract example that must give `None`; 89 passed.

**Checkpoint**: the rule exists and every caller of `normalize_doi` uses it.

---

## Phase 3: User Story 1 - Different works are no longer merged by a value that is not a DOI (Priority: P1) 🎯 MVP

**Goal**: two works that share a Scopus link without a DOI, or an ISSN, stay two articles; they still match by title and year.

**Independent Test**: on the in-memory `articles` table of tests/test_lattes_articles.py, an article stored with the Scopus `doi=null` link is not found by an item with another title and the same link; it is found by an item with the same title and year.

### Tests for User Story 1

- [X] T005 [US1] In tests/test_lattes_articles.py add, with a module constant `SCOPUS_NO_DOI = "http://www.scopus.com/scopus/inward/citedby.url?partnerID=bb5nvXTn&rel=R6.0.0&doi=null&md5=f8a2d9f8af7e0fb17f9968fbbee28b49"`: `test_a_scopus_link_without_a_doi_does_not_match_another_title` (stored `("Work A", 2013, SCOPUS_NO_DOI)`; `_find_article(session, "Work B", 2013, SCOPUS_NO_DOI) is None`); `test_an_issn_in_the_doi_field_does_not_match_another_title` (stored and wanted `"http://dx.doi.org/1982-9434"`, different titles -> `None`); `test_same_title_and_year_still_match_with_a_non_doi_value` (same title and year, both with `SCOPUS_NO_DOI` -> the stored id); `test_a_non_doi_value_matches_an_article_with_a_real_doi_by_title` (stored `("Same", 2020, "10.1000/abc")`, wanted `("Same", 2020, SCOPUS_NO_DOI)` -> the stored id).
- [X] T006 [P] [US1] In tests/test_horizon_identity.py add `test_article_with_a_non_doi_value_gets_the_content_id`: `article_decision` of a row whose `doi` is the Scopus `doi=null` link, and of one whose `doi` is `http://dx.doi.org/1982-9434`, returns the same `horizon_id` as the row with `doi=""` (prefix `article:h:`), never `article:doi:`.
- [X] T007 [P] [US1] In tests/test_tracking_keys.py add `test_article_key_of_a_non_doi_value_uses_title_and_year`: `lattes_article_key(CV, art)` for an item with the Scopus `doi=null` link equals the key of the same item with `doi=None`, and two items with different titles and the same link have different keys.
- [X] T008 [P] [US1] In tests/test_article_consolidation.py add `test_a_shared_non_doi_value_does_not_group_articles`: three rows with different titles and years and the same Scopus `doi=null` link in `doi` give no group (same helper and assertions style as `test_blank_titles_are_never_grouped`).
- [X] T009 [US1] Run T005-T008. Record which fail without further code: they depend only on T003, so they are expected to pass already; a failure means a caller compares the DOI without `normalize_doi` and must be fixed in that caller. Result: all passed with T003 alone, as expected; no caller compares a DOI outside `normalize_doi`.

### Implementation for User Story 1

- [X] T010 [US1] In src/flows/lattes/projects.py update the docstring of `_find_article` (spec 029 D4 text): a value that is not a DOI after `normalize_doi` (spec 033) counts as no DOI and the item is matched by title and year. No logic change is expected in `_find_article`; if T005 fails, fix it there.

**Checkpoint**: US1 works; the fake DOI no longer joins different works in matching, in the permanent id, in the tracking key and in the duplicate audit.

---

## Phase 4: User Story 2 - A stored DOI is always a DOI (Priority: P2)

**Goal**: `articles.doi` and the tracked `doi` hold the cleaned DOI or nothing; the raw value stays in the source record.

**Independent Test**: the helper that prepares an article item returns the cleaned DOI for each kind of value; filling a missing DOI writes the cleaned DOI and never a non-DOI value.

### Tests for User Story 2

- [X] T011 [US2] In tests/test_article_fill.py add `test_item_is_stored_with_the_cleaned_doi`: import `_with_clean_doi` from src.flows.lattes.projects; for an item `{"title": "T", "year": 2020, "doi": <raw>, "volume": "1"}` with each raw value (a dx.doi.org address, a Scopus link with `doi=10.1186/1753-6561-8-s4-p29`, `10.3390 / fishes6030031`, the Scopus `doi=null` link, `http://dx.doi.org/1982-9434`), the returned dict has `doi` equal to `10.…` cleaned or `None`, keeps the other fields, and the input dict is not modified. Confirm it fails (ImportError). Result: failed before T014 (ImportError), as expected.
- [X] T012 [US2] In tests/test_article_fill.py add `test_missing_doi_is_filled_with_the_cleaned_doi` (stored article without a DOI; `_fill_missing_article_fields(session, 1, _with_clean_doi({"doi": "http://dx.doi.org/10.1000/ABC."}), 7)` stores `10.1000/abc`) and `test_a_non_doi_value_never_fills_the_doi` (same with the Scopus `doi=null` link: `doi` stays NULL and no change is recorded for `doi`).
- [X] T013 [P] [US2] In tests/test_lattes_articles.py add `test_a_link_carrying_the_doi_matches_the_plain_doi` (stored `("Some Title", 2019, "10.1186/1753-6561-8-s4-p29")`; `_find_article(session, "Other", 2020, "http://www.scopus.com/scopus/inward/citedby.url?partnerID=x&rel=R6.0.0&doi=10.1186/1753-6561-8-s4-p29&md5=abc") == 1`) and `test_a_doi_with_spaces_or_a_trailing_full_stop_matches` (stored `10.3390/fishes6030031`; wanted `http://dx.doi.org/10.3390 / fishes6030031` and `10.3390/fishes6030031.` -> 1).

### Implementation for User Story 2

- [X] T014 [US2] In src/flows/lattes/projects.py add `_with_clean_doi(art: dict) -> dict` next to `_fill_missing_article_fields`: returns a copy of the item whose `doi` is `normalize_doi(art.get("doi"))`; docstring cites spec 033 (FR-006) and research R5. T011 and T012 pass.
- [X] T015 [US2] In `ingest_articles_task` (src/flows/lattes/projects.py): keep `tracking_recorder.record_source_record(payload=art, ...)` with the raw item (FR-008); right after it set `art = _with_clean_doi(art)` and `doi = art["doi"]`, so the cleaned DOI is what goes to `_find_article`, `article_ctrl.create_article(doi=...)`, the `create` change log, `_fill_missing_article_fields`, `record_attribute_assertions` and the `doi_exact` / `title_year` choice of `record_entity_match`. Add a two-line comment saying why the source record comes first.
- [X] T016 [US2] Run tests/test_article_fill.py and tests/test_lattes_articles.py; all pass. Result: 22 passed.

**Checkpoint**: US1 and US2 pass together; SC-003 holds in tests.

---

## Phase 5: User Story 3 - Valid DOI merges and everything else stay as they are (Priority: P2)

**Goal**: the stricter rule splits nothing that was correctly one article.

**Independent Test**: the existing DOI and title tests of tests/test_lattes_articles.py pass unchanged, and two items with one valid DOI and different titles are one article.

### Tests for User Story 3

- [X] T017 [US3] Confirm that `git diff tests/test_lattes_articles.py` shows only added tests: the 11 tests that existed before this branch (DOI by case or prefix whatever the title, stored prefix, two different DOIs, blank titles, one DOI only, years, lowest id, LIKE wildcards) are unchanged and pass. Result: `git diff` shows 50 added lines and none removed.
- [X] T018 [P] [US3] In tests/test_horizon_identity.py add `test_valid_doi_spellings_keep_the_same_article_id`: `article_decision` gives `article:doi:10.1016/j.theriogenology.2018.10.032` for the plain DOI, the dx.doi.org address, the value with a trailing full stop and the Scopus link carrying it, so ids published for valid DOIs do not change (research R8).
- [X] T019 [P] [US3] In tests/test_article_consolidation.py confirm `test_groups_by_normalized_doi` and `test_two_different_dois_merge_only_rows_with_the_same_doi` pass with the values of T004; add no code.

### Implementation for User Story 3

- [X] T020 [US3] No code beyond T003 is expected. Run T017-T019 and fix `normalize_doi` only if one fails. Result: no further code needed.

**Checkpoint**: US1, US2 and US3 pass together.

---

## Phase 6: User Story 4 - A database that already holds the wrong merges is repaired (Priority: P3)

**Goal**: a database written under the old rule is rebuilt once before use.

**Independent Test**: a database whose recorded rule version is 2 requires a reset; one recorded with the code's version does not.

### Tests for User Story 4

- [X] T021 [US4] In tests/test_rule_version_guard.py add `test_a_database_written_before_spec_033_needs_a_reset`: with the same setup as `test_other_or_missing_version_needs_a_reset`, a database with ingested rows and `rule_version = "2"` makes `rule_version_requires_reset` return True, and assert `HORIZON_RULE_VERSION >= 3`. Confirm it fails. Result: failed before T022, as expected.

### Implementation for User Story 4

- [X] T022 [US4] In src/core/logic/horizon_identity.py set `HORIZON_RULE_VERSION = 3` and extend the comment above it: `3 (branch 033): only a value in DOI form is a DOI, so articles merged under a link or an ISSN are split by one rebuild.` T021 passes.
- [X] T023 [US4] Run `grep -rn "rule_version\|RULE_VERSION" tests docs` and update any test or document that states the version as the literal 2 (none is expected in tests: they import the constant). Run tests/test_rule_version_guard.py, tests/test_horizon_ids_flow.py, tests/test_horizon_id_assigner.py, tests/test_ensure_db.py, tests/test_save_horizon_id_history.py and tests/test_export_canonical_data_flow.py; all pass. Result: no literal version found in tests or docs; 40 passed.

**Checkpoint**: all stories pass.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T024 [P] Add to docs/backlog.md the entry `TD-039 — A value that is not a DOI merges different articles`: the defect (Scopus link without a DOI, ISSN), the numbers of the 2026-11-10 run (110 items, 69 hidden works, 45 stored non-DOI values; also on main and branch 022), the rule in one sentence, the stored value (bare DOI), the rule version 3 rebuild, and that journal and conference items with the same title and year (47 cases) stay a separate defect. Status: Done with the date once T027 passes. Result: entry added with status "Implemented; local and fork validation pending".
- [X] T025 [P] Run `.venv/bin/black --check`, `.venv/bin/isort --check-only` and `.venv/bin/flake8` on src/core/logic/horizon_identity.py, src/flows/lattes/projects.py and the six test files touched. Result (2026-11-10): black and isort clean on the 8 files (black reformatted one existing line of tests/test_horizon_identity.py made longer by T004); flake8 reports the same findings as before the change on these files (E402/F401 in src/flows/lattes/projects.py, not from this branch).
- [X] T026 Run the full suite `.venv/bin/python -m pytest -q` and record the counts against the 1045 passed, 10 skipped of spec 032; then run `make ci-check` (the constitution's gate before a merge) and record its result. If `make ci-check` fails on files this branch did not touch, record which and do not fix them here. Result (2026-11-10): 1080 passed, 10 skipped, 0 failed (35 new tests). `make ci-check` does not pass on this repository, before or after this branch: `make format-check` wants to reformat 46 files and `make lint` reports 578 findings, the same count with and without the change; none is in a line this branch added. Not fixed here.
- [X] T027 Local validation per quickstart.md sections 2 and 3 (ask the maintainer first; back up `db/horizon.db` and `data/` before): one `make weekly-flows` rebuilds the database because of the rule version; record the "rebuilding it once" log line, the `Horizon ids:` line (rule version 3, aliases created), and the results of the read-only check: 0 stored values that are not DOIs (45 before), about 20 articles fed by more than one title and all with a DOI, 0 without one (SC-001, SC-003, SC-004), a sample of the hidden works present as their own articles (SC-002), the counts of awards, languages and technical productions compared with the 2026-11-10 run (SC-005; a difference is accepted only for curricula downloaded again), and the old permanent id of the Scopus `doi=null` article (read from the backup database) found as an alias or reported as retired. Result (2026-11-10, local, backup in data/_backup_2026-11-10_pre033/): `make weekly-flows` exit 0, 19:16 to 20:30, every phase exit 0. Log: "Database rule version differs from the code's; rebuilding it once before the phases (FR-024)"; "Horizon ids: 70856 entities, 84 collision groups, rule version 3; aliases 1915 (58 new, 764 retired ...)". Read-only check: 0 of 2,539 stored DOI values lack DOI form (SC-003); 21 articles fed by more than one title, 2 titles at most, all with a stored DOI, 0 without one (SC-001, SC-004; the 21st is `10.3390/fishes6030031`, written with spaces in one curriculum and before kept as a second article); articles 7,979 -> 8,053 (75 titles added, 1 duplicate removed), 0 articles without an author; the sample work "Thermal comfort temperature update for broiler chickens up to 21 days of age" is its own article with its researcher (SC-002). SC-005: awards 183, academic educations 1,962, professional activities 7,855, research productions 3,727 and production authors 3,848 equal the database before the rebuild; the other differences come from the sources: 6 curricula changed between the two downloads (+6 advisorships, +2 articles, +7 and -1 initiatives) and the SigPesq group report has 353 rows instead of 354. Old ids: `article:doi:http://www.scopus.com/...doi=null...` and `article:doi:1982-9434` are in `horizon_id_aliases` with reason `retired`. One ERROR line in the log, `cnpq_group_url_invalid` for 1 group, a SigPesq registration problem that exists without this branch.
- [X] T028 Second local run per quickstart.md section 4 (same approval): `make weekly-flows` (the refresh share cannot be 0, so part of the curricula is downloaded again); record that every article change logged by the second `lattes_projects` run comes from a curriculum that changed and none from an unchanged one (SC-006), and that the articles of the unchanged curricula keep the same permanent ids and stored DOI as after the rebuild (User Story 4, scenario 3). Result (2026-11-10, local, copy of the rebuilt database in data/_backup_2026-11-10_post033_run1/): `make weekly-flows` exit 0, 20:35 to 21:27, every phase exit 0, no rebuild ("Horizon ids: 70856 entities ... rule version 3 ... history from ['database']"). 4 curricula changed between the two downloads. Articles: 8,053 before and after, 0 added, 0 removed, 0 rows changed, 0 permanent ids changed, 0 stored DOIs changed, 0 new article source records, 0 article entries in the change log (SC-006; User Story 4, scenario 3). Writes of the run that are not about articles and not from this branch: 21 SigPesq project source records whose only difference is the order of the names in `Estudantes` (same students), 22 initiative updates (4 by sigpesq_projects on dates, 16 by lattes_projects on status and dates, 2 by the enrichment loader on PJ 140 and PJ 170 = TD-038), 5 advisorship entries and 1 person dropped, from the changed curricula and SigPesq.
- [X] T029 Fork validation per quickstart.md section 5 (ask the maintainer first; only on the RafaelDeps fork): the first weekly of the branch and a second one over the restored database; the second writes no article change, and the exported `articles_canonical.json` has no `doi` containing `scopus.com` or lacking DOI form (SC-007 is covered by T021 and by the local rebuild of T027, because the branch's first fork run has no earlier database to restore). Result (2026-11-11, RafaelDeps fork, commit 8b3a36d): run 42951144113 (no earlier database of the branch, built from scratch, 1h31) and run 42990877931 (database restored by `make restore-weekly`, 50 min), both success, 22 phases exit 0 each, no ERROR line. Both report rule version 3; id history from ['zip'] in the first and from ['database'] in the second. `articles_canonical.json` has 8,056 articles and 2,540 DOIs in both runs, 0 DOIs outside DOI form and 0 containing `scopus.com`; between the two runs 0 articles added, 0 removed, 0 changed in any exported field, and the 8,056 article rows of `horizon_ids_canonical.json` and the 647 article rows of `horizon_id_aliases_canonical.json` are identical. The only id difference is one new entity that is not an article (70,871 to 70,872).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001; blocks every story (T002 -> T003 -> T004).
- **US1 (Phase 3)**: after Phase 2. T005-T008 -> T009 -> T010.
- **US2 (Phase 4)**: after Phase 2; independent of US1. T011-T013 -> T014 -> T015 -> T016.
- **US3 (Phase 5)**: after Phase 2; T017 is checked last, after US1 and US2 added their tests to the same file.
- **US4 (Phase 6)**: after Phase 2; independent of the other stories. T021 -> T022 -> T023.
- **Polish (Phase 7)**: after the stories; T027, T028 and T029 need the maintainer's approval, in that order.

### Within Each User Story

- Tests first, and seen failing where the task says so, before implementation.
- Tasks in the same file run in sequence: tests/test_horizon_identity.py (T002, T004, T006, T018), tests/test_lattes_articles.py (T005, T013, T017), tests/test_article_fill.py (T011, T012), tests/test_article_consolidation.py (T004, T008, T019), tests/test_tracking_keys.py (T004, T007), src/flows/lattes/projects.py (T010, T014, T015), src/core/logic/horizon_identity.py (T003, T022).

### Parallel Opportunities

- T006, T007 and T008 touch different files.
- T018 and T019 touch different files.
- T024 and T025 touch different files.

---

## Parallel Example: User Story 1

```bash
Task: "T006 article id of a non-DOI value in tests/test_horizon_identity.py"
Task: "T007 tracking key of a non-DOI value in tests/test_tracking_keys.py"
Task: "T008 duplicate audit ignores a shared non-DOI value in tests/test_article_consolidation.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001 baseline.
2. T002-T004: the rule and the test values in DOI form.
3. T005-T010: different works are no longer joined.
4. Stop and validate: US1 in tests.

### Incremental Delivery

1. MVP (US1): the data loss stops for new databases.
2. US2: the stored and exported DOI is the bare DOI.
3. US3: confirm nothing correct was split.
4. US4: rule version 3, so existing databases are rebuilt.
5. Polish: backlog, lint, full suite; then local and fork validation after approval.

US4 must be delivered in the same change as US1 and US2: without the rule
version bump an existing database would mix articles keyed by both rules.

---

## Notes

- No new setting, Makefile target or workflow input (FR-011).
- No Docker change and no third-party library change (FR-012).
- The Lattes parser is not touched: the raw value stays in the source record (FR-008).
- Commits only when the maintainer asks; nothing upstream before validation.
