"""Deletes the old public weekly artifacts and run logs (spec 029).

NOT run by the feature: the maintainer runs it by hand after the first clean
run, by contracts/history-purge.md. A dry run is the default; nothing is
deleted without ``--execute``. Deleting logs cannot be undone.

    python -m src.scripts.purge_public_artifacts --repo OWNER/REPO \\
        --first-clean-run main=RUN_ID
    python -m src.scripts.purge_public_artifacts --repo OWNER/REPO \\
        --first-clean-run main=RUN_ID --execute [--logs] \\
        [--include-branches-without-clean-run]

Per branch, artifacts older than its first clean run are deleted; the artifacts
of a clean run are never deleted. A clean run is named by the maintainer and
refused unless it succeeded, ran on that branch, and its artifact holds
``weekly_state.bundle``. Output holds counts and ids only.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Callable, Dict, List, Optional

ARTIFACT = "weekly-etl-artifacts"
BUNDLE = "weekly_state.bundle"

Gh = Callable[[List[str]], str]


class Refused(Exception):
    """A clean run that cannot be trusted; nothing is deleted."""


def run_gh(args: List[str]) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        raise RuntimeError(
            f"gh {args[0]} failed" + (f": {detail[-1]}" if detail else "")
        )
    return result.stdout


def _json_documents(text: str) -> list:
    """``gh api --paginate`` prints one JSON document per page."""
    decoder, position, documents = json.JSONDecoder(), 0, []
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        document, position = decoder.raw_decode(text, position)
        documents.append(document)
    return documents


def list_artifacts(gh: Gh, repo: str) -> List[dict]:
    out = gh(["api", "--paginate", f"repos/{repo}/actions/artifacts?per_page=100"])
    artifacts = []
    for page in _json_documents(out):
        artifacts.extend(page.get("artifacts", []))
    return [a for a in artifacts if a.get("name") == ARTIFACT and not a.get("expired")]


def check_clean_run(gh: Gh, repo: str, branch: str, run_id: int) -> dict:
    """The run record, or ``Refused``."""
    run = json.loads(gh(["api", f"repos/{repo}/actions/runs/{run_id}"]) or "{}")
    if run.get("conclusion") != "success":
        raise Refused(f"run {run_id} did not succeed")
    if run.get("head_branch") != branch:
        raise Refused(f"run {run_id} is not a run of branch {branch}")
    with tempfile.TemporaryDirectory(prefix="purge-check-") as folder:
        try:
            gh(
                [
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    repo,
                    "-n",
                    ARTIFACT,
                    "-D",
                    folder,
                ]
            )
        except RuntimeError as exc:
            raise Refused(f"run {run_id}: artifact not downloaded ({exc})")
        if not os.path.isfile(os.path.join(folder, BUNDLE)):
            raise Refused(f"run {run_id}: its artifact has no {BUNDLE}")
    return run


def parse_clean_runs(values: List[str]) -> Dict[str, int]:
    result = {}
    for value in values:
        branch, sep, run_id = value.rpartition("=")
        if not sep or not branch or not run_id.isdigit():
            raise Refused(f"--first-clean-run expects BRANCH=RUN_ID, got {value!r}")
        result[branch] = int(run_id)
    return result


def plan_deletions(
    artifacts: List[dict],
    clean_runs: Dict[str, dict],
    include_without_clean_run: bool,
) -> List[dict]:
    clean_ids = {run["id"] for run in clean_runs.values() if "id" in run}
    chosen = []
    for artifact in artifacts:
        run = artifact.get("workflow_run") or {}
        branch = run.get("head_branch")
        if run.get("id") in clean_ids:
            continue  # never a clean run's own artifact
        clean = clean_runs.get(branch)
        if clean is None:
            if include_without_clean_run:
                chosen.append(artifact)
        elif artifact.get("created_at", "") < clean["created_at"]:
            chosen.append(artifact)
    return chosen


def main(argv: Optional[List[str]] = None, gh: Gh = run_gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument(
        "--first-clean-run", action="append", default=[], metavar="BRANCH=RUN_ID"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--logs", action="store_true")
    parser.add_argument("--include-branches-without-clean-run", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo

    try:
        named = parse_clean_runs(args.first_clean_run)
        clean_runs = {}
        for branch, run_id in named.items():
            run = check_clean_run(gh, repo, branch, run_id)
            clean_runs[branch] = {
                "id": run_id,
                "created_at": run.get("created_at") or "",
            }
    except Refused as exc:
        print(f"refused: {exc}")
        return 2

    artifacts = list_artifacts(gh, repo)
    chosen = plan_deletions(
        artifacts, clean_runs, args.include_branches_without_clean_run
    )
    per_branch: Dict[str, int] = {}
    for artifact in chosen:
        branch = (artifact.get("workflow_run") or {}).get("head_branch") or "?"
        per_branch[branch] = per_branch.get(branch, 0) + 1

    mode = "EXECUTE" if args.execute else "dry run (nothing is deleted)"
    print(f"{repo}: {mode}")
    print(f"live artifacts: {len(artifacts)}; selected for deletion: {len(chosen)}")
    for branch in sorted(per_branch):
        print(f"  branch {branch}: {per_branch[branch]} artifact(s)")
    run_ids = sorted({(a.get("workflow_run") or {}).get("id") for a in chosen} - {None})
    if args.logs:
        print(f"run logs selected: {len(run_ids)}")
    if not args.execute:
        return 0

    deleted = 0
    for artifact in chosen:
        gh(["api", "-X", "DELETE", f"repos/{repo}/actions/artifacts/{artifact['id']}"])
        deleted += 1
    print(f"deleted {deleted} artifact(s)")
    if args.logs:
        logs = 0
        for run_id in run_ids:
            gh(["api", "-X", "DELETE", f"repos/{repo}/actions/runs/{run_id}/logs"])
            logs += 1
        print(f"deleted logs of {logs} run(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
