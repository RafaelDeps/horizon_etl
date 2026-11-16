"""Spec 038: exports_parquet.zip, built from the JSON archive of the same run."""

import hashlib
import json
import zipfile

import pytest

import src.flows.exports.parquet_archive as parquet_archive
from src.core.logic.parquet_layout import equal_to_json, read_member_back
from src.flows.exports.parquet_archive import build_parquet_archive

MANIFEST = json.dumps({"key_fingerprint": "abc", "official": True}).encode()

EXPORTS = {
    "assertions_canonical.json": [
        {"id": 1, "value_json": "texto"},
        {"id": 2, "value_json": 42},
        {"id": 3, "value_json": [1, 2]},
        {"id": 4, "value_json": {"k": "v"}, "extra": True},
    ],
    "empty_canonical.json": [],
    "people_graph.json": {
        "metadata": {"name": "g"},
        "graph_stats": {"nodes": 1},
        "graph": {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [{"id": "a"}],
            "edges": [],
        },
    },
    "horizon_ids_canonical.json": {
        "rule_version": 6,
        "generated_at": "t",
        "ids": [{"id": 1, "horizon_id": "person:lattes:1"}],
    },
    "mart.json": {"a": {"b": [1, 2]}},
}


def _json_archive(folder, exports=EXPORTS, manifest=MANIFEST):
    path = folder / "exports_canonical.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, value in exports.items():
            zf.writestr(name, json.dumps(value, ensure_ascii=False, indent=2))
        zf.writestr("research_group_relationship_graphs/g_1.json", "{}")
        if manifest is not None:
            zf.writestr("export_manifest.json", manifest)
    return path


@pytest.fixture
def folder(tmp_path):
    _json_archive(tmp_path)
    return tmp_path


@pytest.fixture
def report(tmp_path):
    return tmp_path / "reports" / "parquet_archive_report.json"


def _build(folder, report):
    return build_parquet_archive(str(folder), report_path=str(report))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_archive_holds_the_layout_of_every_top_level_member(folder, report):
    _build(folder, report)

    with zipfile.ZipFile(folder / "exports_parquet.zip") as zf:
        names = zf.namelist()
    assert names == sorted(names[:-1]) + ["export_manifest.json"]
    assert "assertions_canonical.parquet" in names
    assert "assertions_canonical.cols.json" in names
    assert "empty_canonical.parquet" in names
    assert "people_graph.nodes.parquet" in names
    assert "people_graph.edges.parquet" in names
    assert "people_graph.meta.json" in names
    assert "horizon_ids_canonical.meta.json" in names
    assert "mart.json" in names
    assert not any(n.startswith("research_group_relationship_graphs") for n in names)


def test_every_member_reads_back_equal(folder, report):
    _build(folder, report)

    with (
        zipfile.ZipFile(folder / "exports_canonical.zip") as j,
        zipfile.ZipFile(folder / "exports_parquet.zip") as p,
    ):
        for name in EXPORTS:
            assert equal_to_json(read_member_back(p, name), json.loads(j.read(name)))


def test_the_json_archive_is_untouched(folder, report):
    before = _sha(folder / "exports_canonical.zip")
    _build(folder, report)
    assert _sha(folder / "exports_canonical.zip") == before


def test_the_report_says_what_was_built(folder, report):
    result = _build(folder, report)

    written = json.loads(report.read_text())
    assert written == result
    assert written["status"] == "built"
    assert written["reason"] is None
    assert written["failed_member"] is None
    assert written["json_archive_sha256"] == _sha(folder / "exports_canonical.zip")
    with zipfile.ZipFile(folder / "exports_parquet.zip") as zf:
        infos = zf.infolist()
    assert written["members"] == len(infos)
    assert written["archive_bytes"] == (folder / "exports_parquet.zip").stat().st_size
    largest = max(infos, key=lambda i: i.file_size)
    assert written["largest_member"] == largest.filename
    assert written["largest_member_bytes"] == largest.file_size
    assert written["seconds"] >= 0


def test_the_flow_runs_the_build(folder, report, monkeypatch):
    monkeypatch.setattr(parquet_archive, "REPORT_PATH", str(report))
    parquet_archive.parquet_archive_flow.fn(output_dir=str(folder))
    assert (folder / "exports_parquet.zip").exists()


# --- US2: as safe as the JSON archive ---------------------------------------

FAKE_EMAIL = "person@example.test"
FAKE_PHONE = "+55 00 00000-0000"


@pytest.fixture
def scanned(tmp_path, monkeypatch):
    """A JSON archive built by the real zip task (safety net included)."""
    import src.flows.exports.canonical_data as canonical_data

    monkeypatch.setattr(
        canonical_data, "SCAN_REPORT_PATH", str(tmp_path / "scan_report.json")
    )
    folder = tmp_path / "exports"
    folder.mkdir()
    rows = [
        {"id": 1, "note": f"contato {FAKE_EMAIL}", "phones": [FAKE_PHONE]},
        {"id": 2, "note": "nada", "phones": []},
    ]
    (folder / "people_canonical.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    canonical_data.zip_exports_task.fn(str(folder))
    return folder


def test_values_are_the_ones_after_the_safety_net(scanned, report):
    from src.core.logic.pii_anonymizer import scan_text

    _build(scanned, report)

    with (
        zipfile.ZipFile(scanned / "exports_canonical.zip") as j,
        zipfile.ZipFile(scanned / "exports_parquet.zip") as p,
    ):
        published = json.loads(j.read("people_canonical.json"))
        rebuilt = read_member_back(p, "people_canonical.json")
    assert equal_to_json(rebuilt, published)
    text = json.dumps(rebuilt, ensure_ascii=False)
    assert FAKE_EMAIL not in text and FAKE_PHONE not in text
    _, counts = scan_text(text)
    assert not any(counts.values())


def test_the_manifest_is_the_json_archives(scanned, report):
    _build(scanned, report)

    with (
        zipfile.ZipFile(scanned / "exports_canonical.zip") as j,
        zipfile.ZipFile(scanned / "exports_parquet.zip") as p,
    ):
        assert p.read("export_manifest.json") == j.read("export_manifest.json")


def test_a_json_archive_without_manifest_stops_the_build(tmp_path, report):
    _json_archive(tmp_path, manifest=None)

    result = _build(tmp_path, report)

    assert result["status"] == "failed"
    assert "export_manifest.json" in result["reason"]
    assert not (tmp_path / "exports_parquet.zip").exists()


# --- US3: a failed or repeated build changes nothing -------------------------


def _capture():
    from loguru import logger

    messages = []
    return messages, logger.add(lambda m: messages.append(str(m)))


def test_the_same_json_archive_gives_the_same_bytes(folder, report):
    _build(folder, report)
    first = (folder / "exports_parquet.zip").read_bytes()
    _build(folder, report)
    assert (folder / "exports_parquet.zip").read_bytes() == first
    with zipfile.ZipFile(folder / "exports_parquet.zip") as zf:
        assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def _assert_failed_and_kept(folder, report, result, messages, previous):
    from loguru import logger  # noqa: F401

    assert result["status"] == "failed"
    assert result["reason"]
    assert json.loads(report.read_text())["status"] == "failed"
    assert not (folder / "exports_parquet.zip.tmp").exists()
    if previous is None:
        assert not (folder / "exports_parquet.zip").exists()
    else:
        assert (folder / "exports_parquet.zip").read_bytes() == previous
    assert any(parquet_archive.EARLIER_RUN_WARNING in m for m in messages)


def test_a_member_that_cannot_be_converted_keeps_the_previous_archive(
    folder, report, monkeypatch
):
    from loguru import logger

    from src.core.logic.parquet_layout import ParquetLayoutError

    _build(folder, report)
    previous = (folder / "exports_parquet.zip").read_bytes()
    json_before = _sha(folder / "exports_canonical.zip")
    real = parquet_archive.layout_members

    def broken(name, raw):
        if name == "empty_canonical.json":
            raise ParquetLayoutError(f"{name}: cannot write")
        return real(name, raw)

    monkeypatch.setattr(parquet_archive, "layout_members", broken)
    messages, sink = _capture()
    try:
        result = _build(folder, report)
    finally:
        logger.remove(sink)

    _assert_failed_and_kept(folder, report, result, messages, previous)
    assert result["failed_member"] == "empty_canonical.json"
    assert _sha(folder / "exports_canonical.zip") == json_before


@pytest.mark.parametrize("limit", [400, 2500])
def test_over_the_limit_keeps_the_previous_archive(folder, report, monkeypatch, limit):
    # 400: a Parquet member is larger; 2500: every member fits but the archive
    # does not.
    from loguru import logger

    _build(folder, report)
    previous = (folder / "exports_parquet.zip").read_bytes()
    monkeypatch.setattr(parquet_archive, "MAX_ARCHIVE_BYTES", limit)
    messages, sink = _capture()
    try:
        result = _build(folder, report)
    finally:
        logger.remove(sink)

    _assert_failed_and_kept(folder, report, result, messages, previous)
    assert "limit" in result["reason"]


def test_a_failure_with_no_previous_archive_leaves_none(folder, report, monkeypatch):
    from loguru import logger

    monkeypatch.setattr(parquet_archive, "MAX_ARCHIVE_BYTES", 400)
    messages, sink = _capture()
    try:
        result = _build(folder, report)
    finally:
        logger.remove(sink)

    _assert_failed_and_kept(folder, report, result, messages, None)


def test_the_flow_fails_when_the_build_fails(folder, report, monkeypatch):
    monkeypatch.setattr(parquet_archive, "REPORT_PATH", str(report))
    monkeypatch.setattr(parquet_archive, "MAX_ARCHIVE_BYTES", 400)
    with pytest.raises(parquet_archive.ParquetArchiveError):
        parquet_archive.parquet_archive_flow.fn(output_dir=str(folder))
