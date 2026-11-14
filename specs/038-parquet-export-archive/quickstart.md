# Quickstart: Parquet export archive

**Feature**: 038-parquet-export-archive | **Date**: 2026-11-14

Local validation, after the implementation. The weekly runs are started only
with the maintainer's go-ahead, and only after a restorable backup of
`db/horizon.db` and `data/`.

## 1. Tests

```bash
.venv/bin/python -m pytest tests/test_parquet_layout.py tests/test_parquet_archive.py tests/test_export_parquet.py tests/test_weekly_orchestrator.py tests/test_app_zip_exports.py tests/test_zip_excludes_source_documents.py tests/test_weekly_etl_workflow.py -q
```

```bash
.venv/bin/python -m pytest -q
```

## 2. Build from the current JSON archive (no weekly run)

```bash
make parquet-archive
```

Expected: `data/exports/exports_parquet.zip` exists and
`data/reports/parquet_archive_report.json` says `"status": "built"`.

## 3. Sizes and members

```bash
.venv/bin/python - <<'EOF'
import zipfile
z = zipfile.ZipFile("data/exports/exports_parquet.zip")
infos = z.infolist()
big = max(infos, key=lambda i: i.file_size)
print(len(infos), "members;", sum(i.compress_size for i in infos), "bytes stored")
print("largest:", big.filename, big.file_size)
print("dates:", {i.date_time for i in infos})
print("attribute_assertions:", "attribute_assertions_canonical.parquet" in z.namelist())
EOF
```

Expected: archive under 100 MB (about 51 MB), largest member under 100 MB
(about 8 MB), one date `(1980, 1, 1, 0, 0, 0)`, attribute assertions present.

## 4. Every table reads back equal to the JSON archive

```bash
.venv/bin/python - <<'EOF'
import io, json, zipfile
from src.core.logic.parquet_layout import equal_to_json, read_member_back
j = zipfile.ZipFile("data/exports/exports_canonical.zip")
p = zipfile.ZipFile("data/exports/exports_parquet.zip")
names = sorted(n for n in j.namelist() if "/" not in n and n != "export_manifest.json")
bad = [n for n in names if not equal_to_json(read_member_back(p, n), json.loads(j.read(n)))]
print(len(names), "members compared;", len(bad), "different:", bad)
EOF
```

Expected: 48 members compared (on 2026-11-14), 0 different (equality as in
the data model: missing key = null, integers as integers).

## 5. No value the safety net would replace

```bash
.venv/bin/python - <<'EOF'
import json, zipfile
from src.core.logic.parquet_layout import read_member_back
from src.core.logic.pii_anonymizer import scan_text
j = zipfile.ZipFile("data/exports/exports_canonical.zip")
p = zipfile.ZipFile("data/exports/exports_parquet.zip")
names = sorted(n for n in j.namelist() if "/" not in n and n != "export_manifest.json")
hits = {}
for n in names:
    _, counts = scan_text(json.dumps(read_member_back(p, n), ensure_ascii=False))
    if any(counts.values()):
        hits[n] = counts
print("members with matches:", hits)
EOF
```

Expected: `{}`. Only counts are printed.

## 6. Same JSON archive, same bytes

```bash
sha256sum data/exports/exports_parquet.zip && make parquet-archive && sha256sum data/exports/exports_parquet.zip
```

Expected: the two hashes are equal.

## 7. Gate

```bash
.venv/bin/python -m src.scripts.check_publishable_archive data/exports/exports_parquet.zip --ref HEAD
```

Expected locally: refused with "the archive was not built by the official
workflow" (a local build has `official: false`), exactly as the JSON archive
of the same run.

## 8. Weekly runs (maintainer's go-ahead)

Two local weekly runs, as in the earlier specs:

```bash
make weekly-flows
```

After each: the phase `parquet_archive` passed; steps 3 to 5 hold; the report's
`json_archive_sha256` equals `sha256sum data/exports/exports_canonical.zip`;
the member list of `exports_canonical.zip` equals the one before the change
(SC-005); the phase took about one minute (SC-006).

## 9. Failure keeps the previous archive (optional, manual)

Make the JSON archive unreadable for a moment (copy it aside, write a
non-zip file in its place), run `make parquet-archive`, check the report says
`"failed"`, the log has the "earlier run" warning and `exports_parquet.zip`
has the same hash as before; then put the JSON archive back.

## 10. Stale folder

`data/exports/parquet/` (2026-09-17) is not read or written by any step; it
can be removed by hand.
