# Phase 0 Research: Campus Resolution — SigPesq Execution Campus + Advisorship Fallback

**Feature**: `010-campus-resolution-fallback` | **Date**: 2026-09-03

All open questions from the Technical Context are resolved below. No
`NEEDS CLARIFICATION` markers remain.

---

## R1 — Where to persist the source-stated execution campus

**Decision**: Persist it as a tracking **attribute assertion**
(`attribute_assertions`) on the initiative or advisorship, under the attribute
name `execution_campus_id`, alongside the human-readable `execution_campus_name`.
Do **not** add a `campus_id` column to `initiatives`.

**Rationale**:

- Constitution Principle II makes `research-domain` the owner of canonical
  entities. `Initiative` is defined there
  (`.venv/lib/python3.14/site-packages/research_domain`), so adding a column
  would require changing an external package — which the project explicitly
  forbids: fixes belong inside `horizon_etl`, never in the shared library.
- `attribute_assertions` is an ETL-owned tracking table
  (`src/tracking/entities/attribute_assertion.py`) built for exactly this: a
  source-stated value, attributed to the source record that stated it, with
  `is_selected` and `selection_reason`. It satisfies Principle IV (audit-driven
  data quality) for free — every attributed campus is traceable back to the
  report row that stated it.
- The write path already exists and is already called for these very entities:
  `tracking_recorder.record_attribute_assertions(...)` in
  `src/core/logic/project_loader.py:518` records `tracked_attrs` for both
  `initiative` and `advisorship`. Adding the campus is a new key in that dict,
  not a new mechanism.
- The read path already exists too: `ExportCampusResolver` already queries
  `attribute_assertions` (`src/core/logic/export_campus_resolver.py:120`).

**Alternatives considered**:

- *Add `initiatives.campus_id`*: cleanest to query, but requires a schema
  migration plus a model change in `research-domain`. Rejected on both
  Principle II and the standing rule against editing the shared library.
- *Reuse `initiative_teams` by synthesising a campus-bearing research group*:
  would fabricate research groups that do not exist in CNPq, corrupting group
  counts in the dashboard. Rejected.
- *A new ETL-local table `initiative_campuses`*: possible, but it duplicates
  what `attribute_assertions` already models, and adds a migration for no gain.
  Rejected.

---

## R2 — How to resolve a campus name to a campus record

**Decision**: Reuse `SigPesqCampusStrategy.ensure(campus_ctrl, campus_name,
org_id)` from `src/core/logic/strategies/sigpesq_excel.py`, but call it through
a small guard that (a) strips a leading `"Campus "` token and surrounding
whitespace before lookup, and (b) refuses to create a campus for a name that
only differs from an existing campus by that token.

**Rationale**:

- `ensure` already normalizes via `normalize_text` (NFD accent-stripping,
  punctuation folding, case folding, whitespace collapsing), which handles
  `"Serra"` / `"serra"` / `"Serra "` correctly.
- It does **not** handle the `"Campus Serra"` form, and its fallback path is
  `create_campus`. Left unguarded, `"Campus Serra"` would create a 24th
  organizational unit named "Campus Serra" — a silent data corruption that
  SC-006 forbids.
- The dirty variants were observed only in the advisorship `Campus` column
  (the student's self-declared campus, 94/115 filled). `CampusExecucao` is
  clean and 100% filled on every report inspected, so the guard is defence in
  depth rather than the primary path.

**Alternatives considered**:

- *Trust `ensure` unchanged*: rejected, creates duplicate campuses.
- *Never create, only match*: attractive, but a genuinely new campus appearing
  in the sources would then be silently dropped. The guard keeps creation
  possible while blocking the known-bad prefix form.
- *Normalize inside `normalize_text`*: rejected — `normalize_text` is shared by
  identity keys across the codebase, and stripping a "campus" token there would
  change project- and group-name matching too.

---

## R3 — Which source column feeds the execution campus

**Decision**: `CampusExecucao` for both projects and advisorships, keeping the
existing fallback to `Campus` for advisorships. Do not introduce
`CampusOrientador`.

**Rationale**:

- `src/core/logic/strategies/sigpesq_projects.py:77` already maps
  `CampusExecucao` → `campus_name`, and
  `src/core/logic/strategies/sigpesq_advisorships.py:126` already maps
  `CampusExecucao` with a `Campus` fallback. The mapping layer needs no change
  at all — only the loader's use of the value does.
- `CampusExecucao` is the campus where the work is executed, which is the
  correct semantic for attributing the initiative and its participants.
- `CampusOrientador` (the supervisor's own campus) is filled 115/115, but adding
  it would create a second, competing signal for the same person that the
  supervisor-fallback tier already covers from the database side. Keeping one
  signal keeps precedence explainable.

**Alternatives considered**:

- *Prefer `Campus` (student's campus) for advisorships*: rejected — it is the
  dirtiest column (94/115, unnormalized) and describes the student's home
  campus, not where the advisorship runs.

---

## R4 — How the supervisor fallback avoids inference chains

**Decision**: Compute the fallback in a **separate second pass**, after the
primary map of directly-evidenced campuses is built, reading supervisors'
campuses only from that first map, and writing results into a distinct
inference layer that is consulted only when the direct layer has no answer.

**Rationale**:

- `ExportCampusResolver._ensure_loaded` already uses this exact
  build-then-derive shape twice: it builds `primary_from_direct`, derives
  source-record campuses from it, rebuilds as `primary_with_sources`, then
  derives ingestion-run campuses. The fallback follows the established pattern
  rather than inventing one.
- Reading supervisors from the frozen direct map makes chaining structurally
  impossible (FR-008): an inferred campus is never in the map the inference
  reads from. Ordering of rows therefore cannot affect the outcome, which is
  what SC-005 (determinism) requires.
- Keeping the inferred results out of the direct counter guarantees FR-007
  (direct evidence always wins) without needing per-evidence priority values
  inside the existing `Counter`.

**Alternatives considered**:

- *Add supervisor evidence into the same weighted `Counter` with a low weight*:
  simpler to write, but a person with one weak group membership and five
  supervisor-inferred hits would flip to the inferred campus. Violates FR-007.
  Rejected.
- *Iterate to a fixed point so students of students inherit transitively*:
  rejected — it is non-deterministic in the presence of cycles and spreads a
  single attribution across arbitrarily long chains.

---

## R5 — Tie-breaking

**Decision**: Keep the existing tie-break unchanged, and pin it with a
regression test.

**Rationale**: `_build_primary_map` already sorts candidates by
`(-count, campus_name, campus_id)`
(`src/core/logic/export_campus_resolver.py:218`), so equal weights are already
broken by campus name and then by id — deterministically, independent of SQL row
order. SC-005 is therefore already satisfied by the current code; the risk is
that a future edit replaces this sort with `Counter.most_common`, whose order for
equal counts is insertion order. The work here is a test that fails if that
happens, not a behaviour change.

**Alternatives considered**: *Switch the tie-break to lowest campus id only*:
rejected — it would change the exported campus of anyone currently tied, for no
benefit, violating SC-004's no-regression intent. The inference layer added by
this feature reuses the same helper, so it inherits the same ordering for free.

---

## R6 — Propagating an initiative's campus to its participants

**Decision**: Treat a person as having direct evidence for campus C when they
are a member of a team linked to an initiative whose asserted execution campus
is C, via `initiative_teams` → `team_members`.

**Rationale**: `initiative_persons` is empty (0 rows) in the current database —
the association actually used is `initiative_teams` → `teams` →
`team_members` (4,126 link rows). Any design keyed on `initiative_persons`
would silently do nothing. Measured: 3,565 people sit on initiative teams, 2,829
of whom have no campus today.

**Alternatives considered**: *Use `initiative_persons`*: rejected, no data.

---

## R7 — Verification baselines

**Decision**: Verify against `db/horizon.db` as it stands, using the counts
measured on 2026-09-03: 9,626 researchers exported, 3,018 (31.4%) with a null
campus; 6,608 people covered by research-group evidence; 1,936 people reachable
by the supervisor fallback; 587 SigPesq advisorships and 102 SigPesq projects
carrying an execution campus.

**Rationale**: The supervisor fallback needs no re-ingestion (FR-011), so its
gain is measurable immediately by re-running the export. The execution-campus
gain requires re-ingesting the SigPesq reports in `data/raw/`, which are
present in the repository.

**Caveat**: The most recent ingestion was scoped to the Serra campus, so the
absolute counts will grow once other campuses are ingested. The assertions in
the success criteria are stated as ratios and as no-regression rules so they
remain valid as the dataset grows.

---

## R8 — Relative weight of research-group membership

**Decision**: Research-group membership counts with weight **3**; an asserted
execution campus counts with weight 1. Both remain direct evidence, resolved by
the same weighted count — the group simply has to be clearly outnumbered before
it loses.

**Rationale**: The first full run with equal weights moved **52** people to a
different campus than the group rule gave them, and every single move was toward
Serra. That is not a signal about those people; it is the shape of the
ingestion. 777 of the 806 execution-campus assertions in that run were Serra,
because the weekly pipeline is currently scoped to Serra — so any researcher who
joins a loaded project inherits the only campus that happens to be loaded. Worse,
7 of the 52 moves were exact 1-1 ties broken alphabetically, where "Serra"
simply sorts before "Vitória".

The two evidences also mean different things: the group says where the person is
attached, the execution campus says where one project they joined runs. Treating
them as interchangeable conflates affiliation with activity.

Weight 3 was chosen so that a bare majority cannot unseat the group, while
genuine dominance still can. Re-measured on the same database, the moves fall
from 52 to **33** — 32 by real dominance and 1 remaining tie — with coverage
unchanged, since weights decide *which* campus, never *whether* there is one.

**Alternatives considered**:

- *Keep equal weights*: rejected after the 52 moves were reviewed. The bias
  would self-correct once every campus is ingested, but the export is consumed
  now.
- *Let the group win ties only*: fixes the 7 arbitrary moves but leaves the 45
  narrow-majority ones, which have the same cause.
- *Hard precedence, group always wins*: rejected — it would discard the source's
  own statement about someone with one stale group membership and twenty
  projects elsewhere, which is the case the execution campus exists for.
