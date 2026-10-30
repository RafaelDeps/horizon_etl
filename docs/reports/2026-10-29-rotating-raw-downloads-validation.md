# Download Only What Is New Plus a Rotating Share — Validation Report (spec 023)

Date: 2026-10-29 · Spec: `specs/023-rotating-raw-downloads/` · Branch:
`026-rotating-raw-downloads` (fork RafaelDeps) · Code: `a11dacc` (CI runs),
then the fix `7cdfe65`.

## 1. Summary

- **CNPq**: the phase downloads only a quarter of the pages and reuses the
  stored ones, and went from 15.6 min (spec 022 steady state) to **3.9 min**
  on CI. Of 347 groups, it downloaded 87 again and reused 260; 3 pages had
  changed (SC-002: at most about 6 min).
- **Lattes**: 109 curricula are downloaded again per run, the oldest quarter.
  Before this spec, a cached curriculum was never downloaded again on CI once
  spec 022 kept the cache, so Lattes data stopped updating. The refresh found
  real changes: 99 CVs were processed again and 12 dropped items deleted.
- **Provenance**: `source_document_states_canonical.json` has the new field
  `downloaded_at`. It is set for 2,257 of 2,376 documents; the 119 without
  one are the CVs the portal served as "Nome-nao-identificado", which fail
  and are never read. No other export changed its fields.
- **A failed download never loses a copy.** Tests cover this, and a local
  run with every CNPq download failing completed with all 347 groups
  processed from their stored pages.
- **Found and fixed**: a curriculum the portal served as
  "Nome-nao-identificado" counted as a good download, so it would not be
  downloaded again for about four weeks. The first CI run got 73 of them.
  It now loses its date and is retried on the next run (`7cdfe65`).
- **Found, not fixed** (TD-029): one refreshed CV fails as `partial`,
  because a project title collides with another initiative's name
  (`UNIQUE initiatives.name`). It keeps its previous data.

## 2. Success criteria

| Criterion | Target | Result | Status |
|---|---|---|---|
| SC-001 coverage | every item downloaded again within 4 runs | Tests (simulated 4 runs) and a local run on the real cache: 109 / 218 / 327 / 435 of 435 dated after runs 1–4 | Met locally; CI has run the first rotation only |
| SC-002 CNPq time | ≤ 40% of 15.6 min | 3.9 min (25%) | Met |
| SC-003 no lost copy | 0 | Tests: a failed refresh keeps `cache/<id>` byte for byte; a failed page uses the stored copy. CI run 2: 0 download failures | Met |
| SC-004 provenance | 100% of documents dated | 2,257 / 2,376; the 119 undated are unidentified CVs, which fail and are never read | Met for every document that is read |
| SC-005 portal down | groups keep their data | Local: 347 failed downloads, all processed from stored pages, 0 failed documents; integration test with the portal fully down. CI run 4: the CNPq portal hung, the phase timed out, and the data stayed intact, but the stored pages were not used (section 7) | Met for data safety; the fallback needs a time limit |
| SC-006 exports | same files and fields | Same 38 files and fields as the spec 022 export; one field added to the states export | Met (counts: see section 4) |

## 3. CI runs

| Run | Restore | CNPq downloads | Lattes downloads | Total |
|---|---|---|---|---|
| [40934866237](https://github.com/RafaelDeps/horizon_etl/actions/runs/40934866237) | `rebuilt — no successful run` (new branch) | new 347 | new 422, refreshed 4, reused 9 | 1 h 52 min |
| [40952053776](https://github.com/RafaelDeps/horizon_etl/actions/runs/40952053776) | restored from 40934866237 | refreshed 87, reused 260, failed 0 | refreshed 109, reused 326, failed 0 | 39 min 22 s |

Per phase (minutes):

| Phase | Spec 022 steady state (40914744437) | Spec 023, run 2 |
|---|---:|---:|
| sigpesq | 0.6 | 0.8 |
| cnpq | 15.6 | **3.9** |
| lattes_download | 1.6 | 7.7 |
| lattes_projects | 0.2 | 3.0 |
| lattes_advisorships | 0.1 | 4.0 |
| extract_project_files | 5.5 | 6.0 |

The rotation moves time from CNPq to Lattes. CNPq saves about 12 min, while
Lattes now spends about 6 min downloading 109 curricula, which it did not do
before. Run 2 also processed the CVs that changed in the refresh and the
one-time convergence after a rebuild (spec 021 report, section 4), so its
Lattes phases are not yet the steady state.

## 4. Export counts

Compared with the spec 022 export (`be9a126`):

| File | Spec 022 | Spec 023 run 2 |
|---|---:|---:|
| `researchers_canonical.json` | 17,445 | 16,666 |
| `initiatives_canonical.json` | 12,535 | 11,598 |
| `articles_canonical.json` | 7,209 | 6,590 |
| `research_groups_canonical.json` | 353 | 353 |

The drop comes from the source, not from the rotation:

- This branch's database started from scratch on run 1. That day, the portal
  served 73 curricula as "Nome-nao-identificado", against 36 on the spec 022
  run, so those CVs' projects, articles and people were never ingested here.
- About 37 more unreadable CVs with about 17 articles each account for the
  roughly 600 missing articles.
- With the fix `7cdfe65`, those curricula are downloaded again on the next
  run, and their data comes back once the portal serves them correctly.

A database that already held them (the normal persistent case) keeps their
data when the portal serves them badly, because the CV fails and nothing is
deleted.

## 5. Local validation

- Tests: `tests/test_raw_rotation.py`, `tests/test_raw_store.py`,
  `tests/test_lattes_rotation.py` and `tests/test_cnpq_rotation.py` are new.
  The incremental, export, schema and workflow tests were extended. Full
  suite: 673 passed, the same 6 failures as before these specs.
- Lattes, real cache of 435 listed curricula, fake downloader that copies
  the file: 109 refreshed per run; all dated after 4 runs.
- CNPq, a copy of the real database, with the recorded payloads behind the
  replay crawler:

| Run | Downloads | Documents | Time |
|---|---|---|---|
| 1 | new 347 | processed 338, skipped 12 | 241 s |
| 2 | refreshed 87, reused 260 | processed 0 | 19 s |
| 3 (every download failing, full refresh) | failed 347, reused after failure 347 | failed 0 | 18 s |

## 6. Why run 2 had fewer entities, and the two fixes

The "Nome-nao-identificado" curricula are the Lattes portal's reCAPTCHA
page, served instead of the curriculum when the portal limits access. The
page is about 18 KB and has no "Currículo do Sistema de Currículos Lattes
(<name>)" title, and scriptLattes builds a CV with no items from it. It hits
different curricula on every full download:

| Run | Unidentified CVs |
|---|---:|
| spec 022, 3 runs (cache restored between them) | 36 |
| spec 023 run 1 (fresh download, new branch) | 73 |
| spec 023 run 2 | 68 |
| spec 023 run 3 (first fix) | 53 |
| spec 023 run 4 (both fixes) | **12** |

- Only 6 of run 1's 73 were among spec 022's 36.
- 54 of the 57 CVs that owned the entities missing from run 2's export were
  unidentified in run 1.

The fixes:

- `7cdfe65`: a CV that turns out unidentified loses its download date, so the
  next rotation downloads it first.
- `ae87205`: the download checks the page title.
  - An access check page never replaces a cached curriculum, and is never
    cached for a new one.
  - Locally, 408 curricula were recognized and all 27 unidentified pages
    rejected.
  - The captcha is never answered or bypassed.

Export counts after each run:

| File | spec 022 | run 2 | run 3 | run 4 |
|---|---:|---:|---:|---:|
| `researchers_canonical.json` | 17,445 | 16,666 | 16,970 | **17,758** |
| `initiatives_canonical.json` | 12,535 | 11,598 | 12,002 | **12,879** |
| `articles_canonical.json` | 7,209 | 6,590 | 6,775 | **7,435** |

Run 4 ([40966298828](https://github.com/RafaelDeps/horizon_etl/actions/runs/40966298828))
went past spec 022 because it has fewer unreadable CVs (12 against 36).

- **Lattes:** it refreshed 86 curricula and rejected 23 access check
  pages, keeping the old copies.

## 7. Run 4: the CNPq portal was down

Run 4 took 3 h 40 min:

- **CNPq:** the phase timed out after its 3 h limit. Every page failed
  9 times (3 ETL attempts × 3 library attempts), and the adaptive gate cut
  the concurrency from 4 to 2. With 87 pages due, the phase was killed
  before its writer reached them, so nothing was written. The CNPq data in
  the database stayed as run 3 left it, intact.
- **The rest of the run:** it completed normally from the Lattes download
  on.

**Gap found.** A failed CNPq download falls back to the stored page only
when the fetch returns. When the portal hangs, the phase hits its time limit
first. A follow-up should stop fetching once failures cluster (the gate
already detects it), and process every group from its stored page. The same
idea applies to Lattes when the portal starts serving its access check page.
Neither is implemented.

## 8. Not done

- T030, the local weekly on the real database with the real portals, was not
  run; the two CI runs cover the same path.
- `fresh_database`, `refresh_share` and `full_refresh` were not dispatched on
  CI. The workflow tests and the local runs cover them.
