# Name-Matching Index — Validation Report (spec 016)

Date: 2026-10-22 · Spec: `specs/016-name-matching-index/` · Branch:
`019-name-matching-index` · Machine: the maintainer's local machine (12 cores,
NVMe ext4 for `db/`, tmpfs for `/tmp`).

## 1. Summary

- **Equivalence is proven** (SC-004). Controlled replays of `sigpesq`
  persistence and of both Lattes phases produced **identical** results to the
  spec 015 reference: the same counts, the same initiative↔team links and the
  same team memberships, by name. The spec 015 reference was itself proven
  identical to the pre-015 code.
- **The full weekly run went from 3 h 01 min (spec 015) to 2 h 09 min.** All
  19 phases exited 0, and this time CNPq collected all 350/350 groups. The run
  took 8 h 04 min before spec 015.
- **Lattes phases on the real disk:** `lattes_projects` 33.1 → **22.8 min** and
  `lattes_advisorships` 48.5 → **27.9 min**. That misses the 20-minute target.
  On the replay, whose database sits on tmpfs, they ran in **9.9 and 13.8 min**.
- The gap between the two is **SQLite commit latency**, not name matching. A
  commit costs **3.3 ms on the NVMe disk against 0.056 ms on tmpfs** (60×), and
  the ingestion commits per record. Each CV took about 2.1× longer on disk,
  uniformly. That is the next lever (section 5).

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 `lattes_projects` | < 20 min | **22.8 min** full run (disk); 9.9 min replay (tmpfs). Baseline 33.1 | **Not met** on disk |
| SC-002 `lattes_advisorships` | < 20 min | **27.9 min** full run (disk); 13.8 min replay (tmpfs). Baseline 48.5 | **Not met** on disk |
| SC-003 last 50 / first 50 CVs, `lattes_advisorships` | ≤ 1.2 | **1.32** per CV in the full run (1.23 per advisorship record); 1.88 per CV / 1.40 per record in the replay | **Not met** (close per record) |
| SC-004 controlled replay equivalence | Identical | Identical (SigPesq twice, Lattes 435 CVs) | **Met** |
| SC-005 full run excluding `cnpq` | < 104.5 min | **74.3 min** (128.7 − 54.4) | **Met** |
| SC-006 test suite | No new failures | 463 passed, 6 failed; the 6 are the pre-existing ones (spec 015 report §6) | **Met** |

On SC-003: the first and last 50 CVs do not carry the same work. In the full
run they hold 1 067 and 1 145 advisorships; in the replay, 773 and 1 041. CV
order comes from the directory listing, which changes when CVs are downloaded
again. The per-record ratio (1.23 in the full run) is therefore the better
measure of residual growth. That residual growth comes from the fuzzy
comparison, which still scans a candidate list that grows during the phase, and
from SQLite inserts into growing tables.

## 3. Controlled replays (SC-004)

Reference: the spec 015 replay outputs (`feature_sigpesq.db`,
`feature_lattes.db`), with the same frozen inputs and the same pre-Lattes
snapshot (clarification of 2026-10-22).

### 3.1 SigPesq persistence (fresh database)

| Table / set | Spec 015 | Spec 016 |
|---|---:|---:|
| teams / team_members | 1 158 / 3 356 | 1 158 / 3 356 |
| initiatives / initiative_teams | 809 / 879 | 809 / 879 |
| advisorships / persons | 590 / 1 024 | 590 / 1 024 |
| link and membership sets (by name) | — | identical |

Step times with spec 016: `persist_research_groups` 23.1 s, `persist_projects`
14.2 s, `persist_advisorships` 64.3 s.

### 3.2 Lattes phases, 435 CVs

| Table / set | Spec 015 | Spec 016 |
|---|---:|---:|
| teams / team_members | 11 801 / 39 383 | 11 801 / 39 383 |
| initiatives / initiative_teams | 11 701 / 11 771 | 11 701 / 11 771 |
| advisorships / persons | 8 696 / 17 517 | 8 696 / 17 517 |
| link and membership sets (by name) | — | identical |

| Phase (replay, tmpfs) | Spec 015 | Spec 016 | Speed-up |
|---|---:|---:|---:|
| `lattes_projects` | 30.7 min | 9.9 min | 3.1× |
| `lattes_advisorships` | 47.4 min | 13.8 min | 3.4× |

### 3.3 Unit equivalence

`tests/test_person_matcher_index.py` runs the pre-016 `PersonMatcher` (a
verbatim copy, used as an oracle) side by side with the new one on the same call
sequences. It compares the person returned by every call and the final cache
order:
- 1 000 queries over an 800-name cache in CI-sized tests;
- plus, run once, 3 seeds of 1 500 × 1 500, with ~200 fuzzy matches each.

All gave **0 mismatches**, under both the native and the pure-Python rapidfuzz
implementations. Researcher resolution and the memoised name key were checked
against oracle copies: 5 000 names × 8 flag combinations, ties, every tier,
mixed record types and renames.

## 4. Full weekly run (feature code, `make weekly-flows`)

Log: `logs/weekly_016_validation.log`. 2026-10-22 16:42 → 18:51, Telegram
disabled.

| Phase | Before 015 (min) | Spec 015 (min) | **Spec 016 (min)** |
|---|---:|---:|---:|
| sigpesq | 8.0 | 4.0 | **3.2** |
| cnpq | 124.3 | 76.8 ⚠️ | **54.4** (350/350 groups) |
| lattes_download | 2.2 | 2.1 | 2.1 |
| lattes_projects | 81.0 | 33.1 | **22.8** |
| lattes_advisorships | 252.5 | 48.5 | **27.9** |
| extract_project_files | 4.7 | 4.6 | 4.8 |
| consolidate_duplicates | 2.7 | 3.2 | 3.5 |
| export_canonical | 3.7 | 4.4 | 4.9 |
| all other phases | 4.0 | 4.6 | 5.1 |
| **Total** | **484** | **181** | **129** |

Spec 015's CNPq figure is understated because 85 groups failed with connection
resets. This run had no CNPq collection failures; the single ERROR line is the
known invalid `cnpq_url` in SigPesq.

Summary lines from this run:

```text
Person matching [sigpesq_projects]: email=0 canonical=693 exact=0 normalised=0 invariant=0 fuzzy=0 strict_rejected=1 created=285 create_failed=0
Person matching [sigpesq_advisorships]: email=6701 canonical=231 exact=0 normalised=0 invariant=0 fuzzy=0 strict_rejected=0 created=274 create_failed=0
Person matching [lattes_projects]: email=0 canonical=11427 exact=190 normalised=7 invariant=49 fuzzy=86 strict_rejected=177 created=3504 create_failed=0
Person matching [lattes_advisorships]: email=0 canonical=32780 exact=100 normalised=4 invariant=48 fuzzy=24 strict_rejected=193 created=5868 create_failed=0
Researcher resolution [lattes_projects]: lookups=1504 tier200=0 tier150=476 tier100=52 tier90=9 unresolved=967
Researcher resolution [lattes_advisorships]: lookups=0 tier200=0 tier150=0 tier100=0 tier90=0 unresolved=0
```

How to read them:
- **Most persons resolve through the canonical key.** That is a dictionary
  probe, so it was already cheap before this feature.
- **The fuzzy step is reached on every miss** (~9 400 creations plus ~370
  strict rejections in the Lattes phases). That is why its pre-processing and
  cutoff mattered.
- **`lattes_advisorships` shows 0 researcher lookups.** That phase resolves the
  CV owner through `resolve_researcher_from_lattes`, not by name. The zero line
  is expected.
- **`create_failed=0` everywhere.**

## 5. What still costs time

1. **CNPq (54–124 min).** It is now the largest phase by far, and it is
   network-bound. This is tracked as TD-014: 4 concurrent fetches with a single
   SQLite writer, the TD-008 researcher read per group, and retry/back-off on
   connection resets.
2. **SQLite commit latency (new finding).** Every per-CV time in the full run
   was ~2.1× its replay counterpart, for the same CVs and the same data sizes.
   The only difference is the database location: NVMe ext4 against tmpfs. A
   micro-benchmark gave 3.3 ms against 0.056 ms per commit. The ingestion
   commits per record, through `GenericSqlRepository.add` and the ETL's own
   `session.commit()` calls. Candidate fix, in ETL code only: set SQLite
   pragmas on connect (`journal_mode=WAL`, `synchronous=NORMAL`) through a
   SQLAlchemy engine event. Before adopting it, check that the final database
   file is complete when CI uploads it (the WAL is checkpointed on close).
   Expected effect: the Lattes phases move toward their replay times
   (~10–14 min). Tracked as TD-018.
3. **Fuzzy residual growth.** The candidate list grows during the phase, about
   +23% per-record cost across the advisorships run. This is small next to
   items 1 and 2.

## 6. Finding outside scope

`RAPIDFUZZ_IMPLEMENTATION=fallback` (set in `.github/workflows/weekly-etl.yml`
by commit `e0d137e` to avoid an AVX2 segfault) is not a value rapidfuzz
recognises. It accepts only `cpp` or `python`, so the native AVX2 code still
loads. The maintainer should decide the fix. Tracked as TD-017.
