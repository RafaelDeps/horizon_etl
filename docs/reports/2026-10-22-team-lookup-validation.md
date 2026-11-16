# Team Lookup Index — Validation Report (spec 015)

Date: 2026-10-22 · Spec: `specs/015-team-lookup-index/` · Branch:
`018-team-lookup-index` · Machine: the maintainer's local machine (12 cores).

## 1. Summary

- **Equivalence is proven** (SC-004). Controlled replays of the `sigpesq`
  persistence and of both Lattes phases produced **identical** results with the
  old and the new code: the same entity counts, the same initiative↔team links
  and the same team memberships, compared by name. The comparison covered both
  a 100-CV subset and all 435 CVs.
- **The full weekly run went from 8 h 04 min to 3 h 01 min**, with exit 0 on all
  19 phases.
- **Both Lattes phases are 2.3–5.2× faster** and no longer grow quadratically.
  The 20-minute targets (SC-001, SC-002) were **not** reached. The remaining cost
  is a different hotspot with the same pattern, in person and researcher name
  matching (section 5). The maintainer decided to close this feature with the
  current gain and address that hotspot in a new spec.

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 `lattes_projects` | < 20 min | 33.1 min (baseline 81.0) | **Not met** |
| SC-002 `lattes_advisorships` | < 20 min | 48.5 min (baseline 252.5) | **Not met** |
| SC-003 per-CV growth in `lattes_advisorships` (last 50 / first 50 CVs) | ≤ 1.5 | **1.38** in the full run (5.65 s → 7.80 s); 1.67 in the replay below, which ran on a loaded machine | Met in the full run |
| SC-004 controlled replay equivalence | Identical | Identical (SigPesq, 100 CVs, 435 CVs) | **Met** |
| SC-005 full weekly run | < 4 h 02 min | **3 h 01 min** (see the CNPq caveat in section 4) | Met |
| SC-006 test suite | Pass | New tests: 20/20 pass. Full suite: 447 pass, 6 fail; the 6 also fail on the base code (section 6) | Met for this feature |

`lattes_projects` per-CV time in the full run: 4.48 s (first 50 CVs) → 4.54 s
(last 50), ratio 1.01.

## 3. Controlled replays (SC-004)

Procedure: `specs/015-team-lookup-index/quickstart.md` §2.
- Frozen inputs: the SigPesq Excel reports and the 435 Lattes JSONs from the
  2026-10-21 run.
- Pre-Lattes snapshot: `db-init`, then SigPesq persistence, then a real
  `cnpq_sync`, all with the base code.
- Each pair of runs (base, feature) used its own copy of the database, outside
  the repository, with Telegram notifications disabled.

### 3.1 SigPesq persistence (fresh database)

| Table / set | Base | Feature |
|---|---:|---:|
| teams | 1 158 | 1 158 |
| team_members | 3 356 | 3 356 |
| initiatives | 809 | 809 |
| initiative_teams | 879 | 879 |
| advisorships | 590 | 590 |
| persons | 1 024 | 1 024 |
| initiative↔team links (by name) | — | identical |
| team memberships (by name) | — | identical |

| Step | Base | Feature |
|---|---:|---:|
| `persist_research_groups` | 24.2 s | 26.1 s |
| `persist_projects` | 23.1 s | 18.1 s |
| `persist_advisorships` | 370.2 s | **66.0 s** |

### 3.2 Lattes phases, all 435 CVs (from the pre-Lattes snapshot)

| Table / set | Base | Feature |
|---|---:|---:|
| teams | 11 801 | 11 801 |
| team_members | 39 383 | 39 383 |
| initiatives | 11 701 | 11 701 |
| initiative_teams | 11 771 | 11 771 |
| advisorships | 8 696 | 8 696 |
| persons | 17 517 | 17 517 |
| initiative↔team links (by name) | — | identical |
| team memberships (by name) | — | identical |

| Phase | Base | Feature | Speed-up |
|---|---:|---:|---:|
| `lattes_projects` | 71.4 min | 30.7 min | 2.3× |
| `lattes_advisorships` | 196.4 min | 47.4 min | 4.1× |

A 100-CV subset replay was also identical: projects 914 → 444 s, advisorships
2 326 → 584 s.

Replays ran concurrently with each other and with the full run, so their
absolute times are inflated. The comparisons within each pair are fair, because
both sides ran under the same load.

## 4. Full weekly run (`make weekly-flows`, feature code)

Log: `logs/weekly_015_validation.log`. 2026-10-22 10:38 → 13:40, Telegram
disabled.

| Phase | 2026-10-22 baseline (min) | Feature (min) |
|---|---:|---:|
| sigpesq | 8.0 | 4.0 |
| cnpq | 124.3 | 76.8 ⚠️ |
| lattes_download | 2.2 | 2.1 |
| lattes_projects | 81.0 | **33.1** |
| lattes_advisorships | 252.5 | **48.5** |
| extract_project_files | 4.7 | 4.6 |
| consolidate_duplicates | 2.7 | 3.2 |
| export_canonical | 3.7 | 4.4 |
| all other phases | 4.0 | 4.6 |
| **Total** | **484** | **181** |

**⚠️ CNPq caveat.** 85 of 350 groups failed with
`net::ERR_CONNECTION_RESET` within 8 minutes (11:13–11:21). The DGP portal reset
connections, most likely because of today's unusually heavy load: a full
`cnpq_sync` for the replay snapshot (09:00–10:38) ran immediately before this
run's CNPq phase. Failed groups return fast, so the 76.8 min understates the
phase. This run's CNPq data is incomplete. The failures are unrelated to this
feature (CNPq does not use the changed team matching), but they matter for the
planned CNPq concurrency work: retries and back-off on connection resets should
be part of it.

Team lookup summaries from this run:

```text
Team lookup [sigpesq_projects]: loaded=353 hits=1 created=86 refreshes=86 refresh_found=0 failed=0
Team lookup [sigpesq_advisorships]: loaded=440 hits=1684 created=718 refreshes=718 refresh_found=0 failed=0
Team lookup [lattes_projects]: loaded=1158 hits=588 created=2783 refreshes=2783 refresh_found=0 failed=0
Team lookup [lattes_advisorships]: loaded=3941 hits=1862 created=7844 refreshes=7844 refresh_found=0 failed=0
```

`failed=0` everywhere. `refresh_found=0` means that no team was created by other
code while these loaders ran. The incremental refresh is a safety net that this
run did not need.

## 5. What still costs time in the Lattes phases

`cProfile` of `lattes_projects` with the feature code (30 CVs, 532 s under
load):
- `ensure_team` now costs **0.9 s for 272 calls**, down from 296 s for 158 calls
  with the base code.
- What remains:

| Hotspot | Share | Cause |
|---|---:|---|
| `PersonMatcher.match_or_create` | ~62% | On a miss, it re-normalises every cached person name (~17 000) to compare, then again for the fuzzy pass: 5.4 M `normalize_name` calls in 30 CVs. The cache grows during the phase, which is why `lattes_advisorships` still slows down slightly. |
| `resolve_researcher_by_name` | ~26% | Re-normalises every researcher name (~7 600) on every lookup. |
| Prefect `_resolve_parameters` | ~5% | Prefect traverses the `researcher_index` task parameter on every CV (research.md R9). |

The first two hotspots are the same failure pattern as the team lookup:
pre-computing the normalised keys once is the expected fix. The third is task
**T023**. Its condition (a Lattes phase above ~15 min) was met, but it is
**deferred to the next spec** together with the two hotspots above, so that one
replay validates all three.

## 6. Test suite

- New and changed tests: `tests/test_team_synchronizer.py`,
  `tests/test_team_lookup_sql.py`, `tests/test_lattes_advisorships_loader_reuse.py`
  and `tests/test_team_management.py`. **20/20 pass.**
- Full suite (`tests/`, excluding `tests/integration`): **447 passed, 6 failed.**
  The same 6 tests also fail on the base code:
  - `test_download_lattes_flow.py`, three tests (browser/driver version checks);
  - `test_loader_mapping.py::test_research_group_loader_mapping`;
  - `test_sigpesq_adapter.py::test_sigpesq_adapter_logs_http_429_during_login`;
  - `test_weekly_etl_workflow.py::test_weekly_etl_workflow_runs_weekly_flows_with_notifications`.
- `black` / `isort`: the touched files are formatted. Both tools already
  reported 47 other repository files before this change.
- `flake8`: the touched files add one E402 in `src/flows/lattes/projects.py`. The
  new import follows the file's existing `faulthandler.enable()` header, which
  already produced the same warning for every other import in that file.

## 7. Follow-ups

1. **New spec: person and researcher name-matching index.** Pre-compute
   normalised keys in `PersonMatcher` and `resolve_researcher_by_name`, include
   T023 (Prefect `quote()`), and validate with the same controlled replay.
2. **CNPq phase spec:**
   - fix TD-008 (`get_all()` of researchers per group);
   - make group fetches concurrent with 4 workers and a single SQLite writer;
   - retry and back off on connection resets.
3. Revisit the ×10 phase ceilings in `src/flows/pipelines/weekly_orchestrator.py`
   using these durations.
4. Upstream note for `eo_lib`: `lazy="joined"` on `Team.members` /
   `TeamMember.person`.
