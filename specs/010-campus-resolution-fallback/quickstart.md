# Quickstart: Campus Resolution — SigPesq Execution Campus + Advisorship Fallback

**Feature**: `010-campus-resolution-fallback`

How to run this feature's changes and prove they worked. Every command uses the
Makefile targets, which are the canonical entry points.

## 0. Record the baseline before changing anything

```bash
.venv/bin/python -c "import json;d=json.load(open('data/exports/researchers_canonical.json'));r=d if isinstance(d,list) else d.get('data',d);n=len(r);z=sum(1 for x in r if not x.get('campus'));print(n,z,f'{z/n:.1%}')"
```

Expected on the current export: `9626 3018 31.4%`. Keep this number — SC-001 and
SC-004 are both measured against it.

## 1. Run the quality gate

```bash
make ci-check
```

Must pass before and after the change (flake8, black, isort, mypy, pytest).

## 2. Verify Phase A — the supervisor fallback

The fallback needs no re-ingestion, so it can be verified against the database
as it stands:

```bash
make export-canonical
```

Then re-run the baseline command from step 0. Expected: the null share drops
from 31.4% to roughly 11–12%, i.e. about 1,900 more people carry a campus, and
**no** person who had a campus before has lost one.

## 3. Verify Phase B — the execution campus

This one does need the SigPesq reports to be re-read. They are already in
`data/raw/sigpesq/`:

```bash
make ingest-sigpesq
```

Then confirm the assertions were written:

```bash
.venv/bin/python -c "import sqlite3;c=sqlite3.connect('db/horizon.db');print(c.execute(\"select attribute_name, count(*) from attribute_assertions where attribute_name like 'execution_campus%' group by 1\").fetchall())"
```

Expected: one `execution_campus_id` and one `execution_campus_name` row per
ingested SigPesq project and advisorship that stated a campus.

Confirm no campus was duplicated by a dirty name (SC-006):

```bash
.venv/bin/python -c "import sqlite3;c=sqlite3.connect('db/horizon.db');print(c.execute('select count(*) from organizational_units').fetchone()[0])"
```

Expected: still 23, unless a genuinely new campus appeared in the sources.

## 4. Verify Phase C — coverage audit and determinism

```bash
.venv/bin/python -m src.scripts.audit_campus_coverage
```

Reports the null-campus share, the split between directly-evidenced and
supervisor-inferred attributions, and any person whose campus changed relative
to the previous export.

Determinism (SC-005): export twice into different directories and diff.

```bash
make export-canonical OUTPUT_DIR=/tmp/campus-run-a
make export-canonical OUTPUT_DIR=/tmp/campus-run-b
diff /tmp/campus-run-a/researchers_canonical.json /tmp/campus-run-b/researchers_canonical.json && echo "deterministic"
```

## 5. Visual check in the dashboard

The campus-scoped export path must still work:

```bash
make export-canonical CAMPUS=Serra
```

The dashboard consumes the Parquet files from `data/exports/parquet/`, not the
canonical JSON. Back up the destination before replacing anything there.

## Rollback

Both changes are read-path or additive-write:

- Phase A lives entirely in the resolver; reverting the commit restores the old
  attribution on the next export.
- Phase B only *adds* rows to `attribute_assertions`. Reverting the code makes
  the resolver ignore them; the rows are harmless audit history and need no
  cleanup. No schema change means no migration to undo.

---

## Baseline

Measured on 2026-09-03, before any code change, against `db/horizon.db` and the
canonical export then in `data/exports/`:

| Metric | Value |
|--------|-------|
| Researchers exported | 9,626 |
| Exported with `campus: null` | 3,018 |
| Null share | **31.4%** |
| People covered by research-group evidence | 6,608 |
| People reachable by the supervisor fallback | 1,936 |
| Campuses (`organizational_units`) | 23 |
| SigPesq advisorships / projects stating a campus | 587 / 102 |

These are the reference values for SC-001 (null share ≤ 12%), SC-002 (≥ 1,900
newly attributed), SC-004 (no one loses a campus), and SC-006 (campus count
unchanged).

### Achieved

Measured on 2026-09-03 with the implementation in place, via
`python -m src.scripts.audit_campus_coverage --previous data/exports/researchers_canonical.json`:

| Metric | Before | After | Criterion |
|--------|--------|-------|-----------|
| People with no campus | 3,198 (32.6%) | **1,262 (12.9%)** | SC-001 |
| Attributed by direct evidence | 6,608 | 6,608 | — |
| Attributed by supervisor inference | 0 | **1,936** | SC-002 ✅ |
| People who lost a campus | — | **0** | SC-004 ✅ |
| Campuses in `organizational_units` | 23 | 23 | SC-006 ✅ |

The share is quoted over all 9,806 persons in the database; over the 9,626 rows
actually written to `researchers_canonical.json` the before-figure is the 31.4%
in the table above. Either way the reduction is the same 1,936 people.

**Still to verify by the operator**: SC-003 and the SC-001 contribution of the
execution campus require `make ingest-sigpesq`, which rewrites `db/horizon.db`
from the reports in `data/raw/`. That was deliberately not run here — it is a
stateful operation on the canonical database. The ingestion-side behaviour is
covered by unit tests (`tests/test_project_loader_campus.py`,
`tests/test_sigpesq_campus_strategy.py`) and the export-side consumption of the
resulting assertions by `tests/test_export_campus_resolver.py`, but the
end-to-end number will only be known after a real ingestion.


---

## Full pipeline run — 2026-09-03 15:41

`make weekly-flows` (db-reset + full reingestion, Serra-scoped) with the feature
in place.

| Check | Result | Criterion |
|-------|--------|-----------|
| Researchers exported / without campus | 9,630 / 1,023 = **10.6%** | SC-001 (target 12%) |
| Source rows that produced an entity and carry the campus | 85/85 projects, 721/721 advisorships = **100%** | SC-003 |
| People who lost a campus | **0** | SC-004 |
| Campuses in `organizational_units` | **23**, no dirty-name duplicate | SC-006 |
| Attribution split | 6,987 direct / 1,620 supervisor-inferred / 1,203 none | — |

Two observations from that run, neither a defect of this feature:

- 17 of the 102 SigPesq project rows produced no initiative at all (no
  `entity_match`), so they carry no campus either. Every row that *did* produce
  an entity got its campus. The missing initiatives are a pre-existing ingestion
  behaviour worth investigating separately.
- With equal weights, 52 people moved to a campus other than the one their
  research group implied, all toward Serra — an artefact of the Serra-scoped
  ingestion. Research-group membership was consequently given weight 3
  (research.md R8), bringing the moves down to 33: 32 by clear dominance and one
  remaining tie. Coverage is unchanged by the weighting.

**Re-export needed**: the artifacts in `data/exports/` were written before the
weighting change, so 19 people still carry the pre-R8 campus there. Coverage
figures are unaffected. Re-run `make export-canonical` to bring the artifacts in
line.
