"""Spec 020 (FR-023b, SC-002): passes 2 and 3 of ingest_lattes_projects over
the same CVs leave every table identical.

Runs the real phase three times in subprocesses on a temporary database, with
two CVs copied from the local data/lattes_json/. Skipped when they are absent
(the curricula are not versioned).
"""

import glob
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# CVs whose name scriptLattes could not read are left out: they all resolve to
# one "[Nome-nao-identificado]" person and overwrite each other on every run, a
# known data defect outside this test (see the spec 020 validation report).
CVS = sorted(
    p
    for p in glob.glob(os.path.join(REPO, "data", "lattes_json", "*.json"))
    if "Nome-nao-identificado" not in os.path.basename(p)
)
pytestmark = pytest.mark.skipif(len(CVS) < 2, reason="no local Lattes JSON")

# Ignored: the run row itself, and Prefect bookkeeping.
SKIP_TABLES = {"ingestion_runs", "sqlite_sequence"}


def _env(db):
    env = dict(os.environ)
    env.update(
        DATABASE_URL=f"sqlite:///{db}",
        STORAGE_TYPE="db",
        PYTHONPATH=REPO,
        HORIZON_TELEGRAM_BOT_TOKEN="",
        HORIZON_TELEGRAM_CHAT_ID="",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
        HORIZON_QUIET_PREFECT="1",
        PREFECT_LOGGING_TO_API_ENABLED="false",
    )
    return env


def _dump(db):
    con = sqlite3.connect(db)
    tables = [
        r[0]
        for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if r[0] not in SKIP_TABLES
    ]
    out = {t: sorted(map(repr, con.execute(_select(con, t)))) for t in tables}
    con.close()
    return out


def _select(con, table):
    # Spec 021: last_seen_at is the listing date, set by every run that sees
    # a document; it is not data written by processing.
    columns = [
        f'"{r[1]}"'
        for r in con.execute(f'PRAGMA table_info("{table}")')
        if not (table == "source_document_states" and r[1] == "last_seen_at")
    ]
    return f'SELECT {", ".join(columns)} FROM "{table}"'


def test_second_and_third_passes_are_identical(tmp_path):
    work = tmp_path / "work"
    (work / "data" / "lattes_json").mkdir(parents=True)
    # Two small CVs keep the test under a couple of minutes.
    for cv in sorted(CVS, key=os.path.getsize)[:2]:
        shutil.copy(cv, work / "data" / "lattes_json")
    db = tmp_path / "rerun.db"
    env = _env(db)
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=work,
        env=env,
        check=True,
        capture_output=True,
    )
    dumps = []
    for _ in range(3):
        subprocess.run(
            [sys.executable, os.path.join(REPO, "app.py"), "ingest_lattes_projects"],
            cwd=work,
            env=env,
            check=True,
            capture_output=True,
        )
        dumps.append(_dump(db))
    changed = {
        t: sorted(set(dumps[2].get(t, [])) ^ set(dumps[1][t]))[:3]
        for t in dumps[1]
        if dumps[1][t] != dumps[2].get(t)
    }
    assert changed == {}, f"tables changed between passes 2 and 3: {changed}"
    # The first rerun writes no false change logs either (this input has no
    # name that only resolves differently on a fuller database).
    assert dumps[0]["entity_change_logs"] == dumps[1]["entity_change_logs"]
    assert dumps[0]["source_records"] == dumps[1]["source_records"]
