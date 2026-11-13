"""SQLite store of the LinkedIn links (spec 037).

``person_linkedin_links`` is an ETL-owned table created by
``src/db/migrations.py`` beside the library's person tables, which it never
alters: one row per person that has a link, one person per link.

Plain ``sqlite3`` with column-only queries, as the other ETL-owned stores.
"""

import sqlite3
from contextlib import closing
from typing import Dict, Iterable, List, Tuple

TABLE = "person_linkedin_links"

Row = Tuple[int, str, str]  # person id, link, name as written in the list


def _has_table(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (TABLE,),
        ).fetchone()
        is not None
    )


class LinkedinLinkStore:
    """Reads the person names and reads and writes the links."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def persons(self) -> List[Tuple[int, str]]:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT id, name FROM persons").fetchall()

    def stored(self) -> Dict[int, Tuple[str, str]]:
        """``person id -> (link, name as written in the list)``."""
        with closing(self._connect()) as conn:
            if not _has_table(conn):
                return {}
            return {
                person_id: (link, name)
                for person_id, link, name in conn.execute(
                    f"SELECT person_id, linkedin_url, listed_name FROM {TABLE}"
                )
            }

    def apply(
        self,
        add: Iterable[Row],
        change: Iterable[Row],
        remove: Iterable[int],
        now: str,
    ) -> Tuple[int, int, int]:
        """Writes exactly the given rows, in one transaction, and returns how
        many were added, changed and removed. Rows not named are untouched."""
        add, change, remove = list(add), list(change), list(remove)
        if not (add or change or remove):
            return 0, 0, 0
        with closing(self._connect()) as conn:
            with conn:
                # Removals and changes first: a link freed by one person may
                # be given to another in the same call.
                conn.executemany(
                    f"DELETE FROM {TABLE} WHERE person_id = ?",
                    [(person_id,) for person_id in remove],
                )
                conn.executemany(
                    f"UPDATE {TABLE} SET linkedin_url = ?, listed_name = ?, "
                    "updated_at = ? WHERE person_id = ?",
                    [(link, name, now, person_id) for person_id, link, name in change],
                )
                conn.executemany(
                    f"INSERT INTO {TABLE} "
                    "(person_id, linkedin_url, listed_name, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    [(person_id, link, name, now) for person_id, link, name in add],
                )
        return len(add), len(change), len(remove)


def repoint_linkedin_link(conn, winner_id: int, loser_id: int) -> None:
    """Merge hook for ``PersonConsolidator``: when two persons are merged the
    link of the one that goes away stays with the one that remains, unless
    that one already has a link. Runs on the consolidator's raw ``sqlite3``
    connection, inside its transaction."""
    if not _has_table(conn):
        return
    conn.execute(
        f"UPDATE OR IGNORE {TABLE} SET person_id = ? WHERE person_id = ?",
        (winner_id, loser_id),
    )
    conn.execute(f"DELETE FROM {TABLE} WHERE person_id = ?", (loser_id,))
