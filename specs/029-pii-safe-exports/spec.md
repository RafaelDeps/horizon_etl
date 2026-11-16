# Feature Specification: PII-Safe Exports and Deduplicated Articles

**Feature Branch**: `029-pii-safe-exports`

**Created**: 2026-11-05

**Status**: Draft

**Input**: User description: "Make published and restorable data free of plain personal data, stop stale and duplicate data, and purge the existing leak, while keeping the logic that reduces weekly workflow time (restore of previous run database/raw/cache, rotating raw downloads, skip of unchanged documents, portal early stop)."

## Clarifications

### Session 2026-11-05

Answered from the user's binding decisions and from read-only checks of the code and data on 2026-11-05. The user's answers to FR-016, FR-017, FR-018, the database and the history purge are recorded below.

- Q: Must the database be in the canonical export? → A: No. The user's decision is a condition, not an obligation: it MAY be included and restored from only if it holds no plain personal data. Restore does not read it from the archive today (it reads the run artifact). Settled below: it stays out of the archive.
- Q: Does the database fit in the committed archive? → A: Not as a plain addition. GitHub rejects files over 100 MiB; the archive is 56.4 MB and the database compresses to 80.3 MB with the archive's own format (136.7 MB together). See FR-019.
- Q: Does sanitizing database text invalidate the skip of unchanged documents? → A: No. The skip compares a hash of the source document as read, the rule version and the name references, never stored values. Sanitizing database text keeps skip behavior, provided names and rule version are untouched.
- Q: Does sanitizing raw downloads or cache invalidate that skip? → A: Yes, if done on stored files only. The hash is taken over the file content, so 1,217 of 2,376 tracked documents (Lattes curricula in two phases, CNPq pages) would be reprocessed, and rotation would keep reprocessing each freshly downloaded plain copy. See FR-020.
- Q: What does restore need? → A: Three items from the last successful run artifact of the same branch: the database, the raw downloads and the Lattes cache. Anything missing or broken ends in a rebuild, never a failed run. The published archive is read too: the permanent id history and the scrubbed project documents come from it. See FR-021.
- Q: Which public paths hold plain personal data? → A: More than first listed: the Lattes cache and the Lattes JSON folder, also uploaded in the artifact, and files tracked in git. Office files and PDFs compress their content, so a byte scan cannot clear them. See FR-003 and SC-002.
- Q: Where in the database is plain personal data? → A: Plain email addresses in three columns, one row each and the same single address (initiative descriptions, attribute assertion values, change-log after-snapshots). Six malformed email values remain in source-record payloads because the email pattern does not recognize them. person_emails and all other payload emails are tokens. Names are plain by design. See FR-001, FR-017, FR-022.
- Q: Can published hashes be used to recover plain values? → A: Possibly by guessing. Source-record payload hashes are unkeyed SHA-256 of the plain payload, and both they and assertion value hashes are published in the archive; document content hashes are unkeyed too. Tokens are keyed and are not reversible without the key. See FR-023.
- Q: Does FR-011 contradict FR-013 and SC-009? → A: Only if read as every article keeping its record. Surviving records keep their identifiers; a merged record's permanent id remains resolvable as an alias of the survivor, with no rule-version change.
- Q: Do "one DOI and none" articles merge? → A: Yes. A missing DOI is not a differing DOI (today's lookup already falls back to title and year); the survivor keeps the DOI. Two different DOIs stay separate, even with the same title and year.
- Q: Which step failures keep the previous archive (FR-009)? → A: Failures in critical phases, the export, the two marts, the graph, the content scan or the archive build. A portal early stop, or a non-critical phase scheduled after the archive build, does not block publishing.
- Q: Where is the coordinator's email in git history? → A: Inside 21 of 42 versions of the canonical archive and both versions of the tracked snapshot archive, and in no other tracked file, across the refs fetched locally. Those same archive versions also hold other plain addresses, so purging this one address does not clean history. Pull-request refs cannot be rewritten by a force-push and were not searched.
- Q: What is the official anonymization key? → A: The key held by the CI secret. Archives from both repositories share tokens, so CI uses one key; the local key differs (no token in common). Only the workflow publishes. See FR-012.
- Q: What counts as plain personal data (FR-017)? → A: Email, phone and CPF, including malformed values in fields known to hold them. Names and institutional addresses stay.
- Q: How do raw downloads and cache stay restorable (FR-018)? → A: They are encrypted in the CI artifact with a CI secret. Their content is not altered, so skip hashes stay valid and no re-ingest is needed.
- Q: What does "secure form" mean for that encryption? → A: The user's requirement is a form that discourages brute-force attacks and other vulnerabilities: a random 256-bit key from a secure generator (not a passphrase), separate from the anonymization key; authenticated encryption (AES-256-GCM or equivalent) with a maintained tool and no custom cryptography; tampering detected before anything is unpacked, then a fallback to rebuild; one bundle, so file names are hidden; extraction protected against path traversal; the key only in GitHub Secrets, never logged or on a command line; rotation possible; runs triggered from forks' pull requests do not get the key. See FR-024.
- Q: How is the database distributed? → A: It stays out of the committed archive, so the archive stays about 56 MB, and travels only in the run artifact. Unencrypted is acceptable only if verified free of plain personal data, including freed pages.
- Q: How far does the history purge go? → A: ALL plain emails are removed from old archive versions and tracked cache files, not only the coordinator's. A force-push cannot rewrite pull-request refs; forks and those refs need GitHub Support on both repositories.
- Q: What happens to public artifacts from before the fix (FR-016)? → A: They are deleted right after the first clean run on each branch (24 on origin, 4 on ifesserra-lab on 2026-11-05).
- Q: Does a match in the final content check stop the run (FR-002)? → A: No. From the design guidance (do not let the workflow break before it ends): a match is replaced by its token in the archive copy and reported by file and count, never by value. Publishing stops only when the check cannot run or the archive cannot be built. This replaces the earlier wording that a match fails the run; marked for the user's review in the plan.
- Q: Are public run logs in scope of FR-003? → A: Yes, as "publicly downloadable", found in planning: a library's debug output prints curriculum lines into the public log. See FR-003 and FR-016. Marked for the user's review in the plan.

### Session 2026-11-05 (user's answers to the plan's decisions D1-D9)

- Q: D1, where does the database travel? → A: Always inside the encrypted bundle, never plain. Skip hashes (`content_hash`) do not change. FR-004 is rewritten; the "plain if verified" option is gone.
- Q: D2, is a `fresh_database=true` run used to clear the existing duplicates? → A: No. The one-time `consolidate_articles` runs through the merge log; merged `~` ids become aliases of the survivor; `_apply_merges` gets a small guard so a suffixed id is never chosen as permanent.
- Q: D3, is a scan match a publish stop? → A: No. FR-002 stands as reworded: a match is replaced and reported.
- Q: D4, which title normalizer? → A: `normalize_text` (case, accents and punctuation), the one the article ids already use. FR-010 and SC-005 are updated; the baseline is recounted with it.
- Q: D5, public artifacts on branches that may never run again? → A: Deleted right after the first clean run on `main`. FR-016 is updated.
- Q: D6, public run logs? → A: The scriptLattes prints are silenced, and old workflow logs are deleted together with the artifacts, after the first clean run. FR-016 is updated.
- Q: D7, other tracked files and the purge's reach? → A: The purge also covers `.prefect/` history. `cache/`, `data/exports/data_snapshot.zip` and `.prefect/` are untracked from the tip. `MAILTO` in `src/scripts/fetch_openalex_citations.py` stays in the code and is not moved to `.env` (user decision, 2026-11-05). The 3 hits in `specs/013-curate-export-zip` are placeholders. The purge targets do not include these files, and its replacement list stays configurable (a terms file) but is not needed for them.
- Q: D8, old hashes in history? → A: The purge also blanks `payload_hash` and `value_hash` in old archive versions; a flag, on by default.
- Q: D9, the state key? → A: The user creates `HORIZON_STATE_KEY` on each repository before merge.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Published export contains no plain personal data (Priority: P1)

A data consumer downloads the published canonical export archive. No file in it contains a plain email address or other plain personal identifier; personal data appears only in anonymized (tokenized) form. Today a coordinator's email, embedded in free-text initiative descriptions (and the same path for advisorships), reaches the archive.

**Why this priority**: Active exposure of personal data in a public product.

**Independent Test**: Build the archive from data containing a plain email in an initiative description and in an advisorship; scan every file in the archive for email patterns and other known plain identifiers; expect zero matches.

**Acceptance Scenarios**:

1. **Given** an initiative whose description contains the coordinator's email, **When** the archive is built, **Then** the exported initiative shows an anonymized value instead.
2. **Given** an advisorship record with plain personal data, **When** the archive is built, **Then** it is anonymized in the output.
3. **Given** a future or bespoke exporter that forgets to anonymize, **When** the archive is assembled, **Then** a final check over the whole archive content detects the plain value, the archive copy carries its token instead, and the file and count are reported, never the value.

---

### User Story 2 - Public build artifacts and restorable state carry no plain personal data (Priority: P1)

Anyone can download the public CI artifacts. The raw downloads, Lattes cache, Lattes JSON, per-project JSON files, and the database (including descriptions, assertion values and change-log snapshots) contain no plain personal data, or are not exposed publicly. The database stays out of the committed archive.

**Why this priority**: The artifacts are public, retained up to 90 days (30 on artifacts from older workflow versions), and currently hold plain emails (see SC-002).

**Independent Test**: After a full run, scan every publicly downloadable artifact and the database content for plain emails; expect zero. Then run a second run restoring from them and confirm time-saving behavior still works.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** public artifacts are inspected, **Then** no file or database field contains a plain email.
2. **Given** a sanitized database, **When** it is scanned, including freed pages, **Then** it contains no plain unanonymized personal data, and it is not in the committed archive.
3. **Given** a following run restores previous state, **When** it runs, **Then** unchanged documents are still skipped, raw downloads still rotate, and the portal early stop still applies.

---

### User Story 3 - Existing leak removed from git history (Priority: P1)

The maintainer needs the coordinator's email and every other plain email gone from the archive versions and tracked cache files in all published git history, on several branches.

**Why this priority**: User decision; the data remains exposed otherwise even after the current fix.

**Independent Test**: Search all branches and tags on both remotes for the coordinator's email in file contents (including inside archived zips), and for any plain email in archive versions and tracked cache files; expect zero hits.

**Acceptance Scenarios**:

1. **Given** the cleanup is done, **When** all branches and tags are searched including zip contents, **Then** no plain email appears.
2. **Given** history is rewritten, **Then** the working tree content and the latest published export remain otherwise intact.

---

### User Story 4 - Export archive contains current marts and graph (Priority: P2)

The archive is created only after the knowledge-areas mart, initiatives analytics mart and people relationship graph are generated, so it carries up-to-date copies both locally and in CI. An earlier, untested attempt exists on another branch.

**Independent Test**: Run the full pipeline; the archive's marts and graph are as recent as the run and present in CI runs.

**Acceptance Scenarios**:

1. **Given** a full run, **When** the archive is inspected, **Then** all marts and the graph are present and match the run's output.
2. **Given** a failure before or while building the archive, **When** the run ends, **Then** the previously published archive is kept unchanged.

---

### User Story 5 - Same article is stored once (Priority: P2)

An article that differs from another only by letter case, accents, punctuation or DOI case is recognized as the same article and not duplicated. Existing duplicates (94 repeated title groups, 6 repeated DOIs) are consolidated.

**Independent Test**: Ingest two records differing only in case or accents of title (same year) or in DOI case; expect one article. Ingest two with different DOIs, or blank titles; expect two.

**Acceptance Scenarios**:

1. **Given** titles equal ignoring case and accents with the same year, **Then** one article exists.
2. **Given** DOIs equal ignoring case, **Then** one article exists.
3. **Given** the same title but different DOIs, **Then** they stay separate.
4. **Given** blank titles, **Then** they are never merged on title.

---

### User Story 6 - One anonymization key for everything published (Priority: P3)

Published tokens are consistent: an archive never mixes tokens made with different keys, and locally built archives cannot be mistaken for or published as official ones.

**Independent Test**: Attempt to publish an archive built with a non-official key; expect refusal or a clear marking. Compare tokens of the same person across consecutive published archives; expect equality.

**Acceptance Scenarios**:

1. **Given** a local build with a different key, **When** publishing is attempted, **Then** it is refused or clearly kept unpublished.
2. **Given** two official runs, **Then** the same person has the same token.

### Edge Cases

- Free text containing emails in unexpected fields or nested structures.
- Emails written with odd case or surrounding punctuation.
- Anonymizing the database must not change entity identifiers, nor trigger a database reset.
- A scan finding plain personal data in the final archive mid-run: the value is replaced by its token in the archive copy, the file and count are reported, and the run continues. A check that cannot run keeps the previous archive.
- Articles with a DOI on one record and none on the other merge, keeping the DOI.
- Restoring from an older artifact that still holds plain data: the first clean run sanitizes the database rather than discarding it, because discarding forces a full rebuild.
- Plain values that survive in freed database pages after sanitizing.
- Email values too malformed for the email pattern, in fields known to hold emails.
- A scan hit that is not an address (at-signs in journal names or titles).
- Fresh plain downloads next to stored copies during rotation must not look changed.
- Restoring data tokenized with another key: tokens are never re-derived, so keys would mix silently.
- History rewrite invalidates clones and open branches of collaborators.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All exporters, including initiatives and advisorships, MUST anonymize personal data in every field, including free text and nested values. Fields known to hold emails MUST be tokenized whatever the value's format.
- **FR-002**: Before publishing, the system MUST scan the complete archive content for plain personal data, independent of individual exporters, and the published copy MUST carry a token in place of any match; the file and count are reported, never the value. A match MUST NOT stop the run. If the scan cannot run, or a member cannot be scanned and cannot be left out, the archive MUST NOT be published.
- **FR-003**: Everything publicly downloadable (all paths uploaded in the run artifact, including raw downloads, Lattes cache, Lattes JSON, per-project JSON files and database, on successful and failed runs, public run logs, and files tracked in git) MUST contain no readable plain email or other plain personal data. Office and PDF files MUST be cleared by a check that reads their content, or kept non-public.
- **FR-004**: The database MUST stay out of the committed archive and travel only inside the encrypted state bundle in the run artifact (user decision D1). It is never uploaded plain, and `content_hash` and the other skip hashes are not changed.
- **FR-005**: Any state restored between runs MUST not expose plain personal data publicly, and the restore, rotation, unchanged-document skip and portal early-stop behaviors MUST continue to work.
- **FR-006**: Restoring from previous state that still holds plain personal data MUST sanitize it or discard it rather than propagate it.
- **FR-007**: The coordinator's email and ALL other plain emails MUST be removed from every archived version of the canonical and snapshot archives and from tracked cache files, `.prefect/` history included, in all git history on all published branches and tags of both repositories, with permanent ids in the rewritten latest archive intact. The rewrite MUST be a documented, re-runnable procedure with a verification, and runs only after the maintainer's explicit confirmation listing branches and remotes. The purge's replacement list MUST be configurable (OPEN, user decision pending: whether some email-shaped strings in `specs/013-curate-export-zip` and `src/scripts/fetch_openalex_citations.py` are real addresses). Copies reachable only through forks or pull-request refs MUST be purged through the hosting provider on both repositories.
- **FR-008**: The archive MUST be built after the knowledge-areas mart, initiatives analytics mart and people relationship graph complete, and include them.
- **FR-009**: If a critical phase, the export, a mart, the graph, the content scan or the archive build fails, the previously published archive MUST remain unchanged. A portal early stop MUST NOT count as a failure.
- **FR-010**: Article matching MUST ignore case, accents and punctuation in titles (with year), using `normalize_text`, and case in DOIs; two different DOIs or blank titles MUST NOT cause a match. A DOI present on only one record is not a difference.
- **FR-011**: Existing duplicate articles MUST be consolidated without losing their links to other records, including authors, tracking rows and per-document item records; the merged record's permanent id (including `~`-suffixed ids) MUST stay resolvable as an alias of the survivor. Consolidation runs through the merge log, with no `fresh_database` run.
- **FR-012**: A single official anonymization key, the CI secret, MUST be used for everything published and restored; archives or restorable state built with another key MUST NOT be published or restored from. Publishing happens only from the workflow.
- **FR-013**: Identifiers of surviving entities and the rule version MUST NOT change in a way that resets the database.
- **FR-014**: Weekly run duration MUST NOT materially increase.
- **FR-015**: Specs, logs and tests MUST NOT contain the real email; it is referred to as "the coordinator's email" and tests use synthetic addresses.
- **FR-016**: Public artifacts already published with plain data MUST be deleted right after the first clean run, never before it, so that run can still restore from them. For branches that may never run again, the deletion happens right after the first clean run on `main` (user decision D5). Old workflow run logs are deleted together with the artifacts (D6), and the scriptLattes prints are silenced so new logs hold no curriculum lines. The deletion is a script the maintainer runs after confirming.
- **FR-017**: "Plain personal data" means email, phone and CPF, including malformed values in fields known to hold them. Names and institutional addresses stay.
- **FR-018**: Raw downloads and cache MUST stay restorable by travelling encrypted in the CI artifact with a CI secret, unaltered, so skip hashes stay valid and no re-ingest is needed. With no usable key they MUST NOT be uploaded at all, and the run MUST NOT fail for that reason.
- **FR-019**: The committed archive MUST stay under GitHub's 100 MiB file limit; a build over the limit MUST NOT be published and the previous archive stays.
- **FR-020**: The unchanged-document skip MUST keep working across rotation: a fresh download and its stored copy with the same content MUST compare as unchanged, whichever form the stored copy has. Any re-baseline MUST happen at most once, MUST NOT bump the rule version, and that run MUST finish within the workflow's 300-minute limit.
- **FR-021**: The archive MUST keep the permanent id and alias files and the scrubbed project documents, which later runs read from it.
- **FR-022**: After sanitizing, the database file itself MUST hold no plain value in any page, including freed pages, and any stored value hash MUST be consistent with the sanitized value so later writes do not see a false change.
- **FR-023**: Hashes that are published or shipped MUST NOT allow confirming a guessed plain value: they are computed over sanitized content or with a key, without invalidating FR-020. In old archive versions in git history, `payload_hash` and `value_hash` are blanked by the purge (flag, on by default; D8).
- **FR-024**: The encrypted state MUST use a random 256-bit key from a secure generator, separate from the anonymization key, with authenticated encryption (AES-256-GCM or equivalent) from a maintained tool. It MUST be one bundle, so file names are hidden. Tampering MUST be detected before anything is unpacked and MUST end in a rebuild; extraction MUST be protected against path traversal. The key MUST live only in GitHub Secrets, never in a log or on a command line, MUST be rotatable, and runs triggered from forks' pull requests MUST NOT get it.

### Key Entities

- **Canonical export archive**: Published bundle of exports, marts and graph, without the database.
- **Restorable state**: Database, raw downloads and Lattes cache carried between runs in the run artifact; the published archive also supplies id history and project documents.
- **Public artifact**: Any file downloadable by anyone from CI or the repository, on any branch.
- **Article**: A publication matched by normalized title+year or normalized DOI.
- **Anonymization key**: The secret used to derive stable tokens.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A scan of the published archive finds 0 plain emails.
- **SC-002**: A scan of all public artifacts finds 0 readable plain emails. Baseline of the local copy on 2026-11-05: 338 raw CNPq pages, 47 raw project files, 14 of 16 raw Office files, 367 cache files, 329 Lattes JSON files, 21 project files, 3 tracked cache files, 4 members of a tracked snapshot archive, 1 archive member, and 3 database columns plus 6 malformed payload values. The compressed content of the 322 raw PDFs is not yet checked.
- **SC-003**: A search of all branches and tags on both remotes, including zip contents, finds 0 occurrences of the coordinator's email, and 0 plain emails in archive versions and tracked cache files.
- **SC-004**: 100% of full runs publish an archive with marts and graph from that same run; 0 archives with stale or missing marts.
- **SC-005**: 0 repeated article groups differing only by case, accents, punctuation or DOI case after consolidation, except groups with two different DOIs. Baseline with `normalize_text`, from the plan's count on the local database on 2026-11-05: 195 title+year groups (2 with conflicting DOIs) and 6 DOI groups; to be recounted by the verification task. 0 false merges in the test set of differing DOIs or blank titles.
- **SC-006**: Weekly run duration increases by no more than 10% versus the median of recent successful restored runs, excluding any single re-baseline run allowed by FR-020.
- **SC-007**: After a failed run, the published archive is byte-identical to before.
- **SC-008**: The same person has the same token across 100% of published archives; 0 published archives built with a non-official key.
- **SC-010**: 100% of published archives are under 100 MiB.
- **SC-011**: On a run after the first clean run, 0 documents with unchanged content are reprocessed because of sanitizing or rotation.
- **SC-009**: Entity identifiers are unchanged for 100% of surviving records, with one allowed exception: a surviving article whose id carried a `~` suffix takes the bare id once its collision is gone, and the old id stays resolvable as an alias. Merged articles resolve through aliases, and no database reset occurs.

## Assumptions

- Out of scope: merging the 116 repeated initiative groups, research productions, professional activities.
- Both repositories are public; the history rewrite is authorized by the maintainer and collaborators will re-clone.
- The "no more than 10%" duration limit is an assumed reading of "not materially grow".
- Artifacts count as public because both repositories are public.
- Implementation approach is decided in planning.
