# Quickstart: Curated Export Archive

**Branch**: `013-curate-export-zip` | **Date**: 2026-09-18

Runbook to implement, test, and manually verify the feature. All commands run
from the repository root.

## 0. Preconditions

```sh
git branch --show-current        # expect: 013-curate-export-zip
test -d .venv || make setup      # venv with requirements installed
```

Known pre-existing suite failures (recorded in specs/009 T001 — e.g.
`test_export_canonical_data_flow.py` tracking test, `test_sigpesq_adapter.py`
429, `test_download_lattes_flow.py`) are NOT to be fixed here; compare against
this baseline.

## 1. Fast, targeted verification (implementers loop)

```sh
.venv/bin/python -m pytest tests/test_zip_excludes_source_documents.py -q
.venv/bin/python -m pytest tests/test_project_files_zip_reuse.py -q
.venv/bin/python -m pytest tests/test_export_canonical_data_flow.py -q
```

All must pass. R1–R15 in `contracts/export_zip_rules.md` map 1:1 to these
files.

## 2. Full gate

```sh
make test                 # full suite
make format-check && make lint
```

## 3. Manual zip verification (no Prefect server needed)

Build a representative exports dir and run the task directly:

```sh
.venv/bin/python - <<'PY'
import json, os, tempfile, zipfile
from src.flows.exports.canonical_data import zip_exports_task

tmp = tempfile.mkdtemp()
open(os.path.join(tmp, "initiatives_canonical.json"), "w").write("[]")
os.makedirs(os.path.join(tmp, "project_sigpesq_files_json"))
open(os.path.join(tmp, "project_sigpesq_files_json", "PJ_9760.json"), "w").write(
    json.dumps({"coordenador": {"email": "pessoa@ifes.edu.br",
                                "nome": "Coordenador"},
                "_meta": {"arquivo": "PJ_9760.pdf"}})
)
open(os.path.join(tmp, "data_snapshot.zip"), "wb").write(b"stale")
os.makedirs(os.path.join(tmp, "formandos")); open(os.path.join(tmp, "formandos", "x.html"), "w").write("<html>")

zip_exports_task.fn(tmp)

zf = zipfile.ZipFile(os.path.join(tmp, "exports_canonical.zip"))
print(zf.namelist())
blob = b"".join(zf.read(n) for n in zf.namelist())
assert b"pessoa@ifes.edu.br" not in blob
assert b"@anon.lgpd" in blob
assert b"data_snapshot" not in blob and b"formandos" not in blob
print("OK — R1, R2, R5, R6 verified")
PY
```

Expected member list: `initiatives_canonical.json` and
`project_sigpesq_files_json/PJ_9760.json` only.

## 4. Manual reuse smoke (needs SIGPESQ credentials + MISTRAL_KEY only for
the fallback path; the reuse path itself makes no API calls)

```sh
# 1) restore last week's artifact so the export folder has an archive with
#    project_sigpesq_files_json/ inside it
# 2) remove a couple of local JSONs to make those PDFs "pending"
rm data/exports/project_sigpesq_files_json/PJ_9760.json

# 3) run only the extraction phase
make extract-project-files PROJECT_FILES_LIMIT=5

# in the log, expect for each archived stem:
#   "reused from archive" (or the reused counter > 0 in "Extraction finished")
# and NO Mistral call for that stem (stats["reused"] accounts for it)
```

`PROJECT_FILES_LIMIT` caps how many PDFs are considered — keep it small for a
cheap smoke. To prove the paid path still works, delete the archive entry or
use a stem absent from the archive and watch the extractor run.

## 5. Post-implementation checklist

- [x] ADR-003 amended (parquet no longer emitted by the flow; script manual).
- [x] `docs/outputs-and-artifacts.md` notes the archive now carries the
      scrubbed corpus.
- [x] `SKIP_DIRS` = {project_sigpesq_files_json, formandos, docentes,
      mestrado, parquet}; any `*.zip` skipped by name.
- [x] `export_parquet_task` gone from `canonical_data.py`; script untouched.
- [x] Extraction stats include `reused`.
