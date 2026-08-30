# Quickstart: Advisorship Canonical Values (009)

Runnable validations that prove the feature end-to-end. Implementation details live in
`tasks.md`; field semantics in `contracts/advisorships-canonical.md` and
`data-model.md`.

## Prerequisites

- `.venv` present (`make setup`), local DB seeded at `db/horizon.db` (3,199
  advisorship rows, 701 sigpesq + 3,107 lattes advisorship source records).
- Prefect does not need to be running for the dev-exploration commands; they bypass
  the flow context (see constitution: direct python is allowed for exploration, flows
  remain the production path).

## 1. Unit suite (fast gate)

```bash
.venv/bin/python -m pytest tests/test_canonical_exporter.py tests/test_initiative_handlers.py tests/test_mappers.py -q
```

Expected: pass — incl. new cases: SigPesq row → advisorship exports `program`/`provider`
matching report `Programa`/`AgFinanciadora`; `year` = report/directory year; Id-4882-style
cross-directory duplicate resolves to `Ano` (2021); Lattes-sourced row exports nullable
program/provider; strategy return carries `program`; handler persists `initiative.program`.

Full gate when feasible: `make ci-check`.

## 2. Ad hoc export (dev exploration)

```bash
make export-canonical            # production path (Prefect flow)
# or, exploration (no Prefect needed):
PYTHONPATH=. .venv/bin/python - <<'PY'
import json, tempfile
from src.core.logic.canonical_exporter import CanonicalDataExporter
from src.infrastructure.exporters.database import DatabaseExporter
ex = CanonicalDataExporter(DatabaseExporter())
out = tempfile.mkdtemp() + "/advisorships_canonical.json"
ex.export_advisorships(out)
d = json.load(open(out))
advs = [a for p in d for a in p["advisorships"]]
sig = len([a for a in advs if a["program"] is not None])
print("total:", len(advs), "| with program:", sig)
print("sample:", next(a for a in advs if a["program"]))
PY
```

Expected: `total: 3199`; `with program:` > 0 and consistent with the number of
SigPesq-derived advisorship entities minus empty `Programa` rows; sample advisorship
shows report-spelled `program` + `provider` + report `year`.

## 3. Parity & correctness (FR-004 / SC-001..SC-003)

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
import json, re, sqlite3
d = json.load(open("data/exports/advisorships_canonical.json"))
advs = {a["id"] for p in d for a in p["advisorships"]}
db = sqlite3.connect("db/horizon.db")
ids = {r[0] for r in db.execute("select id from advisorships")}
print("missing from export:", sorted(ids - advs))
sig = db.execute("""select count(*) from source_records sr
  join entity_matches em on em.source_record_id = sr.id
  where sr.source_system='sigpesq_advisorships'
    and em.canonical_entity_type='advisorship'""").fetchone()[0]
print("sigpesq-linked advisorship source records:", sig)
for r in db.execute("select raw_payload_json from source_records where source_system='sigpesq_advisorships' limit 5"):
    print(list(json.loads(r[0]).keys()))
PY
```

Expected: `missing from export:` empty; keys shown include `Programa`, `AgFinanciadora`, `Ano` (no PII keys surfaced).

## 4. Year disambiguation (Q2=A)

Verify the observed duplicate case: advisorship from `Id 4882` present under both
`advisorships/2021/` and `advisorships/2022/` with payload `Ano=2021` exports
`year: 2021`.

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
import json
d = json.load(open("data/exports/advisorships_canonical.json"))
cands = [a for p in d for a in p["advisorships"] if a["id"] == 4882]
print(cands)
PY
```

Expected: `year` equals 2021 (payload `Ano`), the directory-year tie-break rule.

## 5. Ingestion persistence (FR-007)

> **NOTE**: Requires a working Prefect server (`make prefect-server`). In dev envs where
> Prefect is unavailable, mark this scenario SKIPPED and run it after a deploy-env
> re-ingestion; export-side correctness is already covered by §2/§3.

After a SigPesq advisorship re-ingestion (e.g. `make ingest-sigpesq` for a fresh
report year):

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
import sqlite3
db = sqlite3.connect("db/horizon.db")
for r in db.execute("select id, program from advisorships where program is not null limit 5"):
    print(r)
print("program non-null:", db.execute("select count(*) from advisorships where program is not null").fetchone()[0])
PY
```

Expected: fresh advisorship rows carry `program` (report `Programa`); existing rows may
be null until the export resolves them from source records (that is by design).

## 6. LGPD (FR-006)

Re-run the PII scan against the produced artifact and assert no raw patterns:

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
import json, re
d = json.dumps(json.load(open("data/exports/advisorships_canonical.json")))
assert not re.search(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", d), "raw email leaked"
assert not re.search(r"(?<!\d)\d{10,11}(?!\d)", d), "raw phone leaked"
assert not re.search(r"\d{11}", d.replace("1","").replace("0","")), "possible CPF window"
print("LGPD clean")
PY
```

Expected: `LGPD clean`.