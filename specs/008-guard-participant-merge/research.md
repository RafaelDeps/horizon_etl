# Research: reliable participant deduplication

**Feature**: 008-guard-participant-merge | **Date**: 2026-08-28

## R1 — Evidence of the defect: duplicated participants in the exported data

**Observation**: the dashboard source data produced by the 2026-08-28 weekly run
(`researchers_canonical.json`, 9,738 records) contains 176 name groups with two
or more participant records. In every detected pair one record carries the
initiative data and the other holds none. The exemplar is the student **Israel
Magalhães do Carmo**, present as two `Person` records:

| id | initiatives | research groups |
|---|---|---|
| 579 | 5 (advisorships + research projects, role Student) | — |
| 5767 | 0 | "Núcleo de Estudos em Robótica e Automação" |

The two records share the identical normalized name and neither carries a strong
identifier; they are one person distributed over two rows.

**Why the dashboard shows it**: the weekly pipeline rebuilds the catalog from
many sources but never runs the participant deduplication step. An exporter then
joins every `Person` against its links, so a person split across two rows is
shown twice — and because the canonical exporter deliberately filters
research-group teams out of a researcher's `initiatives` list, the "second"
record looks like an initiative-less ghost. The user perceives it as
"duplicated, and the initiative data is incomplete".

**Alternative discarded**: treating the exporter's research-group filter as the
bug. The filter is correct — group membership is exported under
`research_groups`, not `initiatives`. The defect is upstream: two records for
one person.

## R2 — Where duplicates are born: several identity paths

Participant creation and matching are spread over at least these paths, each
with its own identity logic:

- `PersonMatcher.match_or_create` (`src/core/logic/person_matcher.py`) — used by
  `ProjectLoader` for teams, advisorships and projects. Exact name, canonical
  name and (non-strict) fuzzy matching, with an in-memory cache rebuilt per run
  via `preload_cache`.
- `resolve_or_create_researcher` / `resolve_researcher_by_name`
  (`src/core/logic/researcher_resolution.py`) — used by the SigPesq/research
  group path. Casefold equality and a normalized-title equality gate, no strong
  identifier on the person side.
- `resolve_researcher_from_lattes` (`researcher_resolution.py`) — used by the
  Lattes curriculum path. Scores candidates by Lattes ID, cnpq URL, normalized
  name and linked-data richness.
- `PersonConsolidator` (`src/core/logic/person_consolidator.py`) — a script-only
  post-processing step (`src/scripts/consolidate_duplicates.py`, `make
  consolidate-duplicates`), **not part of the weekly pipeline**. It groups by
  `PersonMatcher.canonicalize_name`, vetoes groups with conflicting strong
  identifiers, picks a winner by quality score and merges links.

The duplication survives because (a) the paths disagree on what identity is, so
the same person can be created by two different paths in the same run, and
(b) the one holistic pass runs by hand, not by default.

## R3 — The safety analysis: name as signal, strong identifiers as veto

The guiding question is *when two records are safe to merge*. The evidence says:

- **The normalized full name is the only signal present in every source.** The
  observed duplicates have no Lattes URL and no identification ID. Requiring an
  identifier to merge would merge almost nothing and leave the dashboard
  duplicated. So the name must be the primary criterion — this is what the user
  asked to redesign *yes, use it*.
- **Name alone is not sufficient.** Homonyms exist; junk records such as "Dr"
  and "PROF" exist (currently four Person records in the catalog). A merge in
  either direction is irreversible damage to two careers. So the name is
  necessary, never sufficient: a **blocking** condition is added — if the two
  records disagree on a strong identifier (a different Lattes ID, a different
  identification ID), they are homonyms, and the merge is refused and flagged.
- **Absence of identifiers must not block.** All of the observed pairs carry no
  identifiers. Vetoing "identity unknown" would make the guard vacuous. The only
  veto is *conflicting* identity evidence.

Decision: **two records are the same person iff their normalized names are
equal AND they do not carry conflicting strong identifiers.** Yes, the
normalized participant name is the primary identity criterion, exactly because
in this data it is the signal that both unifies the observed duplicates and
discriminates the documented homonyms.

**Fuzzy matching is excluded from merging.** The `PersonMatcher` path uses
`thefuzz` token-sort >= 90 for non-strict cases ("Jose Silva" vs "Jose da
Silva"). At the deduplication level that rounds distinct names into one identity
and would recreate the exact class of false merge the initiative guard exists
to prevent. Fuzzy matching may only *suggest* review candidates; it never
merges (FR-004).

**The initiative-level guard stays.** The prior bug was applying name-similarity
to *individual initiatives* — advisorships whose stored name is the thesis
title, shared across advisor/coadvisor curricula with different participants.
That guard (FR-012) is regression-tested, not loosened.

## R4 — Name normalization design

One shared key function serves every comparison path. Requirements derived from
real data:

1. **Accents/diacritics**: NFD decomposition, drop combining marks —
   `Magalhães` → `MAGALHAES`.
2. **Casing**: single case (uppercase) — `do Carmo` and `DO CARMO` equal.
3. **Whitespace**: collapse runs and trim — `"  Maria   Aparecida "` →
   `MARIA APARECIDA`.
4. **Punctuation**: every non-alphanumeric, non-space character becomes a
   separator — `Santos-Junior` → `SANTOS JUNIOR`, `M.Sc.` → `M SC` (see R4.7).
5. **Particles/connectors**: `DE`, `DA`, `DO`, `DOS`, `DAS`, `DI`, `DU`, `DEL`,
   `DELA`, `E`, `Y` canonicalize to a single lower-case form so capitalization
   differences never split one person. This matches the observed particle
   distribution (`de`/`dos`/`da`/`do`/`das`/`e`/`del`/`dela` are all present in
   the catalog).
6. **Multiple spaces from strips**: re-join on single spaces.
7. **Honorifics/degrees**: tokens that are honorifics or degree abbreviations
   (`DR`, `PROF`, `MSC`) are kept only if the surrounding comparison paths
   agree; the requirement is *deterministic and shared*, not that they are
   dropped. The four junk names in the catalog are a symptom of names stripped
   to an honorific, and the dedup pass flags names below a plausibility floor
   (e.g. fewer than two alpha tokens or single token) instead of merging them.

The existing `normalize_text` (`src/core/logic/initiative_identity.py`) and
`PersonMatcher.normalize_name`/`canonicalize_name` already implement most of
1–6 but differ subtly (punct set, particle set, case). The feature consolidates
them behind one key function so every path agrees; the tests pin the key
function as the contract.

## R5 — Merge semantics: union, preserve, resolve

**Complementary data is unioned, never discarded** (FR-005). Every link the
loser owns that the winner does not already own is transferred: advisorship
memberships, team memberships, initiative–person links, article authorships,
academic education, research-group/team memberships, emails, knowledge areas,
and the researcher-side record. A link that already exists with the same
(initiative/entity, role) on the winner is skipped as an exact duplicate —
"exactly once", not "always twice". This is the rule that fixes the observed
"incomplete" initiative data: the winner keeps its five initiatives and gains
the loser's research-group membership.

**Simultaneous initiatives survive** (FR-006) because identity is *participant*
identity: a person concurrently on advisorship A and project B is one person
with two links, and the link transfer is per (initiative, role). Nothing in the
merge collapses links by time.

**Same-researcher initiatives survive** (FR-007): a researcher shared across two
records is corroboration of the person (it narrows who "the same name" can be),
and all of that researcher's initiatives are transferred along with the links.
The identity of the person never depends on "which researcher" or "which
initiative".

**Winner selection** (FR-009) reuses the existing quality heuristic but makes it
deterministic and documented: strong identifier present, then email count,
advisorship count, team-membership count, article count, education count, and a
fixed tiebreak (lower id, i.e. older record). The winner's scalar fields (name
spelling, birthday) are preferred; a missing field on the winner is filled from
the loser (FR-010). Conflicting scalar values that are both present are resolved
by "winner wins" and logged.

**Homonyms are refused, not merged** (FR-008): any two members of one normalized
name group whose Lattes ID or identification ID disagree make the group a
refusal. Refused groups go to the deduplication report with the reason, and the
report is part of the pipeline output.

## R6 — Where the dedup runs and how it is tested

**Placement** (US5): a consolidation phase between the source-ingestion phases
and `export_canonical` in the weekly pipeline (the orchestrator's load-bearing
order). Being idempotent (FR-013), it is safe to run every week. The exports —
including `researchers_canonical.json` — then read an already-deduplicated
catalog, and the dashboard stops showing the ghost pairs.

**Testing approach** mirrors the discipline established by the *previous*
version of this feature: unit-level, no database, no network, seconds. The
consolidator and the key function are pure against an in-memory schema
(`tests/test_person_consolidator.py` already builds one via `sqlite3`), so the
scenarios are deterministic. The **mandatory experiment** (SC-005, same
principle as before) weakens a guard — e.g. removes the strong-identifier veto,
or the particle normalization — and the suite must fail; restoring the guard
makes it pass again. A regression test that has never been seen failing proves
nothing, and the original feature's 283 passing-yet-blind tests are the reason
this experiment exists at all.

**Alternatives discarded**:

- *Fuzzy-name merging.* Rounds distinct names into one identity; reintroduces
  the class of false merge the guard forbids.
- *Requiring a strong identifier to merge.* Merges nothing in practice; the
  observed duplicates have none.
- *Deduplicating only at display/export time, without touching the catalog.* A
  cosmetic fix; the catalog and every downstream consumer (reports, graphs,
  tracking) stay corrupted, and the union semantics have nowhere to live.
- *A one-off script + manual run.* Already exists and the defect persists every
  week; the fix must be in the pipeline path the user actually runs.