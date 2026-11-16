"""Spec 021 (research R5, FR-006): one transaction per document over the
libraries' own commits, without editing the libraries.

Each scenario runs in a subprocess on a temporary SQLite database, because the
libraries' database client is a process-wide singleton configured from
DATABASE_URL at import time. Another connection (plain ``sqlite3``) checks what
is really committed.
"""

import os
import subprocess
import sys
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRELUDE = """
import sqlite3, sys
from eo_lib import Person, PersonController
from src.adapters.database.document_transaction import DocumentTransaction
from src.adapters.database.sqlite_settings import install_sqlite_connection_settings

install_sqlite_connection_settings()
DB = sys.argv[1]

def persons():
    con = sqlite3.connect(DB)
    try:
        return [r[0] for r in con.execute("SELECT name FROM persons ORDER BY name")]
    finally:
        con.close()

def add(name):
    PersonController().create(Person(name=name))  # the library commits
"""


def _run(tmp_path, body):
    db = tmp_path / "doc.db"
    env = dict(os.environ)
    env.update(DATABASE_URL=f"sqlite:///{db}", STORAGE_TYPE="db", PYTHONPATH=REPO)
    subprocess.run(
        [sys.executable, os.path.join(REPO, "db", "create_db.py")],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
    )
    script = tmp_path / "scenario.py"
    script.write_text(PRELUDE + textwrap.dedent(body))
    result = subprocess.run(
        [sys.executable, str(script), str(db)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_library_commits_stay_inside_the_document_until_it_commits(tmp_path):
    _run(
        tmp_path,
        """
        tx = DocumentTransaction()
        tx.begin()
        add("Ana"); add("Bruno")
        assert persons() == [], persons()
        tx.commit()
        assert persons() == ["Ana", "Bruno"], persons()
        tx.close()
        """,
    )


def test_a_rolled_back_document_leaves_nothing_and_the_next_one_works(tmp_path):
    _run(
        tmp_path,
        """
        tx = DocumentTransaction()
        tx.begin(); add("Ana"); tx.commit()
        tx.begin(); add("Carla"); add("Davi"); tx.rollback()
        assert persons() == ["Ana"], persons()
        tx.begin(); add("Eva"); tx.commit()
        assert persons() == ["Ana", "Eva"], persons()
        tx.close()
        """,
    )


def test_a_failed_row_rolls_back_alone_and_the_session_keeps_working(tmp_path):
    _run(
        tmp_path,
        """
        tx = DocumentTransaction()
        tx.begin()
        add("Ana")
        session = PersonController()._service._repository._session
        session.add(Person(name="Falha"))
        session.flush()
        session.rollback()  # what ProjectLoader does after a failed row
        add("Bia")
        tx.commit()
        assert persons() == ["Ana", "Bia"], persons()
        tx.close()
        """,
    )


def test_both_library_clients_and_the_tracking_sessions_share_the_connection(
    tmp_path,
):
    _run(
        tmp_path,
        """
        from eo_lib.infrastructure.database.postgres_client import PostgresClient as Eo
        from src.adapters.database.document_transaction import active_connection
        from src.tracking.controllers import IngestionRunController
        from src.tracking.service_factory import TrackingServiceFactory
        try:
            from research_domain.infrastructure.database.postgres_client import (
                PostgresClient as Rd,
            )
        except ImportError:
            Rd = None

        tx = DocumentTransaction()
        conn = active_connection()
        assert Eo()._SessionLocal().get_bind() is conn
        if Rd is not None:
            assert Rd()._SessionLocal().get_bind() is conn
        assert TrackingServiceFactory._session().get_bind() is conn

        tx.begin()
        add("Ana")
        IngestionRunController().create_run(source_system="test", flow_name="test")
        con = sqlite3.connect(DB)
        assert con.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0
        con.close()
        tx.rollback()
        con = sqlite3.connect(DB)
        assert con.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0
        con.close()
        assert persons() == []
        tx.close()
        """,
    )


def test_close_restores_the_libraries_own_sessions(tmp_path):
    _run(
        tmp_path,
        """
        from eo_lib.infrastructure.database.postgres_client import PostgresClient as Eo
        original = Eo()._SessionLocal
        tx = DocumentTransaction()
        assert Eo()._SessionLocal is not original
        tx.close()
        assert Eo()._SessionLocal is original
        add("Ana")  # commits on its own again
        assert persons() == ["Ana"], persons()
        """,
    )


# --------------------------------------------------------------------------
# Contract rule 8 and the libraries the rebinding relies on (spec 021, T056)
# --------------------------------------------------------------------------

# The versions the _SessionLocal rebinding was proven on (research R5). A new
# version may change how its client builds sessions: rerun this file and the
# T009 proof of concept, then update the pins.
PINNED = {"eo_lib": "0.2.2", "research_domain": "0.14.4", "libbase": "0.1.0"}


def test_the_rebinding_targets_the_pinned_library_clients():
    from importlib.metadata import version

    assert {name: version(name) for name in PINNED} == PINNED
    from eo_lib.infrastructure.database.postgres_client import PostgresClient as Eo
    from research_domain.infrastructure.database.postgres_client import (
        PostgresClient as Rd,
    )

    for client in (Eo(), Rd()):
        assert hasattr(client, "_SessionLocal"), type(client)


WRITERS = """
import glob, sys
from sqlalchemy import event
from sqlalchemy.engine import Engine
from src.tracking.context import current_document

writers = set()

@event.listens_for(Engine, "before_cursor_execute")
def _watch(conn, cursor, statement, params, context, executemany):
    verb = statement.lstrip().split(" ", 1)[0].upper()
    if current_document.get() is not None and verb in ("INSERT", "UPDATE", "DELETE"):
        writers.add(id(conn.connection.dbapi_connection))

from src.flows.lattes.projects import ingest_lattes_projects_flow
ingest_lattes_projects_flow()
print("WRITERS", len(writers))
"""


def test_a_document_phase_writes_through_one_connection(tmp_path):
    import glob
    import shutil

    import pytest

    cvs = sorted(
        (
            p
            for p in glob.glob(os.path.join(REPO, "data", "lattes_json", "*.json"))
            if "Nome-nao-identificado" not in p
        ),
        key=os.path.getsize,
    )
    if len(cvs) < 30:
        pytest.skip("no local Lattes JSON")
    folder = tmp_path / "data" / "lattes_json"
    folder.mkdir(parents=True)
    shutil.copy(cvs[25], folder)
    env_prefix = (
        "import os\n"
        "os.environ.update(HORIZON_TELEGRAM_BOT_TOKEN='', HORIZON_TELEGRAM_CHAT_ID='',"
        " TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='', HORIZON_QUIET_PREFECT='1',"
        " PREFECT_LOGGING_TO_API_ENABLED='false')\nimport app\n"
    )
    out = _run(tmp_path, env_prefix + WRITERS)
    assert "WRITERS 1" in out, out[-2000:]
