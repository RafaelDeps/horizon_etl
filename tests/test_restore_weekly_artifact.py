"""Spec 022: restoring the previous weekly run's database, raw downloads and
Lattes cache. A fake ``gh`` on PATH answers from recorded JSON, and every
target is a temporary folder: no network, never the repository's database."""

import hashlib
import json
import os
import sqlite3
import stat
import zipfile

import pytest

from src.scripts import restore_weekly_artifact as restore

REPO = "RafaelDeps/horizon_etl"
BRANCH = "025-ci-persistent-database"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _database(path, tables=("persons", "horizon_meta")):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    for table in tables:
        con.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, name TEXT)")
    if "persons" in tables:
        con.execute("INSERT INTO persons (name) VALUES ('Maria da Silva')")
    con.commit()
    con.close()


def _write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


@pytest.fixture
def artifact_dir(tmp_path):
    """A small artifact as the upload lays it out: db/, data/, cache/."""
    root = tmp_path / "artifact"
    _database(str(root / "db" / "horizon.db"))
    _write(
        str(root / "data" / "raw" / "sigpesq" / "research_group" / "r.xlsx"), b"report"
    )
    _write(
        str(
            root
            / "data"
            / "raw"
            / "sigpesq_project_files"
            / "project_files"
            / "PJ_1.pdf"
        ),
        b"pdf",
    )
    _write(str(root / "data" / "exports" / "researchers_canonical.json"), b"[]")
    _write(str(root / "cache" / "lattes" / "1234567890123456.html"), b"<html/>")
    return root


def _target(tmp_path):
    target = tmp_path / "target"
    _write(str(target / "data" / "exports" / "keep.json"), b"keep")
    _write(str(target / "data" / "lattes_json" / "keep.json"), b"keep")
    _write(str(target / "data" / "raw" / "stale.txt"), b"stale")
    return target


def _run(argv, monkeypatch=None):
    assert restore.main(argv) == 0


def _outcome(target):
    with open(target / "data" / "reports" / "restore_outcome.json") as f:
        return json.load(f)


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    """Puts a ``gh`` on PATH. ``configure(runs, artifacts, download_from,
    download_rc)`` sets its answers; every call is appended to calls.log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "gh_state.json"
    calls = tmp_path / "calls.log"
    script = bin_dir / "gh"
    script.write_text(
        f"""#!{__import__('sys').executable}
import json, shutil, sys
state = json.load(open({str(state)!r}))
open({str(calls)!r}, "a").write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] == ["run", "list"]:
    print(json.dumps(state["runs"]))
elif args[0] == "api":
    run_id = args[1].split("/")[-2]
    print(json.dumps({{"artifacts": state["artifacts"].get(run_id, [])}}))
elif args[:2] == ["run", "download"]:
    if state.get("download_rc"):
        sys.stderr.write("artifact not found\\n")
        sys.exit(state["download_rc"])
    dest = args[args.index("-D") + 1]
    shutil.copytree(state["download_from"], dest, dirs_exist_ok=True)
else:
    sys.exit(9)
"""
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    def configure(runs, artifacts, download_from="", download_rc=0):
        state.write_text(
            json.dumps(
                {
                    "runs": runs,
                    "artifacts": artifacts,
                    "download_from": str(download_from),
                    "download_rc": download_rc,
                }
            )
        )
        return calls

    return configure


def _runs():
    return [
        {
            "databaseId": 1,
            "createdAt": "2026-10-22T02:00:00Z",
            "headSha": "a" * 40,
            "event": "schedule",
        },
        {
            "databaseId": 3,
            "createdAt": "2026-11-05T02:00:00Z",
            "headSha": "c" * 40,
            "event": "schedule",
        },
        {
            "databaseId": 2,
            "createdAt": "2026-10-29T02:00:00Z",
            "headSha": "b" * 40,
            "event": "workflow_dispatch",
        },
    ]


def _live(expired=False):
    return [{"name": restore.ARTIFACT, "expired": expired, "size_in_bytes": 10}]


# --------------------------------------------------------------------------
# US1: restore from the previous successful run
# --------------------------------------------------------------------------


def test_from_dir_places_the_three_items_and_nothing_else(tmp_path, artifact_dir):
    target = _target(tmp_path)
    _database(str(target / "db" / "horizon.db"), tables=("old",))
    _write(str(target / "db" / "horizon.db-wal"), b"stale log")
    _write(str(target / "db" / "horizon.db-shm"), b"stale shm")

    _run(["--from-dir", str(artifact_dir), "--target", str(target)])

    outcome = _outcome(target)
    assert outcome["outcome"] == "restored" and outcome["reason"] is None
    assert _sha(target / "db" / "horizon.db") == _sha(
        artifact_dir / "db" / "horizon.db"
    )
    assert not (target / "db" / "horizon.db-wal").exists()
    assert not (target / "db" / "horizon.db-shm").exists()
    assert (target / "data" / "raw" / "sigpesq" / "research_group" / "r.xlsx").exists()
    assert not (target / "data" / "raw" / "stale.txt").exists()  # replaced whole
    assert (target / "cache" / "lattes" / "1234567890123456.html").exists()
    # Not restored: produced again by the run.
    assert (target / "data" / "exports" / "keep.json").read_bytes() == b"keep"
    assert not (target / "data" / "exports" / "researchers_canonical.json").exists()
    assert (target / "data" / "lattes_json" / "keep.json").exists()
    # The simulation's artifact folder is left as it was.
    assert (artifact_dir / "db" / "horizon.db").exists()
    assert not [p for p in os.listdir(target) if p.startswith(".restore-")]
    assert outcome["restored"]["db_bytes"] > 0


def test_from_zip_gives_the_same_result(tmp_path, artifact_dir):
    archive = tmp_path / "weekly-etl-artifacts.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for folder, _dirs, files in os.walk(artifact_dir):
            for name in files:
                path = os.path.join(folder, name)
                z.write(path, os.path.relpath(path, artifact_dir))
    target = _target(tmp_path)
    _run(["--from-zip", str(archive), "--target", str(target)])
    assert _outcome(target)["outcome"] == "restored"
    assert _sha(target / "db" / "horizon.db") == _sha(
        artifact_dir / "db" / "horizon.db"
    )


def test_github_restores_the_newest_successful_run_with_a_live_artifact(
    tmp_path, artifact_dir, fake_gh
):
    # Run 3 is the newest but its artifact expired: run 2 is used.
    calls = fake_gh(
        _runs(), {"3": _live(expired=True), "2": _live(), "1": _live()}, artifact_dir
    )
    target = _target(tmp_path)
    _run(["--github", "--repo", REPO, "--branch", BRANCH, "--target", str(target)])

    outcome = _outcome(target)
    assert outcome["outcome"] == "restored"
    assert outcome["source_run"] == {
        "id": 2,
        "created_at": "2026-10-29T02:00:00Z",
        "head_sha": "b" * 40,
        "event": "workflow_dispatch",
    }
    log = calls.read_text()
    assert (
        f"--repo {REPO} --workflow weekly-etl.yml --branch {BRANCH} --status success"
        in log
    )
    assert f"run download 2 --repo {REPO} -n weekly-etl-artifacts" in log


# --------------------------------------------------------------------------
# US2: every failure rebuilds, with its reason, and exits 0
# --------------------------------------------------------------------------


def _rebuilt(target, reason_start):
    outcome = _outcome(target)
    assert outcome["outcome"] == "rebuilt"
    assert outcome["reason"].startswith(reason_start), outcome["reason"]
    return outcome


def test_no_successful_run(tmp_path, fake_gh):
    fake_gh([], {})
    target = _target(tmp_path)
    _run(["--github", "--repo", REPO, "--branch", BRANCH, "--target", str(target)])
    assert _rebuilt(target, "no successful run")["source_run"] is None
    assert not (target / "db" / "horizon.db").exists()


def test_every_artifact_expired(tmp_path, fake_gh):
    fake_gh(_runs(), {"1": _live(True), "2": _live(True), "3": []})
    target = _target(tmp_path)
    _run(["--github", "--repo", REPO, "--branch", BRANCH, "--target", str(target)])
    _rebuilt(target, "artifact expired")


def test_download_failure_keeps_the_target_as_it_was(tmp_path, fake_gh):
    fake_gh(_runs(), {"3": _live()}, download_rc=1)
    target = _target(tmp_path)
    _run(["--github", "--repo", REPO, "--branch", BRANCH, "--target", str(target)])
    outcome = _rebuilt(target, "download failed: gh run exited 1 (artifact not found)")
    assert outcome["source_run"]["id"] == 3
    assert (target / "data" / "raw" / "stale.txt").exists()


def test_gh_missing_is_a_download_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    target = _target(tmp_path)
    _run(["--github", "--repo", REPO, "--branch", BRANCH, "--target", str(target)])
    _rebuilt(target, "download failed: the gh CLI is not installed")


def test_missing_database_still_places_raw_and_cache(tmp_path, artifact_dir):
    os.remove(artifact_dir / "db" / "horizon.db")
    target = _target(tmp_path)
    _run(["--from-dir", str(artifact_dir), "--target", str(target)])
    outcome = _rebuilt(target, "database missing")
    assert not (target / "db" / "horizon.db").exists()
    assert (target / "cache" / "lattes" / "1234567890123456.html").exists()
    assert outcome["restored"]["db_bytes"] == 0
    assert outcome["restored"]["cache_bytes"] > 0


def test_damaged_database_is_not_placed(tmp_path, artifact_dir):
    path = artifact_dir / "db" / "horizon.db"
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2] + b"\0" * 100)
    target = _target(tmp_path)
    _database(str(target / "db" / "horizon.db"), tables=("previous",))
    before = _sha(target / "db" / "horizon.db")
    _run(["--from-dir", str(artifact_dir), "--target", str(target)])
    _rebuilt(target, "database check failed")
    assert _sha(target / "db" / "horizon.db") == before


def test_database_without_the_weekly_tables_is_not_placed(tmp_path, artifact_dir):
    path = artifact_dir / "db" / "horizon.db"
    os.remove(path)
    _database(str(path), tables=("persons",))
    target = _target(tmp_path)
    _run(["--from-dir", str(artifact_dir), "--target", str(target)])
    _rebuilt(target, "database check failed: no table horizon_meta")


def test_restore_disabled(tmp_path):
    target = _target(tmp_path)
    _run(["--disabled", "--target", str(target)])
    _rebuilt(target, "restore disabled")
    assert (target / "data" / "raw" / "stale.txt").exists()


# --------------------------------------------------------------------------
# US3: the restored files are the files the phases read
# --------------------------------------------------------------------------


def test_a_compressed_raw_file_is_restored_as_itself(tmp_path, artifact_dir):
    folder = artifact_dir / "data" / "raw" / "sigpesq_project_files" / "project_files"
    original = os.urandom(4096)
    (folder / "PJ_9.pdf").write_bytes(original)
    with zipfile.ZipFile(folder / "PJ_9.pdf.zip", "w") as z:
        z.write(folder / "PJ_9.pdf", "PJ_9.pdf")
    os.remove(folder / "PJ_9.pdf")
    # A real zip (other member name) stays a zip.
    with zipfile.ZipFile(folder / "bundle.zip", "w") as z:
        z.writestr("inner.txt", "inner")
    target = _target(tmp_path)
    _run(["--from-dir", str(artifact_dir), "--target", str(target)])

    restored = target / "data" / "raw" / "sigpesq_project_files" / "project_files"
    assert (restored / "PJ_9.pdf").read_bytes() == original
    assert not (restored / "PJ_9.pdf.zip").exists()
    assert (restored / "bundle.zip").exists()


def test_cache_is_restored_byte_for_byte(tmp_path, artifact_dir):
    page = artifact_dir / "cache" / "lattes" / "1234567890123456.html"
    page.write_bytes(os.urandom(2048))
    expected = _sha(page)
    target = _target(tmp_path)
    _run(["--from-dir", str(artifact_dir), "--target", str(target)])
    assert _sha(target / "cache" / "lattes" / "1234567890123456.html") == expected


# --------------------------------------------------------------------------
# US4: the run says where its database came from
# --------------------------------------------------------------------------


def test_summary_of_a_restored_run(tmp_path, artifact_dir, fake_gh, monkeypatch):
    fake_gh(_runs(), {"3": _live()}, artifact_dir)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    target = _target(tmp_path)
    _run(["--github", "--repo", REPO, "--branch", BRANCH, "--target", str(target)])
    text = summary.read_text()
    assert (
        f"Restored from run [3](https://github.com/{REPO}/actions/runs/3) "
        f"of 2026-11-05 (`ccccccc`)"
    ) in text
    assert "database 0 MB, data/raw 0 MB, cache 0 MB." in text
    assert set(_outcome(target)) == {
        "outcome",
        "reason",
        "source_run",
        "restored",
        "checked_at",
        "format",  # spec 029
    }


def test_summary_of_a_rebuilt_run(tmp_path):
    summary = tmp_path / "summary.md"
    target = _target(tmp_path)
    _run(["--disabled", "--target", str(target), "--summary", str(summary)])
    assert (
        summary.read_text() == "### Database\nRebuilt from scratch: restore disabled.\n"
    )


def test_log_lines():
    run = {
        "id": 7,
        "created_at": "2026-10-29T10:15:56Z",
        "head_sha": "4d93988ab",
        "event": "x",
    }
    sizes = {
        "db_bytes": 318 * 1048576,
        "data_raw_bytes": 223 * 1048576,
        "cache_bytes": 66 * 1048576,
    }
    assert restore.log_line(restore.Outcome("restored", None, run, sizes)) == (
        "restore: restored db/horizon.db (318 MB), data/raw (223 MB), cache (66 MB) "
        "from run 7 (2026-10-29, 4d93988)"
    )
    assert restore.log_line(restore.Outcome("rebuilt", "artifact expired")) == (
        "restore: rebuilt — artifact expired"
    )


# --------------------------------------------------------------------------
# Spec 029: the encrypted state bundle
# --------------------------------------------------------------------------

import base64  # noqa: E402

from src.core.logic.pii_anonymizer import key_fingerprint  # noqa: E402
from src.scripts.weekly_state_bundle import seal_bundle  # noqa: E402

STATE_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()
OLD_STATE_KEY = base64.urlsafe_b64encode(bytes(range(1, 33))).decode()


def _stamp(path, value):
    con = sqlite3.connect(path)
    con.execute("DROP TABLE horizon_meta")
    con.execute("CREATE TABLE horizon_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if value is not None:
        con.execute(
            "INSERT INTO horizon_meta VALUES ('pii_key_fingerprint', ?)", (value,)
        )
    con.commit()
    con.close()


def _download(tmp_path, artifact_dir, key=STATE_KEY, name="download"):
    """What the artifact download holds: the bundle and public text only."""
    folder = tmp_path / name
    folder.mkdir()
    seal_bundle(str(artifact_dir), str(folder / "weekly_state.bundle"), key)
    _write(str(folder / "public" / "data" / "reports" / "r.json"), b"{}")
    return folder


@pytest.fixture
def state_key(monkeypatch):
    monkeypatch.setenv("HORIZON_STATE_KEY", STATE_KEY)
    monkeypatch.delenv("HORIZON_STATE_KEY_PREVIOUS", raising=False)


def test_bundle_restores_the_three_items(tmp_path, artifact_dir, state_key):
    folder = _download(tmp_path, artifact_dir)
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    outcome = _outcome(target)
    assert outcome["outcome"] == "restored" and outcome["format"] == "bundle"
    assert _sha(target / "db" / "horizon.db") == _sha(
        artifact_dir / "db" / "horizon.db"
    )
    assert (target / "cache" / "lattes" / "1234567890123456.html").exists()
    assert not (target / "weekly_state.bundle").exists()


def test_legacy_layout_still_restores(tmp_path, artifact_dir):
    target = _target(tmp_path)

    _run(["--from-dir", str(artifact_dir), "--target", str(target)])

    outcome = _outcome(target)
    assert outcome["outcome"] == "restored" and outcome["format"] == "legacy"


@pytest.mark.parametrize("damage", ["flip", "truncate"])
def test_tampered_bundle_is_rebuilt_and_places_nothing(
    tmp_path, artifact_dir, state_key, damage
):
    folder = _download(tmp_path, artifact_dir)
    bundle = folder / "weekly_state.bundle"
    raw = bytearray(bundle.read_bytes())
    if damage == "flip":
        raw[len(raw) // 2] ^= 0x01
    else:
        raw = raw[:-30]
    bundle.write_bytes(bytes(raw))
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    outcome = _rebuilt(target, "state bundle: failed authentication")
    assert outcome["format"] is None
    assert not (target / "db" / "horizon.db").exists()
    assert (target / "data" / "raw" / "stale.txt").exists()  # nothing placed
    assert not (target / "cache").exists()


def test_bundle_without_a_key_is_rebuilt(tmp_path, artifact_dir, monkeypatch):
    folder = _download(tmp_path, artifact_dir)
    monkeypatch.delenv("HORIZON_STATE_KEY", raising=False)
    monkeypatch.delenv("HORIZON_STATE_KEY_PREVIOUS", raising=False)
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    _rebuilt(target, "state bundle: no key")


def test_bundle_with_an_unsafe_member_is_rebuilt(
    tmp_path, artifact_dir, state_key, monkeypatch
):
    import io
    import tarfile

    from src.scripts import weekly_state_bundle as wsb

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    folder = tmp_path / "download"
    folder.mkdir()
    (folder / "weekly_state.bundle").write_bytes(
        wsb._encrypt_payload(buffer.getvalue(), wsb.parse_key(STATE_KEY))
    )
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    _rebuilt(target, "state bundle: unsafe member")
    assert not (tmp_path / "escape").exists()


def test_database_with_another_key_is_not_placed_but_raw_and_cache_are(
    tmp_path, artifact_dir, state_key
):
    _stamp(str(artifact_dir / "db" / "horizon.db"), "0" * 16)
    assert key_fingerprint() != "0" * 16
    folder = _download(tmp_path, artifact_dir)
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    outcome = _rebuilt(target, "database built with another key")
    assert outcome["format"] == "bundle"
    assert not (target / "db" / "horizon.db").exists()
    assert (target / "cache" / "lattes" / "1234567890123456.html").exists()
    assert (target / "data" / "raw" / "sigpesq" / "research_group" / "r.xlsx").exists()


def test_database_with_the_same_key_stamp_is_placed(tmp_path, artifact_dir, state_key):
    _stamp(str(artifact_dir / "db" / "horizon.db"), key_fingerprint())
    folder = _download(tmp_path, artifact_dir)
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    assert _outcome(target)["outcome"] == "restored"


def test_unstamped_database_is_accepted(tmp_path, artifact_dir, state_key):
    _stamp(str(artifact_dir / "db" / "horizon.db"), None)
    folder = _download(tmp_path, artifact_dir)
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    assert _outcome(target)["outcome"] == "restored"


def test_previous_key_is_tried_second(tmp_path, artifact_dir, monkeypatch):
    folder = _download(tmp_path, artifact_dir, key=OLD_STATE_KEY)
    monkeypatch.setenv("HORIZON_STATE_KEY", STATE_KEY)
    monkeypatch.setenv("HORIZON_STATE_KEY_PREVIOUS", OLD_STATE_KEY)
    target = _target(tmp_path)

    _run(["--from-dir", str(folder), "--target", str(target)])

    outcome = _outcome(target)
    assert outcome["outcome"] == "restored" and outcome["format"] == "bundle"
