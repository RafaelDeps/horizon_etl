# Concurrent CNPq Sync — Validation Report (spec 017)

Date: 2026-10-22 · Spec: `specs/017-cnpq-concurrent-sync/` · Branch:
`020-cnpq-concurrent-sync` · Machine: the maintainer's local machine.

## 1. Summary

- **Equivalence is proven** (SC-004). A controlled replay fed the 350 captured
  group payloads to the old and the new code, with random 0.5–3 s delays so that
  completions arrived out of order. The output was **identical** with 4 workers
  and with 1 worker: the same counts, the same memberships by name, the same
  group↔knowledge-area links and the same tracking records by type.
- **The CNPq phase went from 54.4 min (spec 016 run) to 28.3 min**, with 350/350
  groups collected, 0 retries, 0 failures and no concurrency reductions.
- **The full weekly run went from 2 h 09 min to 1 h 37 min**, with exit 0 on all
  19 phases. It took 8 h 04 min before spec 015.

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 CNPq phase, full local run | clearly below 54.4 min (~20–35 expected) | **28.3 min**, 350/350 groups | Met |
| SC-002 fetches in flight ≤ configured | always | Tests: peak = 4 with 4 workers and 1 with 1 worker. The real library in 4 threads peaked at 4 | Met |
| SC-003 no "database is locked", no writes from workers | none | 0 occurrences in the full-run log. Tests assert that every write runs on the flow thread | Met |
| SC-004 controlled replay identical | identical | Identical with N = 4 and with N = 1 (section 3) | Met |
| SC-005 temporary failures recovered by retries | in a simulated burst | Tests: temporary failures recovered (attempts 2–3), permanent ones reported, burst halves the limit, quiet period restores it. The real run had no failures to retry | Met (tests) |
| SC-006 test suite | no new failures | 476 passed, 6 failed (the same pre-existing 6) | Met |

## 3. Controlled replay

**Inputs**:
- **Payloads:** the 350 `cnpq_group_payload` records (347 distinct URLs) from
  the spec 016 validation database, exported read-only before any later run.
- **Snapshot:** a pre-CNPq database built with `db/create_db.py` plus the SigPesq
  persistence, from the frozen SigPesq reports of the same run.

**Harness**: it patches `CnpqCrawlerAdapter.get_group_data` to return the
captured payload after a per-URL random delay, then calls
`sync_cnpq_groups_flow()` with no portal access.

| Run | Time | Result vs base |
|---|---:|---|
| Base (spec 016 code, sequential) | 946 s | — |
| Feature, `HORIZON_CNPQ_WORKERS=1` | 834 s | **IDENTICAL** |
| Feature, `HORIZON_CNPQ_WORKERS=4` | **384 s** | **IDENTICAL** |

The N = 1 run gains ~110 s over base from the researcher index alone (TD-008).
The N = 4 run overlaps the simulated portal waits.

| Table / set | Base | Feature (N = 4) |
|---|---:|---:|
| research_groups / teams | 354 / 1 158 | 354 / 1 158 |
| team_members / persons / researchers | 11 469 / 7 184 / 6 685 | 11 469 / 7 184 / 6 685 |
| knowledge_areas / group_knowledge_areas | 1 561 / 1 954 | 1 561 / 1 954 |
| memberships, by name (with run-time start dates masked) | — | identical |
| group↔area links, by name | — | identical |
| `source_records` per type | — | identical (12 588) |

**Comparison detail**: 913 memberships have no start date in the source.
For those, the sync stamps the current time, so the value differs between any
two runs, including two runs of the old code. The comparator masks start dates
written on the replay day. That is pre-existing behaviour, not something this
feature introduced.

## 4. Full weekly run (feature code)

Log: `logs/weekly_017_validation.log`. 2026-10-22 20:24 → 22:02, Telegram
disabled. The notebook was moved to a different network during
`lattes_projects`, which uses no network; the run was not affected.

| Phase | Before 015 | Spec 015 | Spec 016 | **Spec 017** |
|---|---:|---:|---:|---:|
| sigpesq | 8.0 | 4.0 | 3.2 | 3.5 |
| **cnpq** | 124.3 | 76.8 ⚠️ | 54.4 | **28.3** |
| lattes_download | 2.2 | 2.1 | 2.1 | 2.0 |
| lattes_projects | 81.0 | 33.1 | 22.8 | 21.1 |
| lattes_advisorships | 252.5 | 48.5 | 27.9 | 24.7 |
| extract_project_files | 4.7 | 4.6 | 4.8 | 6.4 |
| consolidate_duplicates | 2.7 | 3.2 | 3.5 | 2.6 |
| export_canonical | 3.7 | 4.4 | 4.9 | 3.7 |
| all other phases | 4.0 | 4.6 | 5.1 | 4.9 |
| **Total (min)** | **484** | **181** | **129** | **97** |

⚠️ Spec 015's CNPq figure is understated: 85 groups failed with connection
resets in that run.

New CNPq line from this run:

```text
CNPq fetch: workers=4 fetched=350 retries=0 failed_after_retries=0 concurrency_reductions=0 researcher_index_loaded=525 researcher_hits=3772 researcher_created=6160
CNPq sync: 350/350 grupos sincronizados | 0 falha(s) de coleta | 1 URL(s) inválida(s)
```

How to read it:
- **Only 525 researchers exist before CNPq**, because SigPesq is the only earlier
  source. The phase therefore creates 6 160 researchers, which the index keeps
  in memory for later groups, and finds 3 772 existing ones.
- **The single ERROR line in the run** is the known invalid `cnpq_url`, which has
  to be fixed in SigPesq.
- The retry and burst paths were not triggered, because the portal was healthy.
  They are covered by the tests.

## 5. Observations and follow-ups

- **Retry and burst tuning.** The defaults are 3 attempts, waits of 30 s and
  90 s, and the rule "4 failures in 60 s halve the limit; 120 s of quiet restore
  one step". They were not exercised by a real burst. Revisit them if a run
  shows `failures clustering` lines.
- **Run-time start dates.** Members without a start date get the run's
  timestamp. That makes exports differ run to run, and it may deserve its own
  look (outside this feature).
- **Next levers:**
  - **SQLite commit latency** (TD-018): the Lattes phases are ~2× slower on disk
    than on tmpfs.
  - **Phase timeouts** (TD-015): still ×10.
  - **The `RAPIDFUZZ_IMPLEMENTATION` setting** (TD-017).
