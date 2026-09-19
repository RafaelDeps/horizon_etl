"""The export zip ships the SigPesq project documents -- scrubbed.

The ``PJ_*.json`` corpus is input to the enrichment phase and carries
coordinator e-mail addresses in clear text, so the raw folder must never
enter the zip unscrubbed. Instead, ``zip_exports_task`` writes anonymized
copies into the archive (R1-R3), skips malformed files individually (R9),
and keeps every other result shipping (R7).
"""

import json
import os
import zipfile

from src.flows.exports.canonical_data import SKIP_DIRS, zip_exports_task


def _make_pj(tmp_path, name="PJ_1.json", payload=None):
    docs = tmp_path / "project_sigpesq_files_json"
    docs.mkdir(exist_ok=True)
    if payload is None:
        payload = {
            "titulo": "Projeto Teste",
            "coordenador": {"nome": "João Silva", "email": "pessoa@ifes.edu.br"},
            "_meta": {"arquivo": "PJ_1.pdf"},
        }
    (docs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_zip_includes_scrubbed_pj_corpus(tmp_path):
    (tmp_path / "initiatives_canonical.json").write_text(
        json.dumps([{"id": 1, "enrichment": {"origin": "new_from_document"}}]),
        encoding="utf-8",
    )
    _make_pj(tmp_path)

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        names = zf.namelist()
        blob = b"".join(zf.read(n) for n in names)
        scrubbed = json.loads(zf.read("project_sigpesq_files_json/PJ_1.json"))

    assert "initiatives_canonical.json" in names, "the result must ship"
    assert "project_sigpesq_files_json/PJ_1.json" in names, "scrubbed PJ must ship"
    assert b"pessoa@ifes.edu.br" not in blob, "raw e-mail must not reach the zip"
    assert scrubbed["coordenador"]["email"].endswith("@anon.lgpd")
    assert (
        scrubbed["coordenador"]["nome"] == "João Silva"
    ), "names ship (catalogue policy)"
    assert scrubbed["_meta"]["arquivo"] == "PJ_1.pdf", "provenance is preserved"


def test_scrub_is_idempotent(tmp_path):
    anon = {"coordenador": {"nome": "João Silva", "email": "3fa85f64c0de@anon.lgpd"}}
    _make_pj(tmp_path, name="PJ_2.json", payload=anon)

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        scrubbed = json.loads(zf.read("project_sigpesq_files_json/PJ_2.json"))
    assert scrubbed["coordenador"]["email"] == "3fa85f64c0de@anon.lgpd"


def test_malformed_pj_is_skipped_without_sinking_the_zip(tmp_path):
    (tmp_path / "initiatives_canonical.json").write_text("[]", encoding="utf-8")
    docs = tmp_path / "project_sigpesq_files_json"
    docs.mkdir()
    (docs / "PJ_bad.json").write_text("{not json", encoding="utf-8")
    _make_pj(tmp_path, name="PJ_good.json")

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        names = zf.namelist()
    assert "project_sigpesq_files_json/PJ_good.json" in names
    assert "project_sigpesq_files_json/PJ_bad.json" not in names


def test_zip_without_pj_corpus_still_works(tmp_path):
    (tmp_path / "initiatives_canonical.json").write_text("[]", encoding="utf-8")

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        assert "initiatives_canonical.json" in zf.namelist()


def test_nested_result_files_still_ship(tmp_path):
    """Pruning must be surgical -- non-excluded subfolders keep shipping."""
    marts = tmp_path / "marts"
    marts.mkdir()
    (marts / "ranking.json").write_text("{}", encoding="utf-8")
    (tmp_path / "project_sigpesq_files_json").mkdir()

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        assert os.path.join("marts", "ranking.json") in zf.namelist()


def test_zip_excludes_nested_archives(tmp_path):
    (tmp_path / "data_snapshot.zip").write_bytes(b"stale snapshot")
    (tmp_path / "other.zip").write_bytes(b"any nested archive")
    (tmp_path / "initiatives_canonical.json").write_text("[]", encoding="utf-8")

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        names = zf.namelist()
    assert "data_snapshot.zip" not in names
    assert "other.zip" not in names
    assert "initiatives_canonical.json" in names


def test_zip_excludes_report_and_format_dirs(tmp_path):
    for folder, fname in (
        ("formandos", "formandos.html"),
        ("docentes", "ranking.json"),
        ("mestrado", "base.html"),
        ("parquet", "table.parquet"),
    ):
        d = tmp_path / folder
        d.mkdir()
        (d / fname).write_text("x", encoding="utf-8")

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        names = zf.namelist()
    assert not any(
        n.startswith(("formandos/", "docentes/", "mestrado/", "parquet/"))
        for n in names
    )


def test_absent_categories_are_noop(tmp_path):
    (tmp_path / "initiatives_canonical.json").write_text("[]", encoding="utf-8")

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        assert zf.namelist() == ["initiatives_canonical.json"]


def test_skip_list_is_explicit():
    assert SKIP_DIRS == {
        "project_sigpesq_files_json",
        "formandos",
        "docentes",
        "mestrado",
        "parquet",
    }


def test_zip_excludes_unzipped_exports_canonical_folders(tmp_path):
    (tmp_path / "initiatives_canonical.json").write_text("[]", encoding="utf-8")
    unzipped_dir = tmp_path / "exports_canonical"
    unzipped_dir.mkdir()
    (unzipped_dir / "initiatives_canonical.json").write_text("[]", encoding="utf-8")
    unzipped_dir_2 = tmp_path / "exports_canonical (2)"
    unzipped_dir_2.mkdir()
    (unzipped_dir_2 / "initiatives_canonical.json").write_text("[]", encoding="utf-8")

    zip_exports_task.fn(str(tmp_path))

    with zipfile.ZipFile(tmp_path / "exports_canonical.zip") as zf:
        names = zf.namelist()
    assert "initiatives_canonical.json" in names
    assert not any(
        n.startswith(("exports_canonical/", "exports_canonical (2)/")) for n in names
    )
