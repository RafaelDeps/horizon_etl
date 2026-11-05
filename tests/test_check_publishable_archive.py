"""Spec 029: the gate that keeps an archive made with another key, or by a
local run, or over the size limit, from being published."""

import json
import os
import subprocess
import zipfile

import pytest

from src.scripts import check_publishable_archive as gate

ARCHIVE = "data/exports/exports_canonical.zip"
FINGERPRINT = "0123456789abcdef"
OTHER_FINGERPRINT = "fedcba9876543210"

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Synthetic Author",
    "GIT_AUTHOR_EMAIL": "author@example.test",
    "GIT_COMMITTER_NAME": "Synthetic Author",
    "GIT_COMMITTER_EMAIL": "author@example.test",
}


def _archive(path, manifest=None, extra=b"{}"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("data.json", extra)
        if manifest is not None:
            zf.writestr("export_manifest.json", json.dumps(manifest))
    return path


def _manifest(official=True, fingerprint=FINGERPRINT):
    return {"official": official, "key_fingerprint": fingerprint}


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, env=GIT_ENV, capture_output=True
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway repository whose HEAD holds an archive with a manifest."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _archive(root / ARCHIVE, _manifest(), extra=b'{"committed": true}')
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "archive")
    monkeypatch.chdir(root)
    return root


def _check(*extra):
    return gate.main([ARCHIVE, *extra])


def test_accepts_a_good_archive(repo):
    _archive(repo / ARCHIVE, _manifest(), extra=b'{"new": true}')

    assert _check("--ref", "HEAD") == 0


def test_refuses_an_archive_without_a_manifest(repo, capsys):
    _archive(repo / ARCHIVE, None)

    assert _check("--ref", "HEAD") == 1
    assert "manifest" in capsys.readouterr().out


def test_refuses_an_archive_that_is_not_official(repo):
    _archive(repo / ARCHIVE, _manifest(official=False))

    assert _check("--ref", "HEAD") == 1


def test_refuses_an_archive_over_the_size_limit(repo, monkeypatch):
    monkeypatch.setattr(gate, "MAX_ARCHIVE_BYTES", 10)

    assert _check("--ref", "HEAD") == 1


def test_refuses_another_key_than_the_archive_at_the_ref(repo, capsys):
    _archive(repo / ARCHIVE, _manifest(fingerprint=OTHER_FINGERPRINT))

    assert _check("--ref", "HEAD") == 1
    out = capsys.readouterr().out
    assert "key" in out.lower()


def test_accepts_when_the_ref_archive_has_no_manifest(repo):
    _archive(repo / ARCHIVE, None, extra=b"old")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old archive without manifest")
    _archive(repo / ARCHIVE, _manifest(fingerprint=OTHER_FINGERPRINT), extra=b"new")

    assert _check("--ref", "HEAD") == 0


def test_accepts_when_the_ref_has_no_archive(repo):
    _git(repo, "rm", "-q", ARCHIVE)
    _git(repo, "commit", "-q", "-m", "remove")
    _archive(repo / ARCHIVE, _manifest())

    assert _check("--ref", "HEAD") == 0


def test_warn_only_restores_the_archive_and_exits_zero(repo, capsys):
    committed = (repo / ARCHIVE).read_bytes()
    _archive(repo / ARCHIVE, _manifest(official=False), extra=b'{"bad": true}')

    code = _check("--ref", "HEAD", "--warn-only")

    assert code == 0
    assert "::warning" in capsys.readouterr().out
    assert (repo / ARCHIVE).read_bytes() == committed


def test_warn_only_with_a_good_archive_changes_nothing(repo, capsys):
    _archive(repo / ARCHIVE, _manifest(), extra=b'{"new": true}')
    fresh = (repo / ARCHIVE).read_bytes()

    assert _check("--ref", "HEAD", "--warn-only") == 0
    assert (repo / ARCHIVE).read_bytes() == fresh
    assert "::warning" not in capsys.readouterr().out


def test_warn_only_removes_an_untracked_refused_archive(repo):
    _git(repo, "rm", "-q", ARCHIVE)
    _git(repo, "commit", "-q", "-m", "remove")
    _archive(repo / ARCHIVE, _manifest(official=False))

    assert _check("--ref", "HEAD", "--warn-only") == 0
    assert not (repo / ARCHIVE).exists()


def test_a_missing_archive_is_refused(repo):
    (repo / ARCHIVE).unlink()

    assert _check("--ref", "HEAD") == 1
