"""Spec 021, US1: on a persistent database the Lattes phases skip every CV
whose content and resolutions did not change, and process again only the CVs
that a new person or initiative could resolve differently (FR-004, FR-005).

Runs the real phases in subprocesses on a temporary database with three small
CVs copied from the local data/lattes_json/ (skipped when they are absent: the
curricula are not versioned).
"""

import glob
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CVS = sorted(
    p
    for p in glob.glob(os.path.join(REPO, "data", "lattes_json", "*.json"))
    if "Nome-nao-identificado" not in os.path.basename(p)
)
pytestmark = pytest.mark.skipif(len(CVS) < 3, reason="no local Lattes JSON")

SUMMARY = re.compile(r"documents (\w+): processed=(\d+) skipped=(\d+) failed=(\d+)")
# Ignored when comparing a skipped pass: the run row each phase opens.
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


def _phase(work, db, command):
    result = subprocess.run(
        [sys.executable, os.path.join(REPO, "app.py"), command],
        cwd=work,
        env=_env(db),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    found = SUMMARY.findall(result.stdout + result.stderr)
    assert found, (result.stdout + result.stderr)[-3000:]
    _, processed, skipped, failed = found[-1]
    return int(processed), int(skipped), int(failed)


def _both(work, db):
    return (
        _phase(work, db, "ingest_lattes_projects"),
        _phase(work, db, "lattes_advisorships"),
    )


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


@pytest.fixture
def populated(tmp_path):
    work = tmp_path / "work"
    (work / "data" / "lattes_json").mkdir(parents=True)
    # Three small CVs keep the test to a few minutes.
    for cv in sorted(CVS, key=os.path.getsize)[20:23]:
        shutil.copy(cv, work / "data" / "lattes_json")
    db = tmp_path / "inc.db"
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=work,
        env=_env(db),
        check=True,
        capture_output=True,
    )
    assert _both(work, db) == ((3, 0, 0), (3, 0, 0))
    return work, db


def test_unchanged_inputs_skip_every_cv_and_write_nothing(populated):
    work, db = populated
    before = _dump(db)
    assert _both(work, db) == ((0, 3, 0), (0, 3, 0))
    after = _dump(db)
    changed = [t for t in before if before[t] != after.get(t)]
    assert changed == []


def _keys(db, source_system, kind):
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT document_key, lookup_key FROM source_document_references "
        "WHERE source_system = ? AND kind = ?",
        (source_system, kind),
    ).fetchall()
    con.close()
    return rows


def _add_person(db, name):
    con = sqlite3.connect(db)
    con.execute("INSERT INTO persons (name) VALUES (?)", (name,))
    con.commit()
    con.close()


def test_a_new_person_with_a_cv_lattes_id_reprocesses_only_that_cv(populated):
    # A name resolved to a person of that very name cannot be changed by a
    # person created later (the exact match wins); a person that now carries
    # the CV's Lattes id can, so that CV is processed again.
    work, db = populated
    refs = _keys(db, "lattes_advisorships", "researcher_owner")
    if not refs:
        pytest.skip("the chosen CVs resolve no owners")
    document_key, lookup = refs[0]
    lattes_id = lookup.partition("|lattes:")[2]
    con = sqlite3.connect(db)
    cur = con.execute("INSERT INTO persons (name) VALUES ('Zzyzx Outro Nome')")
    con.execute(
        "INSERT INTO researchers (id, cnpq_url) VALUES (?, ?)",
        (cur.lastrowid, f"http://lattes.cnpq.br/{lattes_id}"),
    )
    con.commit()
    con.close()
    projects, advisorships = _both(work, db)
    assert advisorships[:2] == (1, 2)


def test_a_new_unrelated_person_reprocesses_nothing(populated):
    work, db = populated
    _add_person(db, "Zzyzx Qwertyuiop Unrelated")
    assert _both(work, db) == ((0, 3, 0), (0, 3, 0))


def test_a_new_initiative_with_a_resolved_title_reprocesses_only_that_cv(populated):
    work, db = populated
    refs = []
    for source in ("lattes_projects", "lattes_advisorships"):
        for key, lookup in _keys(db, source, "initiative"):
            title = lookup.partition("|title:")[2]
            if title:
                refs.append((source, key, title))
    if not refs:
        pytest.skip("the chosen CVs resolve no initiatives")
    _, _, title = refs[0]
    expected = {(s, k) for s, k, t in refs if t == title}
    con = sqlite3.connect(db)
    con.execute("INSERT INTO initiatives (name) VALUES (?)", (title,))
    con.commit()
    con.close()
    projects, advisorships = _both(work, db)
    by_source = {"lattes_projects": projects, "lattes_advisorships": advisorships}
    for source in by_source:
        n = len({k for s, k in expected if s == source})
        assert by_source[source][0] == n, (source, by_source[source], n)


# --------------------------------------------------------------------------
# US3: a failed CV never deletes or changes stored data (FR-008)
# --------------------------------------------------------------------------

UNIDENTIFIED = sorted(
    glob.glob(os.path.join(REPO, "data", "lattes_json", "*Nome-nao-identificado*.json"))
)

# The projects phase with the awards section of one CV raising: that CV must
# be rolled back whole, not committed without its awards.
BROKEN_AWARDS = """
import sys
import app
from src.adapters.sources.lattes_parser import LattesParser
from src.flows.lattes.projects import ingest_lattes_projects_flow

original = LattesParser.parse_awards

def broken(self, data):
    resume = (data.get("informacoes_pessoais") or {}).get("texto_resumo")
    if resume == "Resumo alterado (spec 021).":
        raise RuntimeError("injected failure in the awards section")
    return original(self, data)

LattesParser.parse_awards = broken
ingest_lattes_projects_flow()
"""


def _states(db, source_system):
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT document_key, content_hash, item_count, processed_at, "
        "last_failure FROM source_document_states WHERE source_system = ?",
        (source_system,),
    ).fetchall()
    con.close()
    return {key: rest for key, *rest in rows}


def _run_script(work, db, script):
    path = work / "scenario.py"
    path.write_text(script)
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=work,
        env=_env(db),
        capture_output=True,
        text=True,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out[-3000:]
    _, processed, skipped, failed = SUMMARY.findall(out)[-1]
    return int(processed), int(skipped), int(failed)


def _empty_items(data):
    """The same CV with every section emptied: name and id are kept."""
    out = {}
    for key, value in data.items():
        if key == "informacoes_pessoais":
            out[key] = value
        elif isinstance(value, list):
            out[key] = []
        elif isinstance(value, dict):
            out[key] = {k: [] if isinstance(v, list) else v for k, v in value.items()}
        else:
            out[key] = value
    return out


@pytest.mark.skipif(not UNIDENTIFIED, reason="no local unidentified CV")
def test_failed_cvs_keep_their_data_and_state(populated):
    import json

    work, db = populated
    folder = work / "data" / "lattes_json"
    cvs = sorted(folder.glob("*.json"))
    states = _states(db, "lattes_projects")
    by_key = {p.name[-21:-5]: p for p in cvs}
    # The CV with the most items is emptied: the guard needs stored items.
    emptied_key = max(by_key, key=lambda k: states[k][1])
    unparsable_key, broken_key = sorted(set(by_key) - {emptied_key})
    originals = {k: by_key[k].read_text() for k in by_key}

    shutil.copy(UNIDENTIFIED[0], folder)
    by_key[unparsable_key].write_text("{")
    emptied = _empty_items(json.loads(originals[emptied_key]))
    by_key[emptied_key].write_text(json.dumps(emptied))
    changed = json.loads(originals[broken_key])
    changed["informacoes_pessoais"]["texto_resumo"] = "Resumo alterado (spec 021)."
    by_key[broken_key].write_text(json.dumps(changed))

    # Without stored items (US1 carries few) an emptied CV is a real change.
    total_loss = states[emptied_key][1] > 0
    if not total_loss:
        pytest.skip("the chosen CVs carry no items yet")

    before = _dump(db)
    assert _run_script(work, db, BROKEN_AWARDS) == (0, 0, 4)
    after = _dump(db)
    changed_tables = [t for t in before if before[t] != after.get(t)]
    assert changed_tables in ([], ["source_document_states"])

    now = _states(db, "lattes_projects")
    unidentified_key = os.path.basename(UNIDENTIFIED[0])[-21:-5]
    assert now[unidentified_key][3] == "unidentified"
    assert now[unparsable_key][3] == "unparsable"
    assert now[broken_key][3] == "partial"
    assert now[emptied_key][3] == "total_loss"
    for key in by_key:  # the processing state is the one before the attempt
        assert now[key][:3] == states[key][:3]

    # The next run with good files processes the changed CV normally.
    by_key[unparsable_key].write_text(originals[unparsable_key])
    by_key[emptied_key].write_text(originals[emptied_key])
    projects = _phase(work, db, "ingest_lattes_projects")
    assert projects == (1, 2, 1)  # the changed CV; the unidentified one fails again
    final = _states(db, "lattes_projects")
    assert final[broken_key][3] is None
    assert final[broken_key][0] != states[broken_key][0]


# --------------------------------------------------------------------------
# US4: a CV gone from lattes.list stays, marked inactive (FR-009, FR-010)
# --------------------------------------------------------------------------


def _statuses(db):
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT source_system, document_key, status FROM source_document_states"
    ).fetchall()
    con.close()
    return {(s, k): status for s, k, status in rows}


def test_an_id_removed_from_the_lattes_list_becomes_inactive(populated):
    work, db = populated
    folder = work / "data" / "lattes_json"
    ids = sorted(p.name[-21:-5] for p in folder.glob("*.json"))
    listing = work / "data" / "lattes_run" / "lattes.list"
    listing.parent.mkdir(parents=True)
    listing.write_text("".join(f"{i},Nome {n}\n" for n, i in enumerate(ids)))
    assert _both(work, db) == ((0, 3, 0), (0, 3, 0))
    statuses = _statuses(db)
    for source in ("lattes_projects", "lattes_advisorships"):
        assert all(statuses[(source, i)] == "active" for i in ids)

    # The CV leaves the list (its JSON is gone too, as after lattes_download).
    gone = ids[0]
    listing.write_text("".join(f"{i},Nome\n" for i in ids[1:]))
    next(folder.glob(f"*{gone}.json")).unlink()
    before = _dump(db)
    assert _both(work, db) == ((0, 2, 0), (0, 2, 0))
    statuses = _statuses(db)
    for source in ("lattes_projects", "lattes_advisorships"):
        assert statuses[(source, gone)] == "inactive"
    after = _dump(db)
    # Its data is kept: only the states changed.
    assert [t for t in before if before[t] != after.get(t)] == [
        "source_document_states"
    ]

    # A listed id without its JSON is a failed download, data kept; and a
    # missing lattes.list changes no status.
    listing.write_text("".join(f"{i},Nome\n" for i in ids))
    assert _both(work, db) == ((0, 2, 1), (0, 2, 1))
    assert _statuses(db)[("lattes_projects", gone)] == "active"
    listing.unlink()
    listing.write_text("")
    statuses = _statuses(db)
    _both(work, db)
    assert _statuses(db) == statuses


# --------------------------------------------------------------------------
# US2: a changed CV is processed alone and gives the rebuild's result (FR-011)
# --------------------------------------------------------------------------

# Rows of these tables are compared between the incremental database and a
# rebuild; ids differ, so each row is compared by its content.
COMPARED = {
    "articles": "SELECT title, year, doi FROM articles",
    "article_authors": "SELECT a.title, p.name FROM article_authors x "
    "JOIN articles a ON a.id = x.article_id JOIN persons p ON p.id = x.researcher_id",
    "initiatives": "SELECT name FROM initiatives",
    "team_members": "SELECT t.name, p.name FROM team_members m "
    "JOIN teams t ON t.id = m.team_id JOIN persons p ON p.id = m.person_id",
    "persons": "SELECT name FROM persons",
    "awards": "SELECT title, year FROM awards",
    "academic_educations": "SELECT title, start_year FROM academic_educations",
    "professional_activities": "SELECT institution, start_year, activity_type "
    "FROM professional_activities",
}


def _content(db):
    con = sqlite3.connect(db)
    out = {t: sorted(map(repr, con.execute(q))) for t, q in COMPARED.items()}
    con.close()
    return out


PROJECT_SECTIONS = (
    "projetos_pesquisa",
    "projetos_extensao",
    "projetos_desenvolvimento",
)


def test_a_cv_that_drops_items_matches_a_rebuild(populated, tmp_path):
    import json

    work, db = populated
    folder = work / "data" / "lattes_json"

    def projects(data):
        return sum(len(data.get(k) or []) for k in PROJECT_SECTIONS)

    # The CV with the most projects drops its first project, education and
    # professional activity.
    edited = max(
        sorted(folder.glob("*.json")),
        key=lambda p: (projects(json.loads(p.read_text())), p.name),
    )
    data = json.loads(edited.read_text())
    for key in ("formacao_academica", "atuacao_profissional") + PROJECT_SECTIONS:
        if data.get(key):
            data[key] = data[key][1:]
            if key in PROJECT_SECTIONS:
                break
    edited.write_text(json.dumps(data))

    before = _content(db)
    assert _both(work, db) == ((1, 2, 0), (1, 2, 0))
    after = _content(db)
    assert after != before  # something was dropped

    # The same inputs from scratch.
    rebuild = tmp_path / "rebuild.db"
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=work,
        env=_env(rebuild),
        check=True,
        capture_output=True,
    )
    _both(work, rebuild)
    expected = _content(rebuild)
    differences = {
        t: (
            sorted(set(after[t]) - set(expected[t]))[:5],
            sorted(set(expected[t]) - set(after[t]))[:5],
        )
        for t in COMPARED
        if after[t] != expected[t]
    }
    assert differences == {}

    con = sqlite3.connect(db)
    deletes = con.execute(
        "SELECT COUNT(*) FROM entity_change_logs WHERE operation = 'delete'"
    ).fetchone()[0]
    con.close()
    assert deletes > 0
