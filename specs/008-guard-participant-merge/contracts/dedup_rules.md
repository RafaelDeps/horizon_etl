# Contract: matching rules the test suite fixes

**Feature**: 008-guard-participant-merge | **Date**: 2026-08-28

These are the behavioral rules the suite must guarantee. They are not a
description of the current implementation: they are the contract every future
implementation must honor. Violating any of them must make at least one test
fail.

## Part 1 — Initiative-level matching (prior art, kept in force)

### R1 — An advisorship never matches by approximate name

When resolving an advisorship, the match **must not** return another advisorship
only because the titles coincide after normalization.

*Why*: the stored name is the title of the work and legitimately repeats between
advisor and co-advisor, with different participants in each record.

### R2 — A project matches by approximate name

When resolving a project, the match **must** return the existing project whose
name coincides after normalization, even when the spelling differs.

*Why*: in a project the name identifies the entity; different spellings are the
same project coming from different sources.

### R3 — Exact name takes precedence over approximate

When an exact name coincidence exists, it prevails over any normalization-based
match.

### R4 — The persisted name prevails

Once equivalence is recognized by R2, the already-stored name is **not**
replaced by the name of the record that arrived.

*Why*: renaming makes the row dispute a name another row can occupy, which
discards the record for violating uniqueness.

### R5 — A missing index does not break

A missing, empty index or an empty title produces "not found", never an error.

## Part 2 — Participant-level deduplication (this feature)

### R6 — The normalized full name is the primary identity criterion

Two participant records are candidates for being the same person
**only when** their normalized full-name keys are equal. Exact-key equality is
required; fuzzy similarity (e.g. token-sort ratio) must **not** merge
participants at deduplication time.

*Why*: the name is the only signal shared by all sources (the observed
duplicates carry no strong identifiers), and exact equality keeps homonyms and
distinct names distinct.

### R7 — Normalization is one shared, deterministic key function

Normalization must be performed by a single shared function used by every
participant comparison path. The function must be case-insensitive, strip
diacritics (NFD + drop combining marks), collapse whitespace, turn punctuation
and hyphens into separators, and canonicalize surname particles (`DE`, `DA`,
`DO`, `DOS`, `DAS`, `DI`, `DU`, `DEL`, `DELA`, `E`, `Y`) to a single lower-case
form. The same key must result from any spelling that differs only in these
dimensions.

### R8 — Conflicting strong identifiers veto the merge

A normalized-name group **must not** be merged when any two members disagree on
a strong identifier (a distinct Lattes/CNPq URL, or a distinct identification
ID). Such a group is a homonym group: it is **refused and flagged for review**,
never merged.

### R9 — Missing strong identifiers do not block the merge

Two members with equal normalized names and *no* strong identifiers on either
side **must** be merged. Absence of identity evidence is not grounds to refuse;
only *conflicting* identity evidence is.

### R10 — Merging is a union, never a discard

When a group is merged, every link the losing record owns must be transferred to
the winner — advisorship memberships, team memberships, initiative links,
article authorships, academic education, research-group/team memberships, emails,
knowledge areas and the researcher-side record — unless an identical
(entity, role) link already exists on the winner, in which case it stays once.
No link held by the losing record may be dropped.

### R11 — Simultaneous and same-researcher initiatives survive the merge

Consolidating a person must preserve every initiative the person holds,
including initiatives that overlap in time and initiatives that share the same
researcher. Distinct initiative sets are **not** evidence of distinct persons,
and shared researchers are **not** evidence of duplicate persons.

### R12 — Winner selection and field conflicts are deterministic

The winner is the member with strong identifiers, then the richest linked data,
then a fixed tiebreak (the lower, i.e. older, record id). The winner's scalar
fields prevail; a missing winner field is filled from the loser. Any conflict
where both records hold a differing value is resolved by "winner wins" and every
such conflict is recorded in the deduplication report.

### R13 — Junk names are refused

A member whose normalized name is not plausibly a person's name (fewer than two
alpha tokens, or an honorific-only token such as `DR`, `PROF`) is flagged and
never merged with anything.

### R14 — Deduplication is idempotent and part of the pipeline

Running the deduplication step twice over the same catalog changes nothing on
the second run, and the step runs **before** the canonical exports in the weekly
pipeline, so the exported catalog is already deduplicated.

## Observable consequence (what the second layer checks)

Two advisorship rows with the same title and different participants still reach
their handler **without** an existing initiative attached — creation, not
update (R1–R5, prior art).

The Israel Magalhães do Carmo pair (Person 579 with five initiatives and
Person 5767 with a research-group membership only, no strong identifiers) is
recognized as one person: the surviving record owns **both** the five
initiatives **and** the research-group membership (R6, R9, R10). Two "José da
Silva" records with distinct Lattes URLs are refused as homonyms and appear in
the report (R8).

This is the assertion the previous suite did not make, and why the duplicated
participant reached the dashboard.