"""The export zip must ship results, never the raw documents they came from.

The SigPesq project documents live under data/exports/ for convenience, but they
are input: regenerable, and carrying coordinator names and e-mail addresses in
clear text. The zip is versioned, so sweeping them in put 130 real addresses into
git -- undoing the anonymisation the rest of the pipeline performs.
"""

import json
import os
import zipfile

from src.flows.exports.canonical_data import SKIP_DIRS, zip_exports_task


def test_zip_keeps_results_and_drops_source_documents(tmp_path):
    (tmp_path / "initiatives_canonical.json").write_text(
        json.dumps([{"id": 1, "enrichment": {"origin": "new_from_document"}}]),
        encoding="utf-8",
    )
    docs = tmp_path / "project_sigpesq_files_json"
    docs.mkdir()
    (docs / "PJ_1.json").write_text(
        json.dumps({"coordenador": {"email": "pessoa@ifes.edu.br"}}), encoding="utf-8"
    )

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        names = zf.namelist()
        blob = b"".join(zf.read(n) for n in names)

    assert "initiatives_canonical.json" in names, "the result must ship"
    assert not any("project_sigpesq_files_json" in n for n in names)
    assert b"pessoa@ifes.edu.br" not in blob, "no personal data may reach the zip"


def test_nested_result_files_still_ship(tmp_path):
    """Pruning must be surgical -- other subfolders keep being included."""
    reports = tmp_path / "docentes"
    reports.mkdir()
    (reports / "ranking.json").write_text("{}", encoding="utf-8")
    (tmp_path / "project_sigpesq_files_json").mkdir()

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        assert os.path.join("docentes", "ranking.json") in zf.namelist()


def test_skip_list_is_explicit():
    assert "project_sigpesq_files_json" in SKIP_DIRS
