"""The ETL-owned table of LinkedIn links and its merge hook (spec 037)."""

import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.adapters.database.linkedin_link_store import (
    LinkedinLinkStore,
    repoint_linkedin_link,
)
from src.db.migrations import run_migrations

MARIA = "https://www.linkedin.com/in/maria"
JOAO = "https://www.linkedin.com/in/joao"


def _database(tmp_path, with_table=True):
    path = tmp_path / "horizon.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE initiatives (id INTEGER PRIMARY KEY, name TEXT)")
    con.executemany(
        "INSERT INTO persons (id, name) VALUES (?, ?)",
        [(1, "Maria da Silva"), (2, "João Souza"), (3, "Ana Lima")],
    )
    con.commit()
    con.close()
    if with_table:
        engine = create_engine(f"sqlite:///{path}")
        with Session(engine) as session:
            run_migrations(session)
        engine.dispose()
    return str(path)


def _rows(path):
    con = sqlite3.connect(path)
    try:
        return con.execute(
            "SELECT person_id, linkedin_url, listed_name, updated_at "
            "FROM person_linkedin_links ORDER BY person_id"
        ).fetchall()
    finally:
        con.close()


def test_persons_returns_every_id_and_name(tmp_path):
    store = LinkedinLinkStore(_database(tmp_path))

    assert sorted(store.persons()) == [
        (1, "Maria da Silva"),
        (2, "João Souza"),
        (3, "Ana Lima"),
    ]


def test_stored_is_empty_without_the_table(tmp_path):
    store = LinkedinLinkStore(_database(tmp_path, with_table=False))

    assert store.stored() == {}


def test_apply_adds_changes_and_removes_exactly_the_given_rows(tmp_path):
    path = _database(tmp_path)
    store = LinkedinLinkStore(path)

    counts = store.apply(
        add=[(1, MARIA, "Maria da Silva"), (2, JOAO, "João Souza")],
        change=[],
        remove=[],
        now="2026-11-13T10:00:00Z",
    )

    assert counts == (2, 0, 0)
    assert store.stored() == {
        1: (MARIA, "Maria da Silva"),
        2: (JOAO, "João Souza"),
    }

    counts = store.apply(
        add=[(3, "https://www.linkedin.com/in/ana", "Ana Lima")],
        change=[(1, "https://www.linkedin.com/in/maria-2", "MARIA DA SILVA")],
        remove=[2],
        now="2026-11-13T11:00:00Z",
    )

    assert counts == (1, 1, 1)
    assert _rows(path) == [
        (
            1,
            "https://www.linkedin.com/in/maria-2",
            "MARIA DA SILVA",
            "2026-11-13T11:00:00Z",
        ),
        (3, "https://www.linkedin.com/in/ana", "Ana Lima", "2026-11-13T11:00:00Z"),
    ]


def test_apply_leaves_other_rows_and_their_timestamp_alone(tmp_path):
    path = _database(tmp_path)
    store = LinkedinLinkStore(path)
    store.apply([(1, MARIA, "Maria da Silva")], [], [], "2026-11-13T10:00:00Z")

    store.apply([(2, JOAO, "João Souza")], [], [], "2026-11-13T11:00:00Z")

    assert _rows(path)[0] == (1, MARIA, "Maria da Silva", "2026-11-13T10:00:00Z")


def test_apply_is_one_transaction(tmp_path):
    path = _database(tmp_path)
    store = LinkedinLinkStore(path)
    store.apply([(1, MARIA, "Maria da Silva")], [], [], "2026-11-13T10:00:00Z")

    # The second row repeats a link already stored: nothing of the call stays.
    with pytest.raises(sqlite3.IntegrityError):
        store.apply(
            [(3, "https://www.linkedin.com/in/ana", "Ana Lima"), (2, MARIA, "João")],
            [],
            [],
            "2026-11-13T11:00:00Z",
        )

    assert [row[0] for row in _rows(path)] == [1]


def test_apply_with_nothing_to_do_writes_nothing(tmp_path):
    path = _database(tmp_path)
    store = LinkedinLinkStore(path)

    assert store.apply([], [], [], "2026-11-13T10:00:00Z") == (0, 0, 0)
    assert _rows(path) == []


# --- merge hook (contract section 5) ---


def _hook_db(tmp_path, rows):
    path = _database(tmp_path)
    con = sqlite3.connect(path)
    con.executemany(
        "INSERT INTO person_linkedin_links VALUES (?, ?, ?, '2026-11-13T10:00:00Z')",
        rows,
    )
    con.commit()
    return path, con


def test_the_link_of_the_loser_moves_to_a_winner_without_one(tmp_path):
    path, con = _hook_db(tmp_path, [(2, JOAO, "João Souza")])

    repoint_linkedin_link(con, winner_id=1, loser_id=2)
    con.commit()
    con.close()

    assert _rows(path) == [(1, JOAO, "João Souza", "2026-11-13T10:00:00Z")]


def test_a_winner_with_a_link_keeps_it_and_the_losers_row_goes(tmp_path):
    path, con = _hook_db(
        tmp_path, [(1, MARIA, "Maria da Silva"), (2, JOAO, "João Souza")]
    )

    repoint_linkedin_link(con, winner_id=1, loser_id=2)
    con.commit()
    con.close()

    assert _rows(path) == [(1, MARIA, "Maria da Silva", "2026-11-13T10:00:00Z")]


def test_a_loser_without_a_link_changes_nothing(tmp_path):
    path, con = _hook_db(tmp_path, [(1, MARIA, "Maria da Silva")])

    repoint_linkedin_link(con, winner_id=1, loser_id=2)
    repoint_linkedin_link(con, winner_id=3, loser_id=2)
    con.commit()
    con.close()

    assert _rows(path) == [(1, MARIA, "Maria da Silva", "2026-11-13T10:00:00Z")]


def test_the_hook_does_nothing_on_a_database_without_the_table(tmp_path):
    con = sqlite3.connect(_database(tmp_path, with_table=False))

    repoint_linkedin_link(con, winner_id=1, loser_id=2)

    con.close()
