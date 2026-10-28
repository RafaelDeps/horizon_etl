import sqlite3
from dataclasses import dataclass
from typing import Iterable

from loguru import logger

from src.adapters.database.horizon_id_store import record_merge
from src.core.logic.horizon_identity import merge_candidates
from src.core.logic.initiative_identity import normalize_text


@dataclass
class ConsolidationStats:
    merged: int = 0
    skipped: int = 0


class ReferenceConsolidator:
    def __init__(self, db_path: str = "db/horizon.db"):
        self.db_path = db_path

    def consolidate_knowledge_areas(self) -> ConsolidationStats:
        stats = ConsolidationStats()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            groups = self._canonical_groups(
                conn.execute("SELECT id, name FROM knowledge_areas").fetchall()
            )

            with conn:
                for group in groups:
                    winner = self._pick_named_winner(group["members"])
                    losers = [m for m in group["members"] if m["id"] != winner["id"]]
                    for loser in losers:
                        self._merge_knowledge_area(conn, winner["id"], loser["id"])
                        stats.merged += 1
        return stats

    def consolidate_teams(self) -> ConsolidationStats:
        stats = ConsolidationStats()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            groups = self._canonical_groups(
                conn.execute(
                    "SELECT id, name, description, short_name, organization_id FROM teams"
                ).fetchall()
            )

            with conn:
                for group in groups:
                    if self._group_contains_research_group(conn, group["members"]):
                        stats.skipped += 1
                        continue

                    winner = self._pick_team_winner(conn, group["members"])
                    losers = [m for m in group["members"] if m["id"] != winner["id"]]
                    for loser in losers:
                        self._merge_team(conn, winner["id"], loser["id"])
                        stats.merged += 1
        return stats

    def _canonical_groups(self, rows: Iterable[sqlite3.Row]) -> list[dict]:
        groups = {}
        for row in rows:
            row_dict = dict(row)
            canonical = normalize_text(row_dict.get("name"))
            if canonical:
                groups.setdefault(canonical, []).append(row_dict)

        return [
            {"canonical": canonical, "members": members}
            for canonical, members in groups.items()
            if len(members) > 1
        ]

    def _pick_named_winner(self, members: list[dict]) -> dict:
        def score(item: dict) -> tuple[int, int]:
            name = item.get("name") or ""
            return (len(name.strip()), -int(item["id"]))

        return sorted(members, key=score, reverse=True)[0]

    def _pick_team_winner(self, conn: sqlite3.Connection, members: list[dict]) -> dict:
        def score(item: dict) -> tuple[int, int, int, int]:
            team_id = item["id"]
            links = conn.execute(
                "SELECT COUNT(*) FROM initiative_teams WHERE team_id = ?",
                (team_id,),
            ).fetchone()[0]
            memberships = conn.execute(
                "SELECT COUNT(*) FROM team_members WHERE team_id = ?",
                (team_id,),
            ).fetchone()[0]
            text_score = len((item.get("description") or "").strip()) + len(
                (item.get("short_name") or "").strip()
            )
            return (links, memberships, text_score, -int(team_id))

        return sorted(members, key=score, reverse=True)[0]

    def _group_contains_research_group(
        self, conn: sqlite3.Connection, members: list[dict]
    ) -> bool:
        ids = [member["id"] for member in members]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id FROM research_groups WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return bool(rows)

    def _merge_knowledge_area(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        logger.info(
            "Consolidating knowledge area {} into {}.",
            loser_id,
            winner_id,
        )
        self._record_merge(
            conn, "knowledge_area", "knowledge_areas", winner_id, loser_id
        )
        self._merge_link_table(
            conn,
            table="group_knowledge_areas",
            owner_column="group_id",
            ref_column="area_id",
            winner_id=winner_id,
            loser_id=loser_id,
        )
        self._merge_link_table(
            conn,
            table="initiative_knowledge_areas",
            owner_column="initiative_id",
            ref_column="area_id",
            winner_id=winner_id,
            loser_id=loser_id,
        )
        self._merge_link_table(
            conn,
            table="researcher_knowledge_areas",
            owner_column="researcher_id",
            ref_column="area_id",
            winner_id=winner_id,
            loser_id=loser_id,
        )
        conn.execute("DELETE FROM knowledge_areas WHERE id = ?", (loser_id,))

    def _merge_team(self, conn: sqlite3.Connection, winner_id: int, loser_id: int) -> None:
        logger.info("Consolidating team {} into {}.", loser_id, winner_id)
        self._record_merge(conn, "team", "teams", winner_id, loser_id)
        conn.execute(
            """
            UPDATE teams
            SET description = COALESCE(description, (SELECT description FROM teams WHERE id = ?)),
                short_name = COALESCE(short_name, (SELECT short_name FROM teams WHERE id = ?)),
                organization_id = COALESCE(organization_id, (SELECT organization_id FROM teams WHERE id = ?))
            WHERE id = ?
            """,
            (loser_id, loser_id, loser_id, winner_id),
        )

        self._merge_link_table(
            conn,
            table="initiative_teams",
            owner_column="initiative_id",
            ref_column="team_id",
            winner_id=winner_id,
            loser_id=loser_id,
        )
        self._merge_team_members(conn, winner_id, loser_id)
        conn.execute("DELETE FROM teams WHERE id = ?", (loser_id,))

    def _record_merge(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        table: str,
        winner_id: int,
        loser_id: int,
    ) -> None:
        """Spec 020 (research R7): the loser's ids, before the row is gone."""
        row = conn.execute(
            f"SELECT id, name FROM {table} WHERE id = ?", (loser_id,)
        ).fetchone()
        if row is not None:
            record_merge(
                conn,
                entity_type,
                merge_candidates(entity_type, {"id": row[0], "name": row[1]}),
                winner_id,
            )

    def _merge_link_table(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        owner_column: str,
        ref_column: str,
        winner_id: int,
        loser_id: int,
    ) -> None:
        rows = conn.execute(
            f"SELECT {owner_column} FROM {table} WHERE {ref_column} = ?",
            (loser_id,),
        ).fetchall()
        for row in rows:
            owner_id = row[0]
            exists = conn.execute(
                f"SELECT 1 FROM {table} WHERE {owner_column} = ? AND {ref_column} = ?",
                (owner_id, winner_id),
            ).fetchone()
            if not exists:
                conn.execute(
                    f"INSERT INTO {table} ({owner_column}, {ref_column}) VALUES (?, ?)",
                    (owner_id, winner_id),
                )
        conn.execute(f"DELETE FROM {table} WHERE {ref_column} = ?", (loser_id,))

    def _merge_team_members(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        rows = conn.execute(
            """
            SELECT id, person_id, role_id, start_date, end_date
            FROM team_members
            WHERE team_id = ?
            ORDER BY id
            """,
            (loser_id,),
        ).fetchall()

        for row in rows:
            existing = conn.execute(
                """
                SELECT id, role_id, start_date, end_date
                FROM team_members
                WHERE team_id = ? AND person_id = ?
                ORDER BY id
                LIMIT 1
                """,
                (winner_id, row["person_id"]),
            ).fetchone()
            if existing:
                role_id = existing["role_id"] or row["role_id"]
                start_date = existing["start_date"] or row["start_date"]
                end_date = existing["end_date"] or row["end_date"]
                conn.execute(
                    """
                    UPDATE team_members
                    SET role_id = ?, start_date = ?, end_date = ?
                    WHERE id = ?
                    """,
                    (role_id, start_date, end_date, existing["id"]),
                )
                conn.execute("DELETE FROM team_members WHERE id = ?", (row["id"],))
            else:
                conn.execute(
                    "UPDATE team_members SET team_id = ? WHERE id = ?",
                    (winner_id, row["id"]),
                )
