"""Spec 029: the archive build scans every member and replaces any match."""

import json
import os
import zipfile

import pytest
from loguru import logger

import src.flows.exports.canonical_data as canonical_data
from src.flows.exports.canonical_data import zip_exports_task

FAKE_EMAIL = "person@example.test"
FAKE_PHONE = "+55 00 00000-0000"
FAKE_CPF = "000.000.000-00"
PLAIN_VALUES = (FAKE_EMAIL, FAKE_PHONE, FAKE_CPF)


@pytest.fixture(autouse=True)
def report_path(tmp_path, monkeypatch):
    path = tmp_path / "reports" / "export_scan_report.json"
    monkeypatch.setattr(canonical_data, "SCAN_REPORT_PATH", str(path))
    return path


@pytest.fixture
def exports(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()
    return folder


def _build(folder):
    zip_exports_task.fn(str(folder))
    return folder / "exports_canonical.zip"


def _members(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _report(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _capture_logs():
    messages = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="DEBUG")
    return messages, sink_id


def test_match_is_replaced_and_run_does_not_raise(exports):
    payload = {"note": f"{FAKE_EMAIL} {FAKE_PHONE} {FAKE_CPF}"}
    (exports / "a.json").write_text(json.dumps(payload), encoding="utf-8")

    members = _members(_build(exports))

    text = members["a.json"].decode("utf-8")
    for value in PLAIN_VALUES:
        assert value not in text
    assert "@anon.lgpd" in text


def test_logs_and_report_hold_counts_not_values(exports, report_path):
    (exports / "a.json").write_text(
        json.dumps({"note": f"{FAKE_EMAIL} {FAKE_PHONE} {FAKE_CPF}"}),
        encoding="utf-8",
    )
    messages, sink_id = _capture_logs()
    try:
        _build(exports)
    finally:
        logger.remove(sink_id)

    report = _report(report_path)
    assert report["matches"]["a.json"] == {
        "email": 1,
        "phone": 1,
        "cpf": 1,
        "known_field": 0,
    }
    assert report["files_scanned"] == 1
    assert "seconds" in report
    assert report["left_out"] == []
    blob = json.dumps(report) + "\n".join(messages)
    assert "a.json" in blob
    for value in PLAIN_VALUES:
        assert value not in blob


def test_clean_member_is_written_as_is_with_file_date(exports):
    path = exports / "clean.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    os.utime(path, (1_700_000_000, 1_700_000_000))

    zip_path = _build(exports)

    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo("clean.json")
        expected = zipfile.ZipInfo.from_file(path).date_time
        assert info.date_time == expected
        assert zf.read("clean.json") == path.read_bytes()


def test_changed_member_keeps_json_valid_and_file_date(exports):
    path = exports / "a.json"
    path.write_text(json.dumps({"note": FAKE_EMAIL}), encoding="utf-8")
    os.utime(path, (1_700_000_000, 1_700_000_000))

    zip_path = _build(exports)

    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo("a.json")
        assert info.date_time == zipfile.ZipInfo.from_file(path).date_time
        assert info.compress_type == zipfile.ZIP_DEFLATED
        assert json.loads(zf.read("a.json"))["note"].endswith("@anon.lgpd")


def test_hash_fields_are_not_altered(exports):
    data = {
        "payload_hash": "12345678901234567890123456789012",
        "value_hash": "00000000000000000000000000000000",
        "content_hash": "11111111111111111111111111111111",
    }
    (exports / "h.json").write_text(json.dumps(data), encoding="utf-8")

    members = _members(_build(exports))

    assert json.loads(members["h.json"]) == data


def test_two_builds_give_identical_archives(exports, report_path):
    (exports / "a.json").write_text(json.dumps({"n": FAKE_EMAIL}), encoding="utf-8")
    (exports / "b.json").write_text('{"ok": true}', encoding="utf-8")

    first = _members(_build(exports))
    second = _members(_build(exports))

    assert list(first) == list(second)
    assert first == second
    # The scrubbed content is a fixpoint: scanning the archive's own text
    # finds nothing more.
    from src.core.logic.pii_anonymizer import scan_text

    for content in second.values():
        _, counts = scan_text(content.decode("utf-8"))
        assert sum(counts.values()) == 0


def test_known_fields_with_malformed_values_are_tokenized(exports):
    data = {"email": "not-an-address", "OrientadoCpf": 12345678901}
    (exports / "k.json").write_text(json.dumps(data), encoding="utf-8")

    members = _members(_build(exports))

    out = json.loads(members["k.json"])
    assert out["email"].endswith("@anon.lgpd")
    assert out["OrientadoCpf"].startswith("LGPD-")


def test_project_documents_also_go_through_the_scan(exports, report_path):
    folder = exports / "project_sigpesq_files_json"
    folder.mkdir()
    (folder / "PJ_1.json").write_text(
        json.dumps({"email": "not-an-address", "text": FAKE_EMAIL}),
        encoding="utf-8",
    )

    members = _members(_build(exports))

    out = json.loads(members["project_sigpesq_files_json/PJ_1.json"])
    assert out["email"].endswith("@anon.lgpd")
    assert FAKE_EMAIL not in json.dumps(out)


def test_undecodable_json_raises_and_keeps_previous_archive(exports):
    previous = exports / "exports_canonical.zip"
    previous.write_bytes(b"previous archive")
    (exports / "bad.json").write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28")

    with pytest.raises(Exception):
        zip_exports_task.fn(str(exports))

    assert previous.read_bytes() == b"previous archive"
    assert not (exports / "exports_canonical.zip.tmp").exists()


def test_other_extensions_and_undecodable_text_are_left_out(exports, report_path):
    (exports / "ok.json").write_text("{}", encoding="utf-8")
    (exports / "image.png").write_bytes(b"\x89PNG")
    (exports / "notes.txt").write_bytes(b"\xff\xfe\xc3\x28")

    members = _members(_build(exports))

    assert list(members) == ["ok.json", "export_manifest.json"]
    left_out = {
        entry["file"]: entry["reason"] for entry in _report(report_path)["left_out"]
    }
    assert set(left_out) == {"image.png", "notes.txt"}


def test_source_files_are_not_modified(exports):
    path = exports / "a.json"
    path.write_text(json.dumps({"n": FAKE_EMAIL}), encoding="utf-8")
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns

    _build(exports)

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime


def test_no_hmac_key_raises(exports, monkeypatch):
    monkeypatch.delenv("HORIZON_PII_HMAC_KEY", raising=False)
    (exports / "a.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError):
        zip_exports_task.fn(str(exports))

    assert not (exports / "exports_canonical.zip").exists()


def test_exporters_scrub_already_and_planted_file_is_caught(exports, report_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    from src.adapters.sinks.json_sink import JsonSink
    from src.core.logic.canonical_exporter import CanonicalDataExporter

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=JsonSink())
    exporter._campus_resolver = SimpleNamespace(get_campus=lambda *_a, **_k: None)

    initiative = SimpleNamespace(
        id=1,
        name="Projeto",
        status="active",
        description=f"Contact {FAKE_EMAIL}",
        start_date=None,
        end_date=None,
        initiative_type_id=None,
        organization_id=None,
        parent_id=None,
        demandante=None,
        metadata=None,
    )
    exporter.initiative_ctrl.get_all.return_value = [initiative]
    exporter.initiative_ctrl.list_initiative_types.return_value = []
    exporter.initiative_ctrl.get_teams.return_value = []
    exporter.org_ctrl.get_all.return_value = []

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            text = getattr(statement, "text", str(statement))
            if "entity_matches" in text:
                return FakeResult([])
            return FakeResult(
                [
                    {
                        "id": 1,
                        "name": "Orientacao",
                        "status": "active",
                        "description": f"Phone {FAKE_PHONE} mail {FAKE_EMAIL}",
                        "start_date": None,
                        "end_date": None,
                        "advisorship_type": "Scientific Initiation",
                        "advisorship_program": None,
                        "initiative_type_name": "Advisorship",
                        "person_id": 1,
                        "person_name": "Aluno A",
                        "supervisor_id": 2,
                        "supervisor_name": "Orientador B",
                        "fellowship_id": None,
                        "fellowship_name": None,
                        "fellowship_description": None,
                        "fellowship_value": None,
                        "sponsor_name": None,
                        "parent_id": None,
                        "parent_name": None,
                        "parent_status": None,
                        "parent_description": None,
                        "parent_start_date": None,
                        "parent_end_date": None,
                    }
                ]
            )

    exporter.initiative_ctrl._service._repository._session = FakeSession()
    with (
        patch("src.core.logic.canonical_exporter.ResearchGroupController"),
        patch("eo_lib.TeamController"),
    ):
        exporter.export_initiatives(str(exports / "initiatives_canonical.json"))
    exporter.export_advisorships(str(exports / "advisorships_canonical.json"))

    _build(exports)
    assert _report(report_path)["matches"] == {}

    (exports / "planted.json").write_text(
        json.dumps({"n": FAKE_EMAIL}), encoding="utf-8"
    )
    members = _members(_build(exports))

    assert list(_report(report_path)["matches"]) == ["planted.json"]
    assert FAKE_EMAIL not in members["planted.json"].decode("utf-8")


def test_a_build_over_the_size_limit_raises_and_keeps_the_previous_archive(
    exports, monkeypatch
):
    previous = exports / "exports_canonical.zip"
    previous.write_bytes(b"previous archive")
    (exports / "big.json").write_text(
        json.dumps({"text": "x" * 5000}), encoding="utf-8"
    )
    monkeypatch.setattr(canonical_data, "MAX_ARCHIVE_BYTES", 100)

    with pytest.raises(Exception, match="limit"):
        zip_exports_task.fn(str(exports))

    assert previous.read_bytes() == b"previous archive"
    assert not (exports / "exports_canonical.zip.tmp").exists()


def test_a_build_under_the_size_limit_replaces_the_archive(exports, monkeypatch):
    previous = exports / "exports_canonical.zip"
    previous.write_bytes(b"previous archive")
    (exports / "small.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(canonical_data, "MAX_ARCHIVE_BYTES", 1024 * 1024)

    zip_exports_task.fn(str(exports))

    assert zipfile.is_zipfile(previous)
    assert not (exports / "exports_canonical.zip.tmp").exists()


def test_the_default_size_limit_is_100_mib():
    assert canonical_data.MAX_ARCHIVE_BYTES == 100 * 1024 * 1024


# --- the manifest: one official key for everything published ---


def _manifest(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist()[-1] == "export_manifest.json"
        return json.loads(zf.read("export_manifest.json"))


def test_archive_ends_with_the_manifest(exports, monkeypatch):
    from src.core.logic.pii_anonymizer import key_fingerprint

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (exports / "a.json").write_text("{}", encoding="utf-8")

    manifest = _manifest(_build(exports))

    assert manifest == {"official": True, "key_fingerprint": key_fingerprint()}


@pytest.mark.parametrize("value", [None, "", "false", "1", "True"])
def test_only_github_actions_true_is_official(exports, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", value)
    (exports / "a.json").write_text("{}", encoding="utf-8")

    assert _manifest(_build(exports))["official"] is False


def test_manifest_has_no_timestamp_and_builds_are_identical(exports):
    (exports / "a.json").write_text("{}", encoding="utf-8")

    first = _members(_build(exports))
    second = _members(_build(exports))

    assert set(json.loads(first["export_manifest.json"])) == {
        "official",
        "key_fingerprint",
    }
    assert first == second


def test_a_manifest_file_in_the_folder_is_not_trusted(exports):
    (exports / "export_manifest.json").write_text(
        json.dumps({"official": True, "key_fingerprint": "0" * 16}), encoding="utf-8"
    )

    with zipfile.ZipFile(_build(exports)) as zf:
        names = zf.namelist()
        assert names.count("export_manifest.json") == 1
        assert (
            json.loads(zf.read("export_manifest.json"))["key_fingerprint"] != "0" * 16
        )
