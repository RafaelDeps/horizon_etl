"""Spec 021, US1: on a persistent database the SigPesq loaders skip unchanged
report rows and the CNPq sync skips unchanged group pages (FR-004).

Runs the real loaders in subprocesses on a temporary database, with the first
rows of the local SigPesq reports and the CNPq pages captured in the local
database (skipped when they are absent: neither is versioned).
"""

import glob
import json
import os
import re
import sqlite3
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "data", "raw", "sigpesq")
LOCAL_DB = os.path.join(REPO, "db", "horizon.db")


def _first(pattern):
    found = sorted(glob.glob(os.path.join(RAW, pattern), recursive=True))
    return found[0] if found else None


REPORTS = {
    "research_group": _first("research_group/*.xlsx"),
    "research_projects": _first("research_projects/*.xlsx"),
    "advisorships": _first("advisorships/**/*.xlsx"),
}
pytestmark = pytest.mark.skipif(
    not all(REPORTS.values()) or not os.path.exists(LOCAL_DB),
    reason="no local SigPesq reports or database",
)

SUMMARY = re.compile(r"documents (\w+): processed=(\d+) skipped=(\d+) failed=(\d+)")
SKIP_TABLES = {"ingestion_runs", "sqlite_sequence"}

SIGPESQ = """
import app  # LGPD hooks and SQLite settings, as the weekly phase
from prefect import flow
from src.flows.sigpesq.advisorships import persist_advisorships
from src.flows.sigpesq.groups import persist_research_groups
from src.flows.sigpesq.projects import persist_projects

@flow
def replay():
    persist_research_groups()
    persist_projects()
    persist_advisorships()

replay()
"""

CNPQ = """
import json, sys
import app
from src.adapters.sources import cnpq_crawler
from src.flows.cnpq import groups

payloads = json.load(open(sys.argv[1]))
cnpq_crawler.CnpqCrawlerAdapter.get_group_data = lambda self, url: payloads.get(url)
groups._SLEEP = lambda *_a, **_k: None
groups.sync_cnpq_groups_flow()
"""


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


def _run(work, db, script, *args):
    path = work / "scenario.py"
    path.write_text(script)
    result = subprocess.run(
        [sys.executable, str(path), *args],
        cwd=work,
        env=_env(db),
        capture_output=True,
        text=True,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out[-3000:]
    return {s: (int(p), int(k), int(f)) for s, p, k, f in SUMMARY.findall(out)}


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
    # last_seen_at is the listing date: every run that sees a document sets it.
    columns = [
        f'"{r[1]}"'
        for r in con.execute(f'PRAGMA table_info("{table}")')
        if not (
            table == "source_document_states"
            and r[1] in ("last_seen_at", "downloaded_at")  # dates of reading, spec 023
        )
    ]
    return f'SELECT {", ".join(columns)} FROM "{table}"'


def _cut(report, target, rows):
    import pandas as pd

    os.makedirs(os.path.dirname(target), exist_ok=True)
    pd.read_excel(report).head(rows).to_excel(target, index=False)


def _payloads(tmp_path):
    """CNPq pages captured in the local database (read-only)."""
    con = sqlite3.connect(f"file:{LOCAL_DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT source_file, raw_payload_json FROM source_records "
        "WHERE source_entity_type = 'cnpq_group_payload' ORDER BY id"
    ).fetchall()
    con.close()
    payloads = {url: json.loads(raw) for url, raw in rows}
    path = tmp_path / "payloads.json"
    path.write_text(json.dumps(payloads, ensure_ascii=False))
    return path


def test_unchanged_rows_and_pages_are_skipped_and_write_nothing(tmp_path):
    work = tmp_path / "work"
    raw = work / "data" / "raw" / "sigpesq"
    _cut(REPORTS["research_group"], str(raw / "research_group" / "r.xlsx"), 8)
    _cut(REPORTS["research_projects"], str(raw / "research_projects" / "r.xlsx"), 5)
    _cut(REPORTS["advisorships"], str(raw / "advisorships" / "2026" / "r.xlsx"), 5)
    db = tmp_path / "inc.db"
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=work,
        env=_env(db),
        check=True,
        capture_output=True,
    )
    payloads = _payloads(tmp_path)

    first = _run(work, db, SIGPESQ)
    cnpq_first = _run(work, db, CNPQ, str(payloads))
    for source in ("sigpesq_group", "sigpesq_project", "sigpesq_advisorship"):
        processed, skipped, failed = first[source]
        assert processed > 0 and skipped == 0, (source, first[source])
    groups_processed = cnpq_first["cnpq_group"][0]
    assert groups_processed > 0, cnpq_first

    before = _dump(db)
    second = _run(work, db, SIGPESQ)
    cnpq_second = _run(work, db, CNPQ, str(payloads))
    for source in ("sigpesq_group", "sigpesq_project", "sigpesq_advisorship"):
        assert second[source][0] == 0, (source, second[source])
        assert second[source][1] == first[source][0] + first[source][1]
    assert cnpq_second["cnpq_group"][0] == 0
    assert cnpq_second["cnpq_group"][1] == groups_processed
    after = _dump(db)
    assert [t for t in before if before[t] != after.get(t)] == []


# --------------------------------------------------------------------------
# US3: a failed page or row never deletes or changes stored data (FR-008)
# --------------------------------------------------------------------------

# The second project row raises inside _process_row: only that row's
# document fails, and it is rolled back whole.
FLAKY_SIGPESQ = SIGPESQ.replace(
    "@flow",
    """from src.core.logic.project_loader import ProjectLoader

calls = {"n": 0}
original = ProjectLoader._process_row

def flaky(self, row_dict, *args, **kwargs):
    calls["n"] += 1
    if calls["n"] == 2:
        raise RuntimeError("injected failure")
    return original(self, row_dict, *args, **kwargs)

ProjectLoader._process_row = flaky

@flow""",
    1,
)


def _failures(db, source_system):
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT document_key, content_hash, last_failure FROM "
        "source_document_states WHERE source_system = ? AND last_failure IS NOT NULL",
        (source_system,),
    ).fetchall()
    con.close()
    return rows


def test_a_failed_row_or_page_is_rolled_back_and_retried(tmp_path, monkeypatch):
    work = tmp_path / "work"
    raw = work / "data" / "raw" / "sigpesq"
    _cut(REPORTS["research_group"], str(raw / "research_group" / "r.xlsx"), 8)
    _cut(REPORTS["research_projects"], str(raw / "research_projects" / "r.xlsx"), 5)
    _cut(REPORTS["advisorships"], str(raw / "advisorships" / "2026" / "r.xlsx"), 5)
    db = tmp_path / "inc.db"
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=work,
        env=_env(db),
        check=True,
        capture_output=True,
    )

    first = _run(work, db, FLAKY_SIGPESQ)
    assert first["sigpesq_project"][2] == 1, first
    failed = _failures(db, "sigpesq_project")
    assert [(f[1], f[2]) for f in failed] == [(None, "partial")]
    payloads = _payloads(tmp_path)
    cnpq_first = _run(work, db, CNPQ, str(payloads))
    assert cnpq_first["cnpq_group"][0] > 0

    # The failed row is processed on the next run; nothing else is.
    second = _run(work, db, SIGPESQ)
    assert second["sigpesq_project"][:1] == (1,), second
    assert _failures(db, "sigpesq_project") == []

    # A CNPq page that comes back empty: the group keeps its members and
    # research lines and stays active.
    data = json.loads(payloads.read_text())
    con = sqlite3.connect(db)
    processed = {
        k
        for (k,) in con.execute(
            "SELECT document_key FROM source_document_states "
            "WHERE source_system = 'cnpq_group' AND content_hash IS NOT NULL"
        )
    }
    con.close()
    ids = {k.split(":", 1)[-1] for k in processed}  # "cnpq:<group id>"
    url = next(u for u in data if any(i in u for i in ids))
    data[url] = None
    # Spec 023: a stored copy would be used; without one it is a failed download.
    os.remove(work / "data" / "raw" / "cnpq" / f"{url.rsplit('/', 1)[-1]}.json")
    monkeypatch.setenv("HORIZON_FULL_REFRESH", "1")  # the group is due now
    payloads.write_text(json.dumps(data, ensure_ascii=False))
    before = _dump(db)
    cnpq_second = _run(work, db, CNPQ, str(payloads))
    assert cnpq_second["cnpq_group"][2] == 1, cnpq_second
    after = _dump(db)
    assert [t for t in before if before[t] != after.get(t)] in (
        [],
        ["source_document_states"],
    )
    reasons = [f[2] for f in _failures(db, "cnpq_group")]
    assert reasons == ["download"]


# --------------------------------------------------------------------------
# US4: a group gone from the SigPesq report stays, marked inactive (FR-009)
# --------------------------------------------------------------------------

CNPQ_CAMPUS = CNPQ.replace(
    "groups.sync_cnpq_groups_flow()", "groups.sync_cnpq_groups_flow(campus_name='a')"
)


def _status(db, source_system):
    con = sqlite3.connect(db)
    rows = dict(
        con.execute(
            "SELECT document_key, status FROM source_document_states "
            "WHERE source_system = ?",
            (source_system,),
        ).fetchall()
    )
    con.close()
    return rows


def test_a_group_gone_from_the_report_becomes_inactive_and_comes_back(
    tmp_path, monkeypatch
):
    import pandas as pd

    work = tmp_path / "work"
    raw = work / "data" / "raw" / "sigpesq"
    report = raw / "research_group" / "r.xlsx"
    _cut(REPORTS["research_group"], str(report), 8)
    _cut(REPORTS["research_projects"], str(raw / "research_projects" / "r.xlsx"), 2)
    _cut(REPORTS["advisorships"], str(raw / "advisorships" / "2026" / "r.xlsx"), 2)
    full = pd.read_excel(report)
    db = tmp_path / "inc.db"
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=work,
        env=_env(db),
        check=True,
        capture_output=True,
    )
    payloads = _payloads(tmp_path)
    # As in a weekly: the CNPq listing counts as complete only after the
    # SigPesq report of the same weekly.
    monkeypatch.setenv("HORIZON_WEEKLY_STARTED_AT", "2000-01-01T00:00:00Z")
    _run(work, db, SIGPESQ)
    _run(work, db, CNPQ, str(payloads))
    groups, cnpq = _status(db, "sigpesq_group"), _status(db, "cnpq_group")
    assert groups and set(groups.values()) == {"active"}
    assert cnpq and set(cnpq.values()) == {"active"}

    # Drop the rows of one group that has a CNPq page.
    def cnpq_key(row):
        url = str(row.get("Column1") or "")  # the mirror URL column
        digits = "".join(c for c in url.rsplit("/", 1)[-1] if c.isdigit())
        return f"cnpq:{digits}" if len(digits) == 16 else None

    with_page = [i for i, row in full.iterrows() if cnpq_key(row) in cnpq]
    if not with_page:
        pytest.skip("no group of the cut report has a captured CNPq page")
    dropped = full.loc[with_page[0]]
    full.drop(index=[with_page[0]]).to_excel(report, index=False)
    before = _dump(db)
    _run(work, db, SIGPESQ)
    _run(work, db, CNPQ, str(payloads))
    groups_now, cnpq_now = _status(db, "sigpesq_group"), _status(db, "cnpq_group")
    assert list(groups_now.values()).count("inactive") == 1
    assert cnpq_now[cnpq_key(dropped)] == "inactive"
    after = _dump(db)
    # The group's data is kept.
    for table in ("research_groups", "team_members", "researchers"):
        if table in before:
            assert before[table] == after[table], table

    # A partial CNPq run (campus filter) changes no status.
    _run(work, db, CNPQ_CAMPUS, str(payloads))
    assert _status(db, "cnpq_group") == cnpq_now

    # Back in the report: active again.
    full.to_excel(report, index=False)
    _run(work, db, SIGPESQ)
    _run(work, db, CNPQ, str(payloads))
    assert set(_status(db, "sigpesq_group").values()) == {"active"}
    assert set(_status(db, "cnpq_group").values()) == {"active"}

    # An empty report changes no status.
    full.head(0).to_excel(report, index=False)
    statuses = _status(db, "sigpesq_group")
    _run(work, db, SIGPESQ)
    assert _status(db, "sigpesq_group") == statuses


# --------------------------------------------------------------------------
# Spec 023: with the portal down, stored CNPq pages keep every group's data
# --------------------------------------------------------------------------


def test_stored_pages_keep_the_groups_when_the_portal_is_down(tmp_path, monkeypatch):
    work = tmp_path / "work"
    raw = work / "data" / "raw" / "sigpesq"
    _cut(REPORTS["research_group"], str(raw / "research_group" / "r.xlsx"), 8)
    _cut(REPORTS["research_projects"], str(raw / "research_projects" / "r.xlsx"), 2)
    _cut(REPORTS["advisorships"], str(raw / "advisorships" / "2026" / "r.xlsx"), 2)
    db = tmp_path / "inc.db"
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=work,
        env=_env(db),
        check=True,
        capture_output=True,
    )
    payloads = _payloads(tmp_path)
    _run(work, db, SIGPESQ)
    first = _run(work, db, CNPQ, str(payloads))
    processed = first["cnpq_group"][0]
    assert processed > 0
    stored = sorted((work / "data" / "raw" / "cnpq").glob("*.json"))
    assert len(stored) == processed

    def states():
        con = sqlite3.connect(db)
        rows = dict(
            con.execute(
                "SELECT document_key, downloaded_at FROM source_document_states "
                "WHERE source_system = 'cnpq_group' AND content_hash IS NOT NULL"
            ).fetchall()
        )
        con.close()
        return rows

    dates = states()
    assert dates and all(dates.values())

    # Every fetch fails, and every group is due (full refresh).
    down = tmp_path / "down.json"
    down.write_text(json.dumps({url: None for url in json.loads(payloads.read_text())}))
    monkeypatch.setenv("HORIZON_FULL_REFRESH", "1")
    before = _dump(db)
    second = _run(work, db, CNPQ, str(down))
    assert second["cnpq_group"][2] == 0, second  # no failed document
    assert second["cnpq_group"][1] == processed  # unchanged stored pages: skipped
    after = _dump(db)
    assert [t for t in before if before[t] != after.get(t)] in (
        [],
        ["source_document_states"],
    )
    assert states() == dates  # the stored copies' dates
