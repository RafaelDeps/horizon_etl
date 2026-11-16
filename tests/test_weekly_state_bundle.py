"""Spec 029: the encrypted state bundle, its staging and the seal command."""

import base64
import io
import json
import os
import tarfile

import pytest

from src.scripts import weekly_state_bundle as wsb
from src.scripts.restore_weekly_artifact import RestoreError
from src.scripts.weekly_state_bundle import open_bundle, seal_bundle

KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()
OTHER_KEY = base64.urlsafe_b64encode(bytes(range(1, 33))).decode()
FAKE_EMAIL = "person@example.test"


def _tree(root):
    (root / "db").mkdir(parents=True)
    (root / "db" / "horizon.db").write_bytes(b"SQLite format 3\x00" + b"x" * 500)
    (root / "data" / "raw").mkdir(parents=True)
    (root / "data" / "raw" / "a.txt").write_text("raw content a", encoding="utf-8")
    (root / "cache").mkdir()
    (root / "cache" / "b").write_text("cache content b", encoding="utf-8")
    return root


def _snapshot(root):
    files = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            with open(path, "rb") as fh:
                files[os.path.relpath(path, root)] = fh.read()
    return files


def _crafted(tmp_path, build, key=KEY):
    """A bundle holding a hand-made tar, sealed with a real key."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        build(tar)
    path = tmp_path / "crafted.bundle"
    path.write_bytes(wsb._encrypt_payload(buffer.getvalue(), wsb.parse_key(key)))
    return str(path)


def _add_file(tar, name, content=b"data"):
    info = tarfile.TarInfo(name)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def test_round_trip_is_byte_identical(tmp_path):
    src = _tree(tmp_path / "src")
    bundle = tmp_path / "weekly_state.bundle"

    result = seal_bundle(str(src), str(bundle), KEY)
    dest = tmp_path / "dest"
    dest.mkdir()
    open_bundle(str(bundle), str(dest), [KEY])

    assert result["bundle_bytes"] == bundle.stat().st_size
    assert _snapshot(dest) == _snapshot(src)


def test_bundle_hides_names_and_contents(tmp_path):
    src = _tree(tmp_path / "src")
    bundle = tmp_path / "weekly_state.bundle"

    seal_bundle(str(src), str(bundle), KEY)

    raw = bundle.read_bytes()
    assert raw.startswith(b"HZSTATE1")
    for plain in (b"horizon.db", b"raw content a", b"cache content b", b"a.txt"):
        assert plain not in raw


@pytest.mark.parametrize("damage", ["flip", "truncate", "wrong_key", "short_key"])
def test_bad_bundle_or_key_fails_and_extracts_nothing(tmp_path, damage):
    src = _tree(tmp_path / "src")
    bundle = tmp_path / "weekly_state.bundle"
    seal_bundle(str(src), str(bundle), KEY)
    raw = bytearray(bundle.read_bytes())
    key = KEY
    if damage == "flip":
        raw[len(raw) // 2] ^= 0x01
    elif damage == "truncate":
        raw = raw[: len(raw) - 40]
    elif damage == "wrong_key":
        key = OTHER_KEY
    else:
        key = "a passphrase of sorts"
    bundle.write_bytes(bytes(raw))
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(RestoreError) as error:
        open_bundle(str(bundle), str(dest), [key])

    expected = (
        "state bundle: no key"
        if damage == "short_key"
        else "state bundle: failed authentication"
    )
    assert error.value.reason == expected
    assert list(dest.iterdir()) == []
    assert KEY not in str(error.value) and OTHER_KEY not in str(error.value)


def test_no_keys_at_all_is_no_key(tmp_path):
    src = _tree(tmp_path / "src")
    bundle = tmp_path / "weekly_state.bundle"
    seal_bundle(str(src), str(bundle), KEY)
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(RestoreError) as error:
        open_bundle(str(bundle), str(dest), [None, ""])

    assert error.value.reason == "state bundle: no key"


def _unsafe_cases():
    def dotdot(tar):
        _add_file(tar, "cache/../../escape")

    def absolute(tar):
        _add_file(tar, "/etc/escape")

    def symlink(tar):
        info = tarfile.TarInfo("cache/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)

    def hardlink(tar):
        info = tarfile.TarInfo("cache/hard")
        info.type = tarfile.LNKTYPE
        info.linkname = "db/horizon.db"
        tar.addfile(info)

    def device(tar):
        info = tarfile.TarInfo("cache/dev")
        info.type = tarfile.CHRTYPE
        tar.addfile(info)

    def outside(tar):
        _add_file(tar, "db/horizon.db")
        _add_file(tar, "other/file")

    return {
        "dotdot": dotdot,
        "absolute": absolute,
        "symlink": symlink,
        "hardlink": hardlink,
        "device": device,
        "outside": outside,
    }


@pytest.mark.parametrize("case", sorted(_unsafe_cases()))
def test_unsafe_member_fails_and_extracts_nothing(tmp_path, case):
    path = _crafted(tmp_path, _unsafe_cases()[case])
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(RestoreError) as error:
        open_bundle(path, str(dest), [KEY])

    assert error.value.reason == "state bundle: unsafe member"
    assert list(dest.iterdir()) == []
    assert not (tmp_path / "escape").exists()


def test_previous_key_opens_a_bundle_sealed_with_it(tmp_path):
    src = _tree(tmp_path / "src")
    bundle = tmp_path / "weekly_state.bundle"
    seal_bundle(str(src), str(bundle), OTHER_KEY)
    dest = tmp_path / "dest"
    dest.mkdir()

    open_bundle(str(bundle), str(dest), [KEY, OTHER_KEY])

    assert _snapshot(dest) == _snapshot(src)


def test_error_messages_hold_no_key_or_content(tmp_path):
    src = _tree(tmp_path / "src")
    bundle = tmp_path / "weekly_state.bundle"
    seal_bundle(str(src), str(bundle), KEY)
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(RestoreError) as error:
        open_bundle(str(bundle), str(dest), [OTHER_KEY])

    text = repr(error.value) + str(error.value)
    assert OTHER_KEY not in text and "raw content" not in text


def test_seal_with_an_unusable_key_raises_no_key(tmp_path):
    src = _tree(tmp_path / "src")

    with pytest.raises(RestoreError) as error:
        seal_bundle(str(src), str(tmp_path / "b"), "short")

    assert error.value.reason == "state bundle: no key"
    assert not (tmp_path / "b").exists()


# --- staging and the seal command ---


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = _tree(tmp_path / "ws")
    (root / "data" / "reports").mkdir(parents=True)
    (root / "data" / "reports" / "ok.json").write_text('{"a": 1}', encoding="utf-8")
    (root / "data" / "reports" / "leak.json").write_text(
        json.dumps({"n": FAKE_EMAIL}), encoding="utf-8"
    )
    (root / "data" / "reports" / "image.png").write_bytes(b"\x89PNG")
    (root / "data" / "exports" / "docentes").mkdir(parents=True)
    (root / "data" / "exports" / "docentes" / "page.html").write_text(
        "<p>hello</p>", encoding="utf-8"
    )
    (root / "data" / "exports" / "exports_canonical.zip").write_bytes(b"zip")
    monkeypatch.chdir(root)
    calls = []
    monkeypatch.setattr(
        wsb, "finalize_sqlite_database", lambda url: calls.append("finalize") or {}
    )

    def fake_verify(db_path, report_dir, vacuumed=False):
        calls.append("verify")
        os.makedirs(report_dir, exist_ok=True)
        with open(os.path.join(report_dir, "database_verify_report.json"), "w") as fh:
            fh.write("{}")
        return {}

    monkeypatch.setattr(wsb, "verify_database", fake_verify)
    monkeypatch.delenv("HORIZON_STATE_KEY", raising=False)
    return root, calls


def _names(folder):
    return sorted(
        os.path.relpath(os.path.join(f, n), folder)
        for f, _d, ns in os.walk(folder)
        for n in ns
    )


def test_stage_public_copies_clean_text_only(workspace, tmp_path):
    root, _ = workspace
    out = tmp_path / "out"

    report = wsb.stage_public(str(root), str(out))

    staged = _names(out / "public")
    assert "data/reports/ok.json" in staged
    assert "data/exports/docentes/page.html" in staged
    assert "data/reports/leak.json" not in staged
    assert not any(n.endswith(".png") or n.endswith(".zip") for n in staged)
    assert report["public_left_out"] == ["data/reports/leak.json"]
    assert report["public_files"] == len(staged)
    assert FAKE_EMAIL not in json.dumps(report)


def test_seal_with_a_key_stages_bundle_and_public_only(workspace, tmp_path, capsys):
    root, calls = workspace
    os.environ["HORIZON_STATE_KEY"] = KEY
    out = tmp_path / "out"
    try:
        code = wsb.main(["seal", "--out", str(out)])
    finally:
        del os.environ["HORIZON_STATE_KEY"]

    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == ["public", "weekly_state.bundle"]
    staged = _names(out)
    assert not any(n.endswith("horizon.db") or "raw/a.txt" in n for n in staged)
    report = json.loads(
        (out / "public" / "artifact_stage_report.json").read_text(encoding="utf-8")
    )
    assert report["state"] == "sealed"
    assert report["bundle_bytes"] == (out / "weekly_state.bundle").stat().st_size
    assert calls == ["finalize", "verify"]
    assert "database_verify_report.json" in " ".join(staged)
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err
    assert KEY not in json.dumps(report)


@pytest.mark.parametrize("key", [None, "a passphrase of sorts"])
def test_seal_without_a_usable_key_is_skipped(workspace, tmp_path, capsys, key):
    if key:
        os.environ["HORIZON_STATE_KEY"] = key
    out = tmp_path / "out"
    try:
        code = wsb.main(["seal", "--out", str(out)])
    finally:
        os.environ.pop("HORIZON_STATE_KEY", None)

    assert code == 0
    assert not (out / "weekly_state.bundle").exists()
    report = json.loads((out / "public" / "artifact_stage_report.json").read_text())
    assert report["state"] == "skipped"
    assert "::warning" in capsys.readouterr().out
    staged = _names(out)
    assert not any(n.endswith("horizon.db") for n in staged)
    assert not any("leak.json" in n for n in staged)


def test_seal_io_error_removes_partial_files_and_exits_zero(
    workspace, tmp_path, monkeypatch, capsys
):
    os.environ["HORIZON_STATE_KEY"] = KEY
    out = tmp_path / "out"

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(wsb, "seal_bundle", broken)
    try:
        code = wsb.main(["seal", "--out", str(out)])
    finally:
        del os.environ["HORIZON_STATE_KEY"]

    assert code == 0
    assert not (out / "weekly_state.bundle").exists()
    report = json.loads((out / "public" / "artifact_stage_report.json").read_text())
    assert report["state"] == "failed"
    assert "::warning" in capsys.readouterr().out
    # No leftover temporary folder with plain state in the workspace.
    root, _ = workspace
    assert not [p for p in root.iterdir() if p.name.startswith(".seal-")]


def test_stage_public_keeps_a_report_whose_keys_are_count_names(workspace, tmp_path):
    root, _ = workspace
    (root / "data" / "reports" / "database_verify_report.json").write_text(
        json.dumps({"file_bytes_hits": {"email": 0, "phone": 0, "cpf": 0}}),
        encoding="utf-8",
    )

    report = wsb.stage_public(str(root), str(tmp_path / "out"))

    assert "data/reports/database_verify_report.json" not in report["public_left_out"]
    assert "data/reports/database_verify_report.json" in _names(
        tmp_path / "out" / "public"
    )
