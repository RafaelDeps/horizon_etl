"""Spec 029: deleting the old public artifacts and run logs. The ``gh`` calls
are replaced by a fake: no network, no real GitHub CLI, nothing deleted."""

import json
import os

import pytest

from src.scripts import purge_public_artifacts as purge

REPO = "owner/repo"


class FakeGh:
    """Answers the calls the script makes and records every one."""

    def __init__(self, artifacts, runs, bundle_in=()):
        self.artifacts = artifacts
        self.runs = runs  # run id -> {"conclusion", "head_branch", "created_at"}
        self.bundle_in = set(bundle_in)
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[0] == "api" and "-X" in args and "DELETE" in args:
            return ""
        if args[0] == "api" and args[-1].endswith("/actions/artifacts?per_page=100"):
            return json.dumps({"artifacts": self.artifacts})
        if args[0] == "api" and "/actions/runs/" in args[-1]:
            run_id = int(args[-1].rsplit("/", 1)[-1])
            return json.dumps(self.runs[run_id])
        if args[:2] == ["run", "download"]:
            run_id = int(args[2])
            dest = args[args.index("-D") + 1]
            if run_id in self.bundle_in:
                with open(os.path.join(dest, "weekly_state.bundle"), "wb") as fh:
                    fh.write(b"HZSTATE1")
            return ""
        raise AssertionError(f"unexpected gh call: {args}")

    def deletions(self):
        return [c for c in self.calls if "DELETE" in c]


def _artifact(artifact_id, run_id, branch, created):
    return {
        "id": artifact_id,
        "name": "weekly-etl-artifacts",
        "expired": False,
        "created_at": created,
        "workflow_run": {"id": run_id, "head_branch": branch},
    }


@pytest.fixture
def world():
    artifacts = [
        _artifact(1, 10, "main", "2026-10-01T02:00:00Z"),
        _artifact(2, 11, "main", "2026-10-08T02:00:00Z"),
        _artifact(3, 12, "main", "2026-11-05T02:00:00Z"),  # the clean run's own
        _artifact(4, 13, "main", "2026-11-12T02:00:00Z"),  # newer than the clean run
        _artifact(5, 20, "feature-a", "2026-10-15T02:00:00Z"),
        _artifact(6, 21, "feature-a", "2026-10-16T02:00:00Z"),
    ]
    runs = {
        12: {
            "conclusion": "success",
            "head_branch": "main",
            "created_at": "2026-11-05T01:59:00Z",
        },
        30: {
            "conclusion": "failure",
            "head_branch": "main",
            "created_at": "2026-11-06T01:59:00Z",
        },
    }
    return FakeGh(artifacts, runs, bundle_in=[12])


def _main(gh, *args):
    return purge.main(["--repo", REPO, *args], gh=gh)


def test_dry_run_lists_and_deletes_nothing(world, capsys):
    code = _main(world, "--first-clean-run", "main=12")

    assert code == 0
    assert world.deletions() == []
    out = capsys.readouterr().out
    assert "dry run" in out.lower()
    assert "main" in out


def test_a_run_that_did_not_succeed_is_refused(world):
    code = _main(world, "--first-clean-run", "main=30", "--execute")

    assert code != 0
    assert world.deletions() == []


def test_a_run_whose_artifact_has_no_bundle_is_refused(world):
    world.runs[13] = {
        "conclusion": "success",
        "head_branch": "main",
        "created_at": "2026-11-12T01:59:00Z",
    }

    code = _main(world, "--first-clean-run", "main=13", "--execute")

    assert code != 0
    assert world.deletions() == []


def test_a_run_of_another_branch_is_refused(world):
    code = _main(world, "--first-clean-run", "feature-a=12", "--execute")

    assert code != 0
    assert world.deletions() == []


def test_only_artifacts_older_than_the_branch_clean_run_are_deleted(world):
    code = _main(world, "--first-clean-run", "main=12", "--execute")

    assert code == 0
    deleted = sorted(c[-1] for c in world.deletions())
    assert deleted == [
        f"repos/{REPO}/actions/artifacts/1",
        f"repos/{REPO}/actions/artifacts/2",
    ]


def test_branches_without_a_clean_run_are_kept_unless_included(world):
    _main(world, "--first-clean-run", "main=12", "--execute")

    assert not any(
        "artifacts/5" in c[-1] or "artifacts/6" in c[-1] for c in world.deletions()
    )


def test_include_branches_without_clean_run_deletes_all_their_artifacts(world):
    code = _main(
        world,
        "--first-clean-run",
        "main=12",
        "--execute",
        "--include-branches-without-clean-run",
    )

    assert code == 0
    deleted = sorted(c[-1].rsplit("/", 1)[-1] for c in world.deletions())
    assert deleted == ["1", "2", "5", "6"]


def test_logs_are_deleted_only_with_the_flag_and_execute(world):
    _main(world, "--first-clean-run", "main=12", "--execute")
    assert not any("logs" in c[-1] for c in world.deletions())

    _main(world, "--first-clean-run", "main=12", "--logs")  # dry run
    assert not any("logs" in c[-1] for c in world.deletions())

    _main(world, "--first-clean-run", "main=12", "--execute", "--logs")
    logs = sorted(c[-1] for c in world.deletions() if c[-1].endswith("/logs"))
    assert logs == [
        f"repos/{REPO}/actions/runs/10/logs",
        f"repos/{REPO}/actions/runs/11/logs",
    ]


def test_counts_are_printed_and_no_artifact_content(world, capsys):
    _main(
        world,
        "--first-clean-run",
        "main=12",
        "--execute",
        "--include-branches-without-clean-run",
    )

    out = capsys.readouterr().out
    assert "deleted 4 artifact(s)" in out
    assert "HZSTATE1" not in out
