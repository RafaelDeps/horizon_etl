# Weekly Pipeline Runtime and Language Study (Python vs Go vs Rust)

Date: 2026-10-22 · Scope: `make weekly-flows` on the local machine
(12 cores, 30 GB RAM, Python 3.14 venv), ~435 Lattes CVs.

## 1. Summary

- **Run 1** (2026-10-21 17:44 → 23:28, **5 h 44 min**) completed, but
  `lattes_advisorships` was killed by its 10 800 s ceiling at CV ~360/435, so
  advisorships were ingested only partially.
- The phase ceilings in `src/flows/pipelines/weekly_orchestrator.py` were
  multiplied by 10 (every entry of `_PHASES`).
- **Run 2** (2026-10-21 23:28 → 2026-10-22 07:32, **8 h 04 min**) completed with
  **exit 0 on all 19 phases**.
- **98% of the runtime is in three phases**: `lattes_advisorships` (252 min),
  `cnpq` (124 min) and `lattes_projects` (81 min).
- **The two Lattes phases are slow because of the algorithm, not the language.**
  For every ingested record, `TeamSynchronizer.ensure_team` reloads the whole
  `teams` table through the ORM (each team with its members, and each member's
  person and role, eagerly joined) and compares the new name against every team.
  That costs about 1.5 s per record, and the cost grows as the table grows.
- **The CNPq phase is network-bound.** The DGP mirror answered in 2–60+ s per
  page that night. Parsing a page takes 55 ms in Python.
- **Benchmarks:** keeping today's algorithm, Rust is 2.6× and Go 1.7× faster than
  Python on the hot path. Fixing the algorithm in Python makes the same work
  about 3 000× faster.
- **Recommendation: do not rewrite.** Fix the two access patterns and make the
  CNPq phase concurrent, all in Python. Projected weekly runtime: about
  1 h 15 min – 1 h 45 min, against 8 h today. GitHub-hosted runners stop any job
  at 6 h, so these fixes are mandatory for CI regardless of language.
- If a migration is still wanted later, **Go** fits better than Rust (section 6).

## 2. Per-phase results of both runs

Times come from the Prefect API (flow runs) and from the orchestrator log
`logs/weekly_run2_20261021.log` (run 2).

| # | Phase | Run 1 (min) | Run 2 (min) | Run 2 result |
|---|---|---:|---:|---|
| 1 | sigpesq | 6.5 | 8.0 | exit 0 |
| 2 | cnpq | 72.4 | **124.3** | exit 0 (1 group failed, 1 group with an invalid URL) |
| 3 | lattes_download | 1.7 | 2.2 | exit 0 |
| 4 | lattes_projects | 62.7 | **81.0** | exit 0 (2 786 created / 585 updated) |
| 5 | lattes_advisorships | 180+ (**killed by timeout**) | **252.5** | exit 0 (8 099 created / 1 607 updated) |
| 6 | extract_project_files | 4.7 | 4.7 | exit 0 (7 SigPesq attachment timeouts, warnings only) |
| 7 | enrich_projects | 0.2 | 0.2 | exit 0 |
| 8 | consolidate_duplicates | ~4.3 | 2.7 | exit 0 |
| 9 | export_canonical | 5.8 | 3.7 | exit 0 |
| 10 | knowledge_areas_mart | <0.1 | 0.1 | exit 0 |
| 11 | initiatives_analytics_mart | 1.9 | 1.3 | exit 0 |
| 12 | people_relationship_graph | 0.6 | 0.5 | exit 0 |
| 13–18 | openalex_citations, rank_docentes_impact, analyze_maturity, analyze_venues, impacto_dashboard, ppp_edital_report | ~2.4 total | 1.8 total | exit 0 |
| 19 | anonymize_backfill | <0.1 | <0.1 | exit 0 |
| | **Total** | **344** | **484** | **19/19 exit 0** |

Run 2 log totals: 3 `ERROR` lines, all from the CNPq phase:
- group `6594532777855485` failed to load;
- 1 group whose `cnpq_url` lacks the 16-digit DGP identifier, which has to be
  fixed in SigPesq;
- the phase summary reporting those failures.

There were 9 `WARNING` lines and no tracebacks.

Why run 2 was slower than run 1 with the same code:
- **cnpq (72 → 124 min):** the DGP portal was slower overnight; see section 3.2.
- **lattes_projects (63 → 81 min) and lattes_advisorships:** these phases scan
  every existing team for every new record. Run 2 completed advisorships, so it
  processed more records against a larger table (11 431 teams created in the run).

Prefect detail: in run 1, the killed `Ingest Lattes Advisorships Flow` still shows
as `Running` in Prefect, because the subprocess was killed before it could report
a final state.

## 3. Where the time goes

### 3.1 Lattes phases (projects and advisorships): `ensure_team`

Method: `cProfile` on the real flow functions, against copies of the database
(never `db/horizon.db` itself). Telegram hooks were not triggered.

| Profile | Wall time | `ensure_team` share | Main cost inside it |
|---|---:|---:|---|
| `lattes_projects`, first 15 CVs, 158 records | 440 s | **76%** (296 s) | `team_controller.get_all()`: 249 s over 158 calls |
| `lattes_advisorships`, CVs 300–309, 361 records | 1 470 s | **84%** (1 241 s) | `get_all()` 821 s, `normalize_text` 525 s (3.4 M calls) |

The cost comes from `src/core/logic/team_synchronizer.py:40`:

```python
existing_teams = self.team_controller.get_all()
for t in existing_teams:
    if t_name == team_name or normalize_text(t_name) == team_name_key:
```

1. **The table is reloaded for every record.** In `eo_lib`, `Team.members` is
   `lazy="joined"`, and so are `TeamMember.person` and `TeamMember.role`. With
   10 663 teams and 37 339 memberships, one `get_all()` builds about 3.7 M ORM
   objects and takes **1.5–1.9 s**. The same rows read with plain SQL
   (`teams ⟕ team_members ⟕ persons ⟕ roles`) take **175 ms**.
2. **Every existing team name is re-normalised for every record**, so the cost
   is O(records × teams). Both factors grow during the run, so each CV costs
   more than the one before. In run 1, `lattes_advisorships` went from
   0.22 min/CV at the start to 0.45 min/CV around CV 350.

Run 2 confirms it at full scale: 81 min / 3 371 records = **1.44 s per record**
(projects) and 252 min / 9 706 records = **1.56 s per record** (advisorships).
That matches the measured cost of one `get_all()` plus the name scan.

There is a second, smaller hotspot in `lattes_advisorships`. It builds a new
`ProjectLoader` for every CV (`src/flows/lattes/advisorships.py`, step 3), and
each new loader reloads all initiatives and all persons. In the profile that took
5.8 s per CV. `lattes_projects` already avoids this, as the comment at
`src/flows/lattes/projects.py:928` explains.

This is the same failure pattern as TD-007 (`ResearcherController.get_all()`
per CV), which was fixed for researchers with `load_researcher_index`.

### 3.2 CNPq phase: network

- Each group is fetched by `dgp_cnpq_lib.CnpqCrawler.get_data`, which launches a
  new headless Chromium per group, waits for the page, sleeps 1 s and closes.
  The 350 groups are fetched one after another.
- The 2026-09-19 CI log showed 90.5% of the phase (4 245 of 4 688 s) waiting
  right after `Navigating to …`. The ETL work per group (members, research lines,
  knowledge areas) takes about 0.1 s.
- The pages are plain server-rendered HTML; `curl` gets all 8–9 fieldsets without
  a browser. But plain HTTP alone is not much faster that night: 19 sequential
  fetches averaged **15.7 s**, ranged from 1.9 s to 60 s, and 2 hit the 60 s
  timeout. That is the portal's own latency, not Chromium.
- **Concurrency is what helps** (benchmark B4): 4 parallel fetches of 20 pages
  took **114 s of wall time against 397 s of summed fetch time (3.5×)**, with
  20/20 successes. This matches the earlier decision to parallelise `cnpq_sync`.
  It does not apply to SigPesq, which stays sequential.

## 4. Benchmarks: Python vs Go vs Rust

Toolchains:
- Python 3.14 (project venv);
- Go 1.27.3, official tarball, checksum verified, installed only in the session
  scratchpad;
- Rust 1.98.0 (already installed), built with `--release`.

All runs used the same database snapshot (10 663 teams, 37 339 memberships,
16 590 persons), the same 361 lookup names, the same 17 CNPq pages and the same
435 Lattes JSON files. Correctness check: in B1 all three implementations returned
**357/361 hits**, and in B2 all three extracted **2 104 table cells**, so the
normalisation and parsing are equivalent.

### B1: `ensure_team` hot path

- **Reload + scan** reproduces today's algorithm: reload the team graph and
  re-normalise every team name for each record.
- **Index** loads the graph once, builds a dict keyed by the normalised name, and
  answers each lookup with one hash probe.

| Implementation | Load graph once | Reload + scan, per record | Index, all 361 lookups |
|---|---:|---:|---:|
| Python + SQLAlchemy ORM (today: `TeamController.get_all`) | 1 481–1 903 ms | ~1 500–2 000 ms | n/a |
| Python + sqlite3 (plain SQL) | 175 ms | 380 ms | **466 ms** |
| Go (`database/sql` + `mattn/go-sqlite3`) | 171 ms | 230 ms | 246 ms |
| Rust (`rusqlite` bundled) | 127 ms | 147 ms | 165 ms |

Projected cost of `ensure_team` alone over run 2's 9 706 advisorship records:

| Approach | `ensure_team` time over 9 706 records |
|---|---:|
| Python + ORM, today | ~250 min (measured phase: 252 min) |
| Python plain SQL, same algorithm | ~61 min |
| **Go, same algorithm** | **~37 min** |
| **Rust, same algorithm** | **~24 min** |
| **Python + index** | **~2–5 s** |
| Go / Rust + index | ~1 s |

Reading:
- With the current algorithm, Rust beats Python by 2.6× and Go by 1.7×, measured
  against plain-SQL Python.
- Dropping the ORM read alone gives Python a 4–5× gain.
- Changing the algorithm gives more than 3 000×. Once the index is in place, the
  language difference no longer matters: a few seconds against one.
- Loading the graph costs about the same in all three (127–175 ms), because the
  work is inside SQLite, which is C everywhere.

### B2: parsing CNPq mirror pages (fieldset legends + every table cell)

| Implementation | ms per page | 350 groups |
|---|---:|---:|
| Python + BeautifulSoup (`html.parser`) | 55.2 | 19 s |
| Go + goquery | 4.2 | 1.5 s |
| Rust + scraper | 3.6 | 1.3 s |

Go and Rust parse 13–15× faster. Even so, Python's whole parse budget (19 s) is
0.3% of run 2's CNPq phase (124 min), and the remaining time is network.

### B3: loading the 435 Lattes JSON files (37 MB, generic tree)

| Implementation | All files |
|---|---:|
| Python `json` (C accelerated) | 434 ms |
| Go `encoding/json` (`map[string]any`) | 750 ms |
| Rust `serde_json::Value` | 305 ms |

This is irrelevant at the pipeline scale. Python beats Go here because its JSON
decoder is written in C.

### B4: CNPq fetch concurrency (Python, plain HTTP)

| Mode | Pages | OK | Wall time |
|---|---:|---:|---:|
| Sequential (sum of per-page times) | 20 | 20 | 397 s |
| 4 workers (`ThreadPoolExecutor`) | 20 | 20 | **114 s** |

Go's goroutines or Rust's tokio would give the same 3.5×: the gain comes from
overlapping waits on the portal, not from the language.

## 5. Projection: fix in Python vs rewrite

| Phase | Today (run 2) | Python with fixes (projection) | Go/Rust rewrite, same algorithms (projection) |
|---|---:|---:|---:|
| cnpq | 124 min | 30–40 min (4 workers, plain HTTP) | 124 min (network-bound; ~30–40 min only if made concurrent too) |
| lattes_projects | 81 min | 10–15 min | 15–30 min |
| lattes_advisorships | 252 min | 10–20 min (team index + one shared `ProjectLoader`) | 30–60 min |
| everything else | 27 min | 27 min | 20–27 min |
| **Total** | **8 h 04 min** | **~1 h 15 min – 1 h 45 min** | ~3 h 10 min – 4 h |

How these figures were derived:
- Python fixes: `ensure_team` is 76–84% of each Lattes phase (section 3.1) and
  drops to seconds with an index. The rest of each phase (writes, person
  matching, per-CV loader rebuilds) is the remaining share.
- Rewrite column: B1's per-record speedups applied to the same access pattern.

These are projections. Only the B1–B4 numbers and the two runs were measured.

GitHub Actions impact: `weekly-etl.yml` sets `timeout-minutes: 300`, and
GitHub-hosted runners stop any job at 6 h. Run 2's 8 h 04 min cannot finish in
CI. A Go/Rust rewrite that keeps the current access patterns would also sit near
or above that limit. The Python fixes bring it well under.

## 6. If a migration is still wanted: Go vs Rust

### 6.1 What has to be rewritten

| Code | Python lines |
|---|---:|
| `src/` (ETL, flows, adapters, logic) | 40 889 (of which `src/scripts` reports: 20 461) |
| `tests/` | 11 419 |
| `scriptLattes` (Lattes download/parse) | 12 014 |
| `research_domain` (domain model) | 3 195 |
| `eo_lib` (ORM entities and controllers) | 2 222 |
| `agent_sigpesq` (SigPesq portal automation) | 1 214 |
| `libbase` (generic repository/controller) | 459 |
| `dgp_cnpq_lib` (CNPq crawler) | 360 |
| **Total** | **~71 800** |

The five external libraries (~19 500 lines) live in other repositories and are
not modified from here, by project rule. A migration means rewriting them as new
libraries or as code inside the ETL.

### 6.2 Dependency mapping

| Python dependency (where used) | Go | Rust |
|---|---|---|
| Prefect (26 files with `@flow`/`@task`; orchestration, Telegram state hooks, UI) | No equivalent; a plain orchestrator or Temporal | No equivalent; a plain orchestrator |
| SQLAlchemy + `eo_lib`/`research_domain` models (67 files) | sqlc / sqlx / GORM | sqlx / Diesel / SeaORM |
| Playwright (`agent_sigpesq`, `dgp_cnpq_lib`, `scriptLattes`) | playwright-go (community), chromedp | chromiumoxide, fantoccini / thirtyfour (WebDriver) |
| Selenium (Lattes) | tebeka/selenium (unmaintained) | thirtyfour |
| pandas (11 files, mostly reports) | No mature equivalent; hand-written | Polars (strong) |
| networkx (3 files, graphs) | gonum/graph | petgraph |
| rapidfuzz / thefuzz | go-edlib and similar | rapidfuzz-rs / strsim |
| openpyxl (SigPesq Excel) | excelize (strong) | calamine (read) + rust_xlsxwriter |
| BeautifulSoup | goquery | scraper |
| infisicalsdk | Official Go SDK | REST API |
| Mistral (project document extraction) | REST | REST |
| loguru / pydantic | slog / validator | tracing / serde |

### 6.3 Comparison for this project

| Criterion | Go | Rust |
|---|---|---|
| Fit for an I/O-bound ETL (HTTP, browser, SQLite) | Very good: goroutines, `net/http`, simple concurrency | Good, but async Rust (tokio) adds complexity |
| Raw speed on the measured hot paths | 1.7× Python (B1), 13× (B2) | 2.6× Python (B1), 15× (B2) |
| Learning curve and pace of change | Short; fast compilation | Long (ownership, lifetimes, async); slower iteration |
| Browser automation (SigPesq, Lattes, CNPq) | playwright-go is usable | Weaker ecosystem |
| Data analysis and reports (`src/scripts`, 20 k lines) | Weak (no pandas equivalent) | Polars is strong, but the reports would still be rewritten |
| CI | Single static binary, no venv | Single binary; long cold builds without a cache |

The measured gains appear only where this pipeline does not spend its time
(parsing and JSON). Where it does spend time (database access pattern, portal
latency), the language does not change the outcome. If a rewrite is chosen
anyway, **Go** wins: I/O concurrency is simpler, iteration is faster, browser
automation is better supported, and Rust's extra 1.5× on CPU-bound code has no
measured payoff here.

## 7. Recommended actions (in priority order)

1. **Team index in `TeamSynchronizer`**: build a normalised-name → team dict
   once per phase (plain SQL or a non-eager query), update it when teams are
   created, and stop calling `get_all()` per record. Same pattern as
   `load_researcher_index`.
2. **One `ProjectLoader` for the whole `lattes_advisorships` phase**, as
   `lattes_projects` already does.
3. **Concurrent CNPq fetch** (4 workers) over plain HTTP, implemented inside
   `src/adapters/sources/` without modifying `dgp_cnpq_lib`; database writes stay
   on a single thread.
4. After 1–3 are measured, decide whether to bring the phase ceilings back from
   the temporary ×10 values.
5. Report upstream (not a prerequisite): `lazy="joined"` on `Team.members` /
   `TeamMember.person` in `eo_lib`, as TD-009 does for `Researcher`.

## 8. Reproducibility

Benchmark sources, profiles and database snapshots are in this session's
scratchpad (`…/scratchpad/bench/`, `…/scratchpad/prof/`, `…/scratchpad/runs/`)
and are not versioned. Run 2's full log is `logs/weekly_run2_20261021.log`.
