"""SQLite implementation of the horizon_id store port (spec 020).

Reads with plain ``sqlite3`` (column-only queries: the ORM's joined eager loads
would materialize whole graphs, see spec 015) and writes the ETL-owned tables
created by ``src/db/migrations.py``.
"""

import json
import os
import sqlite3
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger
from sqlalchemy.engine import make_url

from src.core.ports.horizon_id_store import IHorizonIdStore

DEFAULT_SNAPSHOT_PATH = "db/horizon_id_history.json"
DEFAULT_ZIP_PATH = "data/exports/exports_canonical.zip"
ID_FILE = "horizon_ids_canonical.json"
ALIAS_FILE = "horizon_id_aliases_canonical.json"

_ENTITY_SQL = {
    "person": (
        "SELECT p.id, p.name, r.cnpq_url, (r.id IS NOT NULL) AS is_researcher "
        "FROM persons p LEFT JOIN researchers r ON r.id = p.id"
    ),
    "research_group": (
        "SELECT rg.id, t.name, rg.cnpq_url "
        "FROM research_groups rg JOIN teams t ON t.id = rg.id"
    ),
    "initiative": (
        "SELECT i.id, i.name, it.name AS type_name FROM initiatives i "
        "LEFT JOIN initiative_types it ON it.id = i.initiative_type_id "
        "WHERE i.id NOT IN (SELECT id FROM advisorships)"
    ),
    "advisorship": (
        "SELECT i.id, i.name, it.name AS type_name FROM initiatives i "
        "JOIN advisorships a ON a.id = i.id "
        "LEFT JOIN initiative_types it ON it.id = i.initiative_type_id"
    ),
    "article": (
        "SELECT id, title, doi, year, type, journal_conference, volume, pages "
        "FROM articles"
    ),
    "research_production": (
        "SELECT rp.id, rp.title, rp.year, pt.name AS type_name "
        "FROM research_productions rp "
        "LEFT JOIN production_types pt ON pt.id = rp.production_type_id"
    ),
    "academic_education": (
        "SELECT ae.id, ae.researcher_id AS parent_id, et.name AS type_name, "
        "ae.title, ae.start_year FROM academic_educations ae "
        "LEFT JOIN education_types et ON et.id = ae.education_type_id"
    ),
    "professional_activity": (
        "SELECT id, researcher_id AS parent_id, institution_name, start_year, "
        "end_year, role_function, bond FROM professional_activities"
    ),
    "award": "SELECT id, researcher_id AS parent_id, title, year FROM awards",
    "proficiency": (
        "SELECT p.id, p.researcher_id AS parent_id, l.name AS language "
        "FROM proficiencies p LEFT JOIN languages l ON l.id = p.language_id"
    ),
    "team": (
        "SELECT t.id, t.name FROM teams t "
        "WHERE t.id NOT IN (SELECT id FROM research_groups)"
    ),
    "fellowship": "SELECT id, name, value FROM fellowships",
    "knowledge_area": "SELECT id, name FROM knowledge_areas",
    "organization": "SELECT id, name FROM organizations",
    "campus": "SELECT id, name FROM organizational_units",
    "initiative_type": "SELECT id, name FROM initiative_types",
    "production_type": "SELECT id, name FROM production_types",
    "role": "SELECT id, name FROM roles",
    "language": "SELECT id, name FROM languages",
    "education_type": "SELECT id, name FROM education_types",
}


def sqlite_path_from_url(database_url: Optional[str]) -> str:
    """File path of a ``sqlite:///`` URL (relative paths kept relative)."""
    if not database_url:
        return "db/horizon.db"
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise ValueError(f"horizon_id store needs a SQLite file, got {database_url}")
    return url.database


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def read_published_history(zip_path: str) -> Dict[str, list]:
    """Ids and aliases of a published exports_canonical.zip (empty if absent)."""
    out: Dict[str, list] = {"ids": [], "aliases": []}
    if not zip_path or not os.path.exists(zip_path):
        return out
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            if ID_FILE in names:
                out["ids"] = json.loads(zf.read(ID_FILE)).get("ids", [])
            if ALIAS_FILE in names:
                out["aliases"] = json.loads(zf.read(ALIAS_FILE)).get("aliases", [])
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        logger.warning("Could not read id history from {}: {}", zip_path, exc)
    return out


def record_merge(
    conn: sqlite3.Connection,
    entity_type: str,
    loser_candidate_ids: List[str],
    winner_entity_id: int,
) -> None:
    """Writes a ``horizon_merge_log`` row inside the consolidator's own
    transaction, before the loser is deleted (research R7). Does nothing on a
    database the migrations have not reached yet."""
    if not loser_candidate_ids or not _table_exists(conn, "horizon_merge_log"):
        return
    conn.execute(
        "INSERT INTO horizon_merge_log (entity_type, loser_candidate_ids, "
        "winner_entity_id, merged_at) VALUES (?, ?, ?, ?)",
        (entity_type, json.dumps(loser_candidate_ids), winner_entity_id, _now()),
    )


class SqliteHorizonIdStore(IHorizonIdStore):
    def __init__(
        self,
        db_path: str,
        snapshot_path: str = DEFAULT_SNAPSHOT_PATH,
        zip_path: str = DEFAULT_ZIP_PATH,
    ):
        self.db_path = db_path
        self.snapshot_path = snapshot_path
        self.zip_path = zip_path

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    # ----------------------------------------------------------------- reads
    def iter_entities(self, entity_type: str) -> Iterable[Dict[str, Any]]:
        sql = _ENTITY_SQL[entity_type]
        with self._connect() as con:
            return [dict(row) for row in con.execute(sql)]

    def source_keys(self) -> Dict[tuple, List[Dict[str, Any]]]:
        out: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
        with self._connect() as con:
            if not _table_exists(con, "entity_matches"):
                return out
            rows = con.execute(
                "SELECT em.canonical_entity_type, em.canonical_entity_id, "
                "sr.source_system, sr.source_entity_type, sr.source_record_id, "
                "sr.source_file FROM entity_matches em "
                "JOIN source_records sr ON sr.id = em.source_record_id"
            )
            for row in rows:
                key = (row["canonical_entity_type"], row["canonical_entity_id"])
                out[key].append(
                    {
                        "source_system": row["source_system"],
                        "source_entity_type": row["source_entity_type"],
                        "source_record_id": row["source_record_id"] or "",
                        "source_file": row["source_file"] or "",
                    }
                )
        return out

    def team_initiatives(self) -> Dict[int, List[int]]:
        out: Dict[int, List[int]] = defaultdict(list)
        with self._connect() as con:
            for row in con.execute(
                "SELECT team_id, initiative_id FROM initiative_teams"
            ):
                out[row["team_id"]].append(row["initiative_id"])
        return out

    def load_history(self) -> Dict[str, Any]:
        """Previous database tables first; otherwise the pre-reset snapshot and
        the published zip, merged (research R5). Each id row carries
        ``origin`` (``database``, ``snapshot`` or ``zip``). The merge log is
        returned whole (consumed entries too): its winners keep the id they
        were given on every later run."""
        history: Dict[str, Any] = {
            "ids": [],
            "candidates": [],
            "aliases": [],
            "merges": [],
            "snapshot_merges": [],
            "source": [],
        }
        with self._connect() as con:
            if _table_exists(con, "horizon_merge_log"):
                history["merges"] = [
                    {
                        **dict(r),
                        "loser_candidate_ids": json.loads(r["loser_candidate_ids"]),
                    }
                    for r in con.execute(
                        "SELECT id, entity_type, loser_candidate_ids, "
                        "winner_entity_id, consumed_at FROM horizon_merge_log "
                        "ORDER BY id"
                    )
                ]
            if _table_exists(con, "horizon_ids"):
                history["ids"] = [
                    {**dict(r), "origin": "database"}
                    for r in con.execute(
                        "SELECT entity_type, horizon_id, rule, natural_key, "
                        "parent_horizon_id FROM horizon_ids"
                    )
                ]
                history["candidates"] = [
                    tuple(r)
                    for r in con.execute(
                        "SELECT horizon_id, candidate_id FROM horizon_id_candidates"
                    )
                ]
                history["aliases"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT alias_horizon_id, horizon_id, reason, created_at "
                        "FROM horizon_id_aliases"
                    )
                ]
        if history["ids"]:
            history["source"].append("database")
            return history

        snapshot = self._read_snapshot()
        if snapshot:
            history["source"].append("snapshot")
            history["ids"].extend(
                {**row, "origin": "snapshot"} for row in snapshot.get("ids", [])
            )
            history["candidates"].extend(
                (c["horizon_id"], c["candidate_id"])
                for c in snapshot.get("candidates", [])
            )
            history["aliases"].extend(snapshot.get("aliases", []))
            history["snapshot_merges"] = snapshot.get("merge_log", [])
        published = read_published_history(self.zip_path)
        if published["ids"] or published["aliases"]:
            history["source"].append("zip")
            seen = {row["horizon_id"] for row in history["ids"]}
            history["ids"].extend(
                {**row, "origin": "zip"}
                for row in published["ids"]
                if row["horizon_id"] not in seen
            )
            seen_alias = {row["alias_horizon_id"] for row in history["aliases"]}
            history["aliases"].extend(
                row
                for row in published["aliases"]
                if row["alias_horizon_id"] not in seen_alias
            )
        return history

    def history_snapshot(self) -> Optional[Dict[str, Any]]:
        """The id tables in the shape of ``db/horizon_id_history.json``
        (data-model.md), or None when the database has no ids. Merge winners
        are stored as their ``horizon_id``: numeric ids do not survive a
        reset."""
        if not os.path.exists(self.db_path):
            return None
        with self._connect() as con:
            if not _table_exists(con, "horizon_ids"):
                return None
            ids = [
                dict(r)
                for r in con.execute(
                    "SELECT entity_type, horizon_id, rule, natural_key, "
                    "parent_horizon_id FROM horizon_ids ORDER BY horizon_id"
                )
            ]
            if not ids:
                return None
            candidates = [
                dict(r)
                for r in con.execute(
                    "SELECT horizon_id, candidate_id FROM horizon_id_candidates "
                    "ORDER BY horizon_id, candidate_id"
                )
            ]
            aliases = [
                dict(r)
                for r in con.execute(
                    "SELECT alias_horizon_id, horizon_id, reason, created_at "
                    "FROM horizon_id_aliases ORDER BY alias_horizon_id"
                )
            ]
            merges = []
            if _table_exists(con, "horizon_merge_log"):
                for r in con.execute(
                    "SELECT m.entity_type, m.loser_candidate_ids, h.horizon_id "
                    "FROM horizon_merge_log m LEFT JOIN horizon_ids h "
                    "ON h.entity_type = m.entity_type "
                    "AND h.entity_id = m.winner_entity_id ORDER BY m.id"
                ):
                    merges.append(
                        {
                            "entity_type": r[0],
                            "loser_candidate_ids": json.loads(r[1]),
                            "winner_horizon_id": r[2],
                        }
                    )
        rule_version = self.get_meta("rule_version")
        return {
            "saved_at": _now(),
            "rule_version": int(rule_version) if rule_version else None,
            "ids": ids,
            "candidates": candidates,
            "aliases": aliases,
            "merge_log": merges,
        }

    def _read_snapshot(self) -> Optional[Dict[str, Any]]:
        if not self.snapshot_path or not os.path.exists(self.snapshot_path):
            return None
        try:
            with open(self.snapshot_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Could not read id history snapshot {}: {}", self.snapshot_path, exc
            )
            return None

    def current_ids(self) -> List[Dict[str, Any]]:
        with self._connect() as con:
            if not _table_exists(con, "horizon_ids"):
                return []
            return [
                dict(r)
                for r in con.execute(
                    "SELECT entity_type, entity_id, horizon_id, rule, natural_key, "
                    "parent_horizon_id FROM horizon_ids"
                )
            ]

    def current_aliases(self) -> List[Dict[str, Any]]:
        with self._connect() as con:
            if not _table_exists(con, "horizon_id_aliases"):
                return []
            return [
                dict(r)
                for r in con.execute(
                    "SELECT alias_horizon_id, horizon_id, reason, created_at "
                    "FROM horizon_id_aliases"
                )
            ]

    def has_entities(self) -> bool:
        with self._connect() as con:
            if not _table_exists(con, "persons"):
                return False
            return con.execute("SELECT 1 FROM persons LIMIT 1").fetchone() is not None

    def get_meta(self, key: str) -> Optional[str]:
        with self._connect() as con:
            if not _table_exists(con, "horizon_meta"):
                return None
            row = con.execute(
                "SELECT value FROM horizon_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    # ---------------------------------------------------------------- writes
    def replace_current(
        self, ids: List[Dict[str, Any]], candidates: List[tuple]
    ) -> None:
        now = _now()
        con = self._connect()
        try:
            with con:
                con.execute("DELETE FROM horizon_ids")
                con.execute("DELETE FROM horizon_id_candidates")
                con.executemany(
                    "INSERT INTO horizon_ids (entity_type, entity_id, horizon_id, "
                    "rule, natural_key, parent_horizon_id, collision_suffix, "
                    "assigned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            row["entity_type"],
                            row["entity_id"],
                            row["horizon_id"],
                            row["rule"],
                            row.get("natural_key"),
                            row.get("parent_horizon_id"),
                            row.get("collision_suffix"),
                            now,
                        )
                        for row in ids
                    ],
                )
                con.executemany(
                    "INSERT OR IGNORE INTO horizon_id_candidates "
                    "(horizon_id, candidate_id) VALUES (?, ?)",
                    candidates,
                )
        finally:
            con.close()

    def upsert_aliases(self, aliases: List[Dict[str, Any]], current: set) -> None:
        now = _now()
        con = self._connect()
        try:
            with con:
                existing = {
                    r["alias_horizon_id"]: dict(r)
                    for r in con.execute("SELECT * FROM horizon_id_aliases")
                }
                for alias in aliases:
                    old = existing.get(alias["alias_horizon_id"])
                    if old is None:
                        con.execute(
                            "INSERT INTO horizon_id_aliases (alias_horizon_id, "
                            "horizon_id, reason, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (
                                alias["alias_horizon_id"],
                                alias["horizon_id"],
                                alias["reason"],
                                alias.get("created_at") or now,
                                now,
                            ),
                        )
                    elif (old["horizon_id"], old["reason"]) != (
                        alias["horizon_id"],
                        alias["reason"],
                    ):
                        con.execute(
                            "UPDATE horizon_id_aliases SET horizon_id = ?, "
                            "reason = ?, updated_at = ? WHERE alias_horizon_id = ?",
                            (
                                alias["horizon_id"],
                                alias["reason"],
                                now,
                                alias["alias_horizon_id"],
                            ),
                        )
                for alias_id in set(existing) & current:
                    con.execute(
                        "DELETE FROM horizon_id_aliases WHERE alias_horizon_id = ?",
                        (alias_id,),
                    )
        finally:
            con.close()

    def mark_merges_consumed(self, merge_ids: List[int]) -> None:
        if not merge_ids:
            return
        now = _now()
        con = self._connect()
        try:
            with con:
                con.executemany(
                    "UPDATE horizon_merge_log SET consumed_at = ? WHERE id = ?",
                    [(now, merge_id) for merge_id in merge_ids],
                )
        finally:
            con.close()

    def set_meta(self, key: str, value: str) -> None:
        con = self._connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO horizon_meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        finally:
            con.close()
