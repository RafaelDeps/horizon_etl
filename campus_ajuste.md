# Campus Allocation Enhancement Proposals (`campus_ajuste.md`)

## 1. Executive Summary & Problem Context

In the current ETL pipeline architecture, a person/researcher record does not have a direct foreign key column (`campus_id`) in the core database schema (`persons` or `researchers` tables). Instead, campus attribution is inferred dynamically during the export phase by [`ExportCampusResolver`](file:///home/rafael/horizon_etl/src/core/logic/export_campus_resolver.py).

### Current Bottleneck
[`ExportCampusResolver`](file:///home/rafael/horizon_etl/src/core/logic/export_campus_resolver.py#L85-L95) currently resolves a person's primary campus strictly by inspecting research group memberships:

```sql
SELECT tm.person_id AS entity_id, rg.campus_id, COUNT(*) AS weight
FROM team_members tm
JOIN research_groups rg ON rg.id = tm.team_id
WHERE rg.campus_id IS NOT NULL
GROUP BY tm.person_id, rg.campus_id
```

Consequently, any individual who is **not** formally registered as a member or leader of a CNPq Research Group (`research_groups`) is exported with `"campus": null`. This leaves out:
- **Undergraduate & Graduate Students / Fellows:** Active in research projects or advisorships, but not enrolled in research groups.
- **Project Coordinators & Participants:** Involved in SigPesq initiatives with defined execution campuses (`CampusExecucao`), but without registered research groups.
- **Lattes-Only Profiles:** Researchers, advisors, and co-authors extracted from curriculum data without an active research group link.
- **Unconsolidated Duplicates:** Persons split across multiple duplicate records due to slight name variations or missing identifiers where only one record had the group membership.

---

## 2. Proposed Architectural Solutions

### Solution 1: Hierarchical Multi-Tier Fallback (Cascade Resolver)
Expand [`ExportCampusResolver`](file:///home/rafael/horizon_etl/src/core/logic/export_campus_resolver.py) from a single query to a weighted priority cascade when resolving `"researcher"` campus:

1. **Tier 1 — Research Group Affiliation (Highest Confidence):**
   - Retain current behavior as primary signal: direct membership in a `ResearchGroup` linked to a `Campus`.
2. **Tier 2 — Project / Initiative Participation:**
   - Query project teams (`initiative_teams` and `initiatives`).
   - If a person participates in projects executed at a specific campus (e.g., via `initiatives.campus_id` or linked group campus), assign the dominant campus across active projects.
3. **Tier 3 — Academic Advisorships (Supervisor $\leftrightarrow$ Advisee Linkage):**
   - For students/advisees without their own group affiliation, infer their campus from their supervisor's primary campus or from the campus where the advisorship/scholarship program is registered.
4. **Tier 4 — Co-Authorship & Publication Network:**
   - For authors ingested purely via Lattes publications, evaluate the dominant campus among institutional co-authors.

---

### Solution 2: Direct Capture of Ingestion Metadata (SigPesq Fields)
Raw data sources such as SigPesq already provide explicit campus fields that are currently underutilized:
- `sigpesq_projects.py` extracts `CampusExecucao`.
- `sigpesq_advisorships.py` extracts `CampusExecucao` and `Campus`.

**Action:**
- Persist these execution campus references directly as participant affiliations or attribute assertions (`attribute_assertions`) during ingestion, ensuring that person-initiative linkages carry the explicit execution location without requiring an intermediate research group.

---

### 3. Pre-Export Person Deduplication & Link Consolidation
A significant portion of missing campuses stems from split identities:
- Record A: Created via Lattes (contains articles and education, `campus: null`).
- Record B: Created via CNPq/SigPesq (contains research group and `campus_id`).

**Action:**
- Ensure [`PersonConsolidator`](file:///home/rafael/horizon_etl/src/core/logic/person_consolidator.py) executes routinely in the weekly pipeline **prior** to running `ExportCampusResolver`.
- By performing union merges of `team_members` and `advisorship_members` onto the winning canonical record, the consolidated person naturally inherits all campus evidence.

---

### 4. Integration with Institutional Personnel Directory (SUAP / SIAPE)
Faculty and technical administrative staff (TAEs) have official departmental appointments:
- **Action:** Introduce an institutional staff reference file or API feed (e.g., SUAP or transparency portal data).
- Map institutional e-mail domains or employee IDs (`identification_id`) to their official home campus.
- This serves as an authoritative ground truth for employees regardless of whether their research groups have been updated on CNPq.

---

### 5. Weighted Evidence Scoring & Handling Ambiguity
To handle researchers active across multiple campuses or units:
- Define an evidence scoring model:
  $$\text{Score}(\text{Campus}) = 3 \times N_{\text{groups}} + 2 \times N_{\text{coordinated\_projects}} + 1 \times N_{\text{projects}} + 1 \times N_{\text{advisorships}}$$
- **Clear Dominance:** If one campus accounts for $>65\%$ of the total score, designate it as the primary campus.
- **Multi-Campus Designation:** If a person shows active, balanced involvement across multiple distinct campuses (e.g., faculty working across Rectory and regional campuses), classify the campus as `"Multicampi"` or `"Reitoria"` (Rectory) instead of leaving the field as `null`.

---

## 3. Recommended Implementation Roadmap

1. **Phase 1 (Low Effort, High Impact):**
   - Add Tier 2 (Project team members) and Tier 3 (Advisorship supervisor campus) to `ExportCampusResolver`.
2. **Phase 2 (Data Quality & Hygiene):**
   - Enforce `PersonConsolidator` execution in the weekly ETL orchestrator prior to canonical JSON generation.
3. **Phase 3 (Enterprise Integration):**
   - Ingest official personnel dataset (SUAP/SIAPE) to provide ground-truth affiliations for all institutional staff.

---

## Outcome (2026-09-03)

The five proposals above were measured against `db/horizon.db` and the SigPesq
reports in `data/raw/` before any of them was implemented. The results changed
the priority order significantly, and two proposals were dropped outright.
Implementation is tracked in `specs/010-campus-resolution-fallback/`.

| # | Proposal | Measured effect | Decision |
|---|----------|-----------------|----------|
| 1 — Tier 2 | Project participation | 161 people, and only via research groups — `initiatives` has no `campus_id` and `initiative_persons` is empty | **Implemented**, but sourced from proposal 2's asserted campus rather than from groups |
| 1 — Tier 3 | Advisorship supervisor | **1,936 people** | **Implemented** — the single largest gain |
| 1 — Tier 4 | Co-authorship network | 4 people, high risk of inheriting an external co-author's campus | **Rejected** |
| 2 | Persist SigPesq `CampusExecucao` | 587 advisorships + 102 projects with authoritative campus | **Implemented** as tracking attribute assertions |
| 3 | Run `PersonConsolidator` before export | Already runs (`weekly_orchestrator.py:74`); residual gain measured at **zero** (3 duplicate groups, 6 people) | **Already done** |
| 4 | SUAP/SIAPE integration | `persons.identification_id` is 100% empty; all 738 e-mails are anonymized to `anon.lgpd` — neither join key exists | **Rejected as infeasible** |
| 5 | Weighted scoring | The resolver already weights by count and already breaks ties deterministically | **Partly already done**; the "Reitoria" fallback was **rejected** |

Two corrections to the analysis above are worth recording, because the original
text asserts them the other way round:

- **`initiatives` has no `campus_id`, and `initiative_persons` is empty.** The
  Tier 2 design in section 2 assumed both existed. Project participation is
  expressed through `initiative_teams` → `teams` → `team_members`.
- **`Reitoria` is a real organizational unit.** Using it as an "ambiguous or
  unknown" label would fabricate data rather than express uncertainty. People
  with no usable evidence continue to export with a null campus.

Result: people with no campus fell from 3,198 (32.6%) to 1,262 (12.9%), with no
schema migration, no change to `research-domain`, and no person losing a campus
they already had.
