"""Spec 029: the history purge. The pure redaction functions here; the driver
is tested on throwaway repositories further down. Nothing touches this
repository's history."""

import io
import json
import zipfile

from src.core.logic import pii_anonymizer
from src.scripts import purge_history_pii as purge

FAKE_EMAIL = "person@example.test"
FAKE_PHONE = "+55 00 00000-0000"
FAKE_CPF = "000.000.000-00"


def _zip(members, compress=zipfile.ZIP_DEFLATED, date=(2024, 5, 6, 7, 8, 10)):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=date)
            info.compress_type = compress
            zf.writestr(info, data)
    return buffer.getvalue()


def test_detectors_match_the_anonymizers():
    assert purge.EMAIL_RE.pattern == pii_anonymizer._EMAIL_RE.pattern
    assert purge.PHONE_RE.pattern == pii_anonymizer._PHONE_RE.pattern
    assert purge.CPF_RE.pattern == pii_anonymizer._CPF_RE.pattern


def test_redact_bytes_uses_the_constants():
    data = f"mail {FAKE_EMAIL} fone {FAKE_PHONE} cpf {FAKE_CPF}".encode()

    out, counts = purge.redact_bytes(data)

    text = out.decode()
    assert "redacted@anon.lgpd" in text
    assert "LGPD-PHONE-redacted" in text
    assert "LGPD-redacted" in text
    for plain in (FAKE_EMAIL, FAKE_PHONE, FAKE_CPF):
        assert plain not in text
    assert counts["email"] == 1 and counts["phone"] == 1 and counts["cpf"] == 1


def test_redact_bytes_known_json_fields():
    data = json.dumps(
        {"email": "not-an-address", "OrientadoCpf": 12345678901, "telefone": "12 3456"}
    ).encode()

    out, counts = purge.redact_bytes(data)

    parsed = json.loads(out)
    assert parsed["email"] == "redacted@anon.lgpd"
    assert parsed["OrientadoCpf"] == "LGPD-redacted"
    assert parsed["telefone"] == "LGPD-PHONE-redacted"
    assert counts["known_field"] == 3


def test_hash_values_are_blanked_by_default_and_kept_on_request():
    data = json.dumps({"payload_hash": "ab" * 32, "value_hash": "cd" * 32}).encode()

    blanked, counts = purge.redact_bytes(data, blank_hashes=True)
    kept, kept_counts = purge.redact_bytes(data, blank_hashes=False)

    assert json.loads(blanked) == {"payload_hash": "", "value_hash": ""}
    assert counts["hash"] == 2
    assert kept == data and kept_counts["hash"] == 0


def test_extra_terms_are_replaced_and_nothing_else_is_assumed():
    data = b"write to coordinator@example.test or other@example.test"

    out, counts = purge.redact_bytes(data, extra_terms=["coordinator@example.test"])

    assert b"coordinator@example.test" not in out
    # The default list is the detectors only: nothing outside the list is
    # assumed beyond what the detectors match.
    assert counts["terms"] == 1
    assert b"other@example.test" not in out  # matched by the e-mail detector
    out2, _ = purge.redact_bytes(b"plain words only", extra_terms=["absent term"])
    assert out2 == b"plain words only"


def test_clean_blob_is_returned_unchanged():
    data = b'{"a": 1, "note": "nothing"}'

    out, counts = purge.redact_bytes(data)

    assert out is data
    assert not any(counts.values())


def test_second_pass_changes_nothing():
    data = f"{FAKE_EMAIL} {FAKE_PHONE} {FAKE_CPF}".encode()
    once, _ = purge.redact_bytes(data)

    twice, counts = purge.redact_bytes(once)

    assert twice == once
    assert not any(counts.values())


def test_non_text_blob_is_reported_and_left():
    data = b"\xff\xfe\x00 not text \xc3\x28"

    out, counts = purge.redact_bytes(data)

    assert out is data
    assert counts["unreadable"] == 1


def test_redact_zip_changes_only_members_with_hits():
    original = _zip(
        {
            "clean.json": b'{"a": 1}',
            "dirty.json": json.dumps({"n": FAKE_EMAIL}).encode(),
        }
    )

    out, counts = purge.redact_zip(original)

    assert counts["email"] == 1
    with (
        zipfile.ZipFile(io.BytesIO(out)) as new,
        zipfile.ZipFile(io.BytesIO(original)) as old,
    ):
        assert new.namelist() == old.namelist()
        for name in new.namelist():
            assert new.getinfo(name).date_time == old.getinfo(name).date_time
            assert new.getinfo(name).compress_type == old.getinfo(name).compress_type
        assert new.read("clean.json") == old.read("clean.json")
        assert FAKE_EMAIL not in new.read("dirty.json").decode()


def test_redact_zip_keeps_the_blob_when_nothing_changed():
    original = _zip({"clean.json": b'{"a": 1}'})

    out, counts = purge.redact_zip(original)

    assert out is original
    assert not any(counts.values())


def test_redact_zip_second_pass_changes_nothing():
    original = _zip(
        {"d.json": json.dumps({"n": FAKE_EMAIL, "payload_hash": "ab"}).encode()}
    )
    once, _ = purge.redact_zip(original)

    twice, counts = purge.redact_zip(once)

    assert twice is once
    assert not any(counts.values())


def test_redact_zip_blank_hashes_flag():
    original = _zip({"d.json": json.dumps({"value_hash": "ab" * 32}).encode()})

    kept, _ = purge.redact_zip(original, blank_hashes=False)
    blanked, counts = purge.redact_zip(original, blank_hashes=True)

    assert kept is original
    assert counts["hash"] == 1
    with zipfile.ZipFile(io.BytesIO(blanked)) as zf:
        assert json.loads(zf.read("d.json")) == {"value_hash": ""}


def test_a_blob_that_is_not_a_zip_is_reported_and_left():
    out, counts = purge.redact_zip(b"this is not a zip")

    assert out == b"this is not a zip"
    assert counts["unreadable"] == 1


# --- the driver, on throwaway repositories ---------------------------------

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

FILTER_REPO_PYTHON = Path.home() / ".local/share/uv/tools/git-filter-repo/bin/python"
SCRIPT = Path(__file__).resolve().parent.parent / "src/scripts/purge_history_pii.py"
SYNTHETIC_TERM = "Synthetic Street 12345"

needs_filter_repo = pytest.mark.skipif(
    not FILTER_REPO_PYTHON.exists(),
    reason="the git-filter-repo interpreter is not installed",
)

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Synthetic Author",
    "GIT_AUTHOR_EMAIL": "author@example.test",
    "GIT_COMMITTER_NAME": "Synthetic Author",
    "GIT_COMMITTER_EMAIL": "author@example.test",
    "GIT_AUTHOR_DATE": "2024-01-02T03:04:05+00:00",
    "GIT_COMMITTER_DATE": "2024-01-02T03:04:05+00:00",
}


def _git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        env=GIT_ENV,
    )
    if check:
        assert result.returncode == 0, result.stderr.decode()
    return result.stdout.decode().strip()


def _write_file(root, relative, content):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())


def _archive(version):
    return _zip(
        {
            "a.json": json.dumps({"n": FAKE_EMAIL, "v": version}).encode(),
            "b.json": json.dumps({"payload_hash": "ab" * 32}).encode(),
            "clean.json": b'{"ok": true}',
        }
    )


@pytest.fixture
def mirror(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _write_file(work, "data/exports/x.zip", _archive(1))
    _write_file(work, "cache/y", f"page {FAKE_EMAIL} {FAKE_PHONE} {SYNTHETIC_TERM}")
    _write_file(work, ".prefect/z", f"log {FAKE_EMAIL}")
    _write_file(work, "src/code.py", f'EXAMPLE = "{FAKE_EMAIL}"\n')
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "first")
    _git(work, "tag", "v1")
    _write_file(work, "data/exports/x.zip", _archive(2))
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "second")
    _git(work, "checkout", "-q", "-b", "other")
    _write_file(work, "cache/y", f"other page {FAKE_PHONE}")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "other")
    _git(work, "checkout", "-q", "main")
    _git(work, "update-ref", "refs/pull/1/head", _git(work, "rev-parse", "other"))
    path = tmp_path / "mirror.git"
    subprocess.run(
        ["git", "clone", "-q", "--mirror", f"file://{work}", str(path)],
        check=True,
        env=GIT_ENV,
    )
    return path


def _run(*args):
    return subprocess.run(
        [str(FILTER_REPO_PYTHON), str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        env=GIT_ENV,
    )


def _refs(repo):
    return _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")


def _blob_at(repo, ref, path):
    return _git(repo, "rev-parse", f"{ref}:{path}")


def _zip_text(repo, ref):
    data = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:data/exports/x.zip"],
        capture_output=True,
        env=GIT_ENV,
    ).stdout
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return b"".join(zf.read(n) for n in zf.namelist()).decode()


@needs_filter_repo
def test_plan_writes_nothing_and_prints_counts_only(mirror):
    before = (_refs(mirror), sorted(p.name for p in mirror.iterdir()))

    result = _run("plan", "--repo", mirror)

    assert result.returncode == 0, result.stderr
    assert (_refs(mirror), sorted(p.name for p in mirror.iterdir())) == before
    assert "data/exports/*.zip" in result.stdout
    assert "refs/pull/1/head" in result.stdout
    for plain in (FAKE_EMAIL, FAKE_PHONE, SYNTHETIC_TERM):
        assert plain not in result.stdout + result.stderr


@needs_filter_repo
def test_rewrite_refuses_a_repository_that_is_not_a_mirror(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _write_file(work, "cache/y", FAKE_EMAIL)
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "x")
    before = _refs(work)

    result = _run("rewrite", "--repo", work)

    assert result.returncode != 0
    assert _refs(work) == before
    assert (work / "cache/y").read_text() == FAKE_EMAIL


@needs_filter_repo
def test_rewrite_refuses_a_repository_with_push_remotes(mirror):
    _git(mirror, "config", "remote.origin.pushurl", "file:///nowhere.git")
    before = _refs(mirror)

    result = _run("rewrite", "--repo", mirror)

    assert result.returncode != 0
    assert _refs(mirror) == before


@needs_filter_repo
def test_rewrite_cleans_targets_and_leaves_other_blobs(mirror):
    code_before = _blob_at(mirror, "main", "src/code.py")
    clean_before = _blob_at(mirror, "other", "src/code.py")

    result = _run("rewrite", "--repo", mirror)

    assert result.returncode == 0, result.stderr
    assert "refs/pull" not in _refs(mirror)
    assert _blob_at(mirror, "main", "src/code.py") == code_before
    assert _blob_at(mirror, "other", "src/code.py") == clean_before
    for ref in ("main", "v1"):
        text = _zip_text(mirror, ref)
        assert FAKE_EMAIL not in text
        assert "redacted@anon.lgpd" in text
        assert "ab" * 32 not in text  # hashes are blanked by default
    cache = _git(mirror, "show", "main:cache/y")
    assert FAKE_EMAIL not in cache and FAKE_PHONE not in cache
    assert FAKE_EMAIL not in _git(mirror, "show", "main:.prefect/z")
    for plain in (FAKE_EMAIL, FAKE_PHONE):
        assert plain not in result.stdout + result.stderr


@needs_filter_repo
def test_rewrite_keeps_hashes_with_the_flag(mirror):
    result = _run("rewrite", "--repo", mirror, "--no-redact-hashes")

    assert result.returncode == 0, result.stderr
    assert "ab" * 32 in _zip_text(mirror, "main")


@needs_filter_repo
def test_two_independent_runs_give_the_same_commits(mirror, tmp_path):
    first, second = tmp_path / "first.git", tmp_path / "second.git"
    shutil.copytree(mirror, first)
    shutil.copytree(mirror, second)

    assert _run("rewrite", "--repo", first).returncode == 0
    assert _run("rewrite", "--repo", second).returncode == 0

    assert _refs(first) == _refs(second)


@needs_filter_repo
def test_verify_passes_after_rewrite_and_fails_on_a_planted_value(mirror, tmp_path):
    assert _run("rewrite", "--repo", mirror).returncode == 0

    clean = _run("verify", "--repo", mirror)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", str(mirror), str(other)], check=True, env=GIT_ENV
    )
    _write_file(other, "cache/planted", f"again {FAKE_EMAIL}")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "plant")
    _git(other, "push", "-q", "origin", "HEAD:refs/heads/planted")

    dirty = _run("verify", "--repo", mirror)

    assert dirty.returncode == 1
    assert "cache/*" in dirty.stdout
    assert FAKE_EMAIL not in dirty.stdout + dirty.stderr


@needs_filter_repo
def test_extra_terms_file_adds_literal_terms(mirror, tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text(SYNTHETIC_TERM + "\n", encoding="utf-8")

    without = _run("verify", "--repo", mirror, "--terms-file", terms)
    assert without.returncode == 1  # the term is still in the history

    rewrite = _run("rewrite", "--repo", mirror, "--extra-terms-file", terms)
    assert rewrite.returncode == 0, rewrite.stderr

    assert SYNTHETIC_TERM not in _git(mirror, "show", "main:cache/y")
    after = _run("verify", "--repo", mirror, "--terms-file", terms)
    assert after.returncode == 0, after.stdout
    assert SYNTHETIC_TERM not in rewrite.stdout + after.stdout


@needs_filter_repo
def test_a_second_rewrite_changes_nothing(mirror):
    assert _run("rewrite", "--repo", mirror).returncode == 0
    refs = _refs(mirror)

    second = _run("rewrite", "--repo", mirror)

    assert second.returncode == 0, second.stderr
    assert _refs(mirror) == refs
