"""Restores the previous weekly run's database, raw downloads and Lattes cache
(spec 022).

Every GitHub Actions weekly starts on an empty runner. The workflow uploads
``db/horizon.db``, ``data/`` and ``cache/`` as the ``weekly-etl-artifacts``
artifact at the end of each run; this module puts back, before the phases, the
three items the next run reads: ``db/horizon.db``, ``data/raw`` and ``cache/``,
from the newest successful run of the same branch whose artifact has not
expired (research R2). ``make weekly-flows`` then works as on a local kept
database: ``make db-ensure`` migrates it, or creates it when none was placed.

Nothing here can fail the run: a missing, expired, broken or unreadable
artifact ends as "rebuilt", with its reason, and exit 0 (FR-003). The outcome
goes to the log, to ``data/reports/restore_outcome.json`` and, in CI, to the
job summary (contracts/restore-cli.md).

Usage:
    PYTHONPATH=. python -m src.scripts.restore_weekly_artifact --github
    PYTHONPATH=. python -m src.scripts.restore_weekly_artifact --from-dir PATH --target DIR
    PYTHONPATH=. python -m src.scripts.restore_weekly_artifact --from-zip PATH --target DIR
    PYTHONPATH=. python -m src.scripts.restore_weekly_artifact --disabled
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger

ARTIFACT = "weekly-etl-artifacts"
WORKFLOW = "weekly-etl.yml"
CANDIDATES = 20  # about five months of weeklies, more than the 90-day retention
DATABASE = os.path.join("db", "horizon.db")
FOLDERS = (os.path.join("data", "raw"), "cache")
OUTCOME_FILE = os.path.join("data", "reports", "restore_outcome.json")
REQUIRED_TABLES = ("persons", "horizon_meta")

RESTORED = "restored"
REBUILT = "rebuilt"


class RestoreError(Exception):
    """A reason to rebuild instead of restoring (data-model.md)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Outcome:
    outcome: str
    reason: Optional[str] = None
    source_run: Optional[dict] = None
    restored: dict = field(
        default_factory=lambda: {"db_bytes": 0, "data_raw_bytes": 0, "cache_bytes": 0}
    )
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )


# ----------------------------------------------------------------------------
# Finding and downloading the run (CI)
# ----------------------------------------------------------------------------


def _gh(args: List[str], timeout: int) -> str:
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise RestoreError("download failed: the gh CLI is not installed")
    except subprocess.TimeoutExpired:
        raise RestoreError(f"download failed: gh {args[0]} timed out")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise RestoreError(
            f"download failed: gh {args[0]} exited {result.returncode}"
            + (f" ({detail[-1]})" if detail else "")
        )
    return result.stdout


def find_run(repo: str, branch: str) -> dict:
    """The newest successful weekly run of the branch whose artifact has not
    expired. Failed, cancelled and running runs are never listed (FR-002)."""
    runs = json.loads(
        _gh(
            [
                "run",
                "list",
                "--repo",
                repo,
                "--workflow",
                WORKFLOW,
                "--branch",
                branch,
                "--status",
                "success",
                "--limit",
                str(CANDIDATES),
                "--json",
                "databaseId,createdAt,headSha,event",
            ],
            timeout=120,
        )
        or "[]"
    )
    if not runs:
        raise RestoreError("no successful run")
    runs.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
    for run in runs:
        payload = json.loads(
            _gh(
                ["api", f"repos/{repo}/actions/runs/{run['databaseId']}/artifacts"],
                timeout=120,
            )
            or "{}"
        )
        for artifact in payload.get("artifacts", []):
            if artifact.get("name") == ARTIFACT and not artifact.get("expired"):
                return _run_record(run)
    raise RestoreError("artifact expired")


def _run_record(run: dict) -> dict:
    return {
        "id": run.get("databaseId"),
        "created_at": run.get("createdAt"),
        "head_sha": run.get("headSha"),
        "event": run.get("event"),
    }


def download(repo: str, run: dict, dest: str) -> None:
    _gh(
        ["run", "download", str(run["id"]), "--repo", repo, "-n", ARTIFACT, "-D", dest],
        timeout=1800,
    )


# ----------------------------------------------------------------------------
# Preparing, checking and placing the files
# ----------------------------------------------------------------------------


def unzip_compressed(raw_dir: str) -> int:
    """Artifacts made before spec 022 may hold a large raw file ``X`` as
    ``X.zip`` (the workflow's compression step). A zip whose only member is
    ``X`` is put back as ``X``; any other zip is a real file and stays."""
    restored = 0
    if not os.path.isdir(raw_dir):
        return restored
    for folder, _dirs, files in os.walk(raw_dir):
        for name in files:
            if not name.endswith(".zip"):
                continue
            path = os.path.join(folder, name)
            original = name[: -len(".zip")]
            try:
                with zipfile.ZipFile(path) as archive:
                    members = archive.namelist()
                    if members != [original]:
                        continue
                    archive.extract(original, folder)
            except zipfile.BadZipFile:
                continue
            os.remove(path)
            restored += 1
    return restored


def check_database(path: str) -> None:
    """Research R4: the file exists, ``PRAGMA quick_check`` is ``ok`` and the
    tables every weekly needs are there."""
    if not os.path.isfile(path):
        raise RestoreError("database missing")
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = con.execute("PRAGMA quick_check").fetchone()
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise RestoreError(f"database check failed: {exc}")
    if not result or result[0] != "ok":
        raise RestoreError(f"database check failed: quick_check {result}")
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        raise RestoreError(f"database check failed: no table {', '.join(missing)}")


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(folder, name))
    return total


def _replace(source: str, destination: str) -> None:
    if os.path.isdir(destination) and not os.path.islink(destination):
        shutil.rmtree(destination)
    elif os.path.exists(destination):
        os.remove(destination)
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    shutil.move(source, destination)


def place(source_root: str, target: str, run: Optional[dict]) -> Outcome:
    """Moves the restored items into the target (contract "Behaviour" 3-5).
    ``data/raw`` and ``cache/`` are placed even when the database is not: a
    bad database does not make the raw downloads wrong."""
    unzip_compressed(os.path.join(source_root, "data", "raw"))
    database_error = None
    try:
        check_database(os.path.join(source_root, DATABASE))
    except RestoreError as exc:
        database_error = exc.reason

    sizes = {"db_bytes": 0, "data_raw_bytes": 0, "cache_bytes": 0}
    for folder, key in zip(FOLDERS, ("data_raw_bytes", "cache_bytes")):
        source = os.path.join(source_root, folder)
        if os.path.isdir(source):
            sizes[key] = _size(source)
            _replace(source, os.path.join(target, folder))
    if database_error is None:
        destination = os.path.join(target, DATABASE)
        for suffix in ("-wal", "-shm"):
            # A stale log next to another file could corrupt it (spec 018).
            if os.path.exists(destination + suffix):
                os.remove(destination + suffix)
        sizes["db_bytes"] = _size(os.path.join(source_root, DATABASE))
        _replace(os.path.join(source_root, DATABASE), destination)
        return Outcome(RESTORED, None, run, sizes)
    return Outcome(REBUILT, database_error, run, sizes)


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------


def _mb(size: int) -> str:
    return f"{size / 1048576:.0f} MB"


def _run_label(run: Optional[dict]) -> str:
    if not run:
        return ""
    date = (run.get("created_at") or "")[:10]
    sha = (run.get("head_sha") or "")[:7]
    return f"run {run.get('id')} ({date}, {sha})"


def log_line(outcome: Outcome) -> str:
    sizes = outcome.restored
    if outcome.outcome == RESTORED:
        return (
            f"restore: restored db/horizon.db ({_mb(sizes['db_bytes'])}), "
            f"data/raw ({_mb(sizes['data_raw_bytes'])}), "
            f"cache ({_mb(sizes['cache_bytes'])}) from "
            + (_run_label(outcome.source_run) or "the given artifact")
        )
    tried = _run_label(outcome.source_run)
    return f"restore: rebuilt — {outcome.reason}" + (f" ({tried})" if tried else "")


def summary_block(outcome: Outcome, repo: Optional[str], server: str) -> str:
    sizes = outcome.restored
    if outcome.outcome == RESTORED:
        run = outcome.source_run or {}
        run_id = run.get("id")
        link = (
            f"[{run_id}]({server}/{repo}/actions/runs/{run_id})"
            if repo
            else str(run_id)
        )
        return (
            "### Database\n"
            f"Restored from run {link} of {(run.get('created_at') or '')[:10]} "
            f"(`{(run.get('head_sha') or '')[:7]}`): "
            f"database {_mb(sizes['db_bytes'])}, "
            f"data/raw {_mb(sizes['data_raw_bytes'])}, "
            f"cache {_mb(sizes['cache_bytes'])}.\n"
        )
    return f"### Database\nRebuilt from scratch: {outcome.reason}.\n"


def report(
    outcome: Outcome,
    outcome_path: str,
    summary_path: Optional[str],
    repo: Optional[str] = None,
    server: str = "https://github.com",
) -> None:
    logger.info(log_line(outcome))
    os.makedirs(os.path.dirname(outcome_path) or ".", exist_ok=True)
    with open(outcome_path, "w", encoding="utf-8") as f:
        json.dump(asdict(outcome), f, indent=2)
        f.write("\n")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(summary_block(outcome, repo, server))


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


def restore(args: argparse.Namespace) -> Outcome:
    target = os.path.abspath(args.target)
    if args.disabled:
        return Outcome(REBUILT, "restore disabled")
    os.makedirs(target, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".restore-", dir=target)
    run = None
    try:
        if args.github:
            run = find_run(args.repo, args.branch)
            download(args.repo, run, work)
        elif args.from_zip:
            try:
                with zipfile.ZipFile(args.from_zip) as archive:
                    archive.extractall(work)
            except (OSError, zipfile.BadZipFile) as exc:
                raise RestoreError(f"download failed: {exc}")
        else:
            # A copy: the simulation's artifact folder must stay as it was.
            shutil.copytree(args.from_dir, work, dirs_exist_ok=True)
        try:
            return place(work, target, run)
        except OSError as exc:
            raise RestoreError(f"restore failed: {exc}")
    except RestoreError as exc:
        return Outcome(REBUILT, exc.reason, run)
    except (OSError, ValueError) as exc:  # unreadable gh output or folders
        return Outcome(REBUILT, f"download failed: {exc}", run)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--github", action="store_true")
    mode.add_argument("--from-dir")
    mode.add_argument("--from-zip")
    mode.add_argument("--disabled", action="store_true")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME"))
    parser.add_argument("--target", default=".")
    parser.add_argument("--summary", default=os.getenv("GITHUB_STEP_SUMMARY"))
    parser.add_argument("--outcome")
    args = parser.parse_args(argv)
    if args.github and not (args.repo and args.branch):
        parser.error(
            "--github needs --repo and --branch (or GITHUB_REPOSITORY and GITHUB_REF_NAME)"
        )
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    outcome = restore(args)
    report(
        outcome,
        args.outcome or os.path.join(os.path.abspath(args.target), OUTCOME_FILE),
        args.summary,
        repo=args.repo,
        server=os.getenv("GITHUB_SERVER_URL", "https://github.com"),
    )
    return 0  # restored or rebuilt: never fails the run (FR-003)


if __name__ == "__main__":
    sys.exit(main())
