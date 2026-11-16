import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from loguru import logger

from src.adapters.database.horizon_id_store import record_merge
from src.core.logic.horizon_identity import (
    article_decision,
    id_priority,
    merge_candidates,
    normalize_doi,
)
from src.core.logic.initiative_identity import normalize_text

# Where consolidate_articles writes its report (counts only).
REPORT_DIR = "data/reports"

_ARTICLE_COLUMNS = "id, title, doi, year, type, journal_conference, volume, pages"
# Survivor fields filled from the losers when empty; never overwritten.
_ARTICLE_FILL_FIELDS = ("doi", "journal_conference", "volume", "pages")


@dataclass
class ConsolidationStats:
    merged: int = 0
    skipped: int = 0
    # consolidate_articles (spec 029)
    groups: int = 0
    skipped_conflicting_doi: int = 0
    ids_aliased: int = 0


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

    def consolidate_articles(self, report_dir: str = None) -> ConsolidationStats:
        """Spec 029: merges articles that are the same work (same normalized
        DOI, or same normalized title and year unless their DOIs differ).
        One transaction per group; a second pass finds nothing."""
        stats = ConsolidationStats()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            rows = [
                dict(r)
                for r in conn.execute(
                    f"SELECT {_ARTICLE_COLUMNS} FROM articles ORDER BY id"
                )
            ]
            current_ids = self._current_article_ids(conn)
            groups, stats.skipped_conflicting_doi = self._article_groups(rows)
            for members in groups:
                with conn:
                    winner = self._pick_article_survivor(members, current_ids)
                    losers = [m for m in members if m["id"] != winner["id"]]
                    stats.ids_aliased += self._merge_articles(
                        conn, winner, losers, current_ids
                    )
                stats.groups += 1
                stats.merged += len(losers)
        self._write_article_report(stats, report_dir or REPORT_DIR)
        return stats

    @staticmethod
    def _write_article_report(stats: "ConsolidationStats", report_dir: str) -> None:
        report = {
            "groups": stats.groups,
            "rows_merged": stats.merged,
            "skipped_conflicting_doi": stats.skipped_conflicting_doi,
            "ids_aliased": stats.ids_aliased,
        }
        try:
            os.makedirs(report_dir, exist_ok=True)
            path = os.path.join(report_dir, "article_consolidation_report.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
        except OSError as exc:  # a report problem never changes the merge
            logger.warning("Article consolidation report not written: {}", exc)

    @staticmethod
    def _current_article_ids(conn: sqlite3.Connection) -> dict:
        """Row id -> current horizon id, empty when ids were never assigned."""
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='horizon_ids'"
        ).fetchone()
        if not exists:
            return {}
        return {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT entity_id, horizon_id FROM horizon_ids "
                "WHERE entity_type = 'article'"
            )
        }

    @staticmethod
    def _article_groups(rows: list[dict]) -> tuple[list[list[dict]], int]:
        """Rows that are the same work, as lists of two or more. A title group
        whose rows carry different DOIs is not merged as a whole: only rows
        with the same DOI merge, and DOI-less rows are left alone."""
        parent = {r["id"]: r["id"] for r in rows}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[max(root_a, root_b)] = min(root_a, root_b)

        by_doi: dict = {}
        by_title: dict = {}
        for row in rows:
            doi = normalize_doi(row["doi"])
            if doi:
                by_doi.setdefault(doi, []).append(row["id"])
            title = normalize_text(row["title"])
            if title:
                by_title.setdefault((title, row["year"]), []).append(row)
        for ids in by_doi.values():
            for other in ids[1:]:
                union(ids[0], other)
        conflicting = 0
        for members in by_title.values():
            if len(members) < 2:
                continue
            dois = {normalize_doi(m["doi"]) for m in members} - {None}
            if len(dois) > 1:
                conflicting += 1
                continue
            for other in members[1:]:
                union(members[0]["id"], other["id"])

        grouped: dict = {}
        for row in rows:
            grouped.setdefault(find(row["id"]), []).append(row)
        return [g for g in grouped.values() if len(g) > 1], conflicting

    @staticmethod
    def _pick_article_survivor(members: list[dict], current_ids: dict) -> dict:
        """The member whose id, without a collision suffix, has the best
        priority (a DOI id before a hash id); the lowest row id breaks ties."""

        def key(member: dict) -> tuple:
            horizon_id = current_ids.get(member["id"]) or (
                article_decision(member).horizon_id
            )
            return (id_priority(horizon_id.split("~")[0]), member["id"])

        return min(members, key=key)

    def _merge_articles(
        self,
        conn: sqlite3.Connection,
        winner: dict,
        losers: list[dict],
        current_ids: dict,
    ) -> int:
        """Merges the losers into the survivor and logs each merge. Returns
        how many ids become aliases (the losers' ids and the survivor's
        suffixed one)."""
        aliased = set()
        for loser in losers:
            logger.info("Consolidating article {} into {}.", loser["id"], winner["id"])
            # Spec 020 (R7): every id the loser was known by, from its row
            # before it is gone. With the loser's current id and the
            # survivor's suffixed one, the old ids resolve as merge aliases
            # and the survivor can take the bare id.
            candidates = merge_candidates("article", loser)
            loser_current = current_ids.get(loser["id"])
            survivor_current = current_ids.get(winner["id"])
            for horizon_id in (loser_current, survivor_current):
                if horizon_id and ("~" in horizon_id or horizon_id == loser_current):
                    candidates = [*candidates, horizon_id]
                    aliased.add(horizon_id)
            record_merge(conn, "article", list(dict.fromkeys(candidates)), winner["id"])
            self._fill_article_fields(conn, winner, loser)
            self._repoint_article_links(conn, winner["id"], loser["id"])
            conn.execute("DELETE FROM articles WHERE id = ?", (loser["id"],))
        return len(aliased)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    def _repoint_article_links(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        """Moves everything that refers to the loser to the survivor. A row
        that would duplicate one the survivor has is dropped, not moved."""
        if self._table_exists(conn, "article_authors"):
            conn.execute(
                "UPDATE OR IGNORE article_authors SET article_id = ? "
                "WHERE article_id = ?",
                (winner_id, loser_id),
            )
            conn.execute(
                "DELETE FROM article_authors WHERE article_id = ?", (loser_id,)
            )
        for table in ("entity_matches", "attribute_assertions", "entity_change_logs"):
            if not self._table_exists(conn, table):
                continue
            conn.execute(
                f"UPDATE OR IGNORE {table} SET canonical_entity_id = ? "
                "WHERE canonical_entity_type = 'article' AND canonical_entity_id = ?",
                (winner_id, loser_id),
            )
            conn.execute(
                f"DELETE FROM {table} "
                "WHERE canonical_entity_type = 'article' AND canonical_entity_id = ?",
                (loser_id,),
            )
        if self._table_exists(conn, "source_document_items"):
            self._repoint_document_items(conn, winner_id, loser_id)

    @staticmethod
    def _repoint_document_items(
        conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        """Spec 021 items: ``article`` refs are the row id, ``article_author``
        refs are ``<article id>:<researcher id>``."""
        moves = [("article", str(loser_id), str(winner_id))]
        for (ref,) in conn.execute(
            "SELECT DISTINCT item_ref FROM source_document_items "
            "WHERE item_type = 'article_author' AND item_ref LIKE ?",
            (f"{loser_id}:%",),
        ).fetchall():
            moves.append(("article_author", ref, f"{winner_id}:{ref.split(':', 1)[1]}"))
        for item_type, old_ref, new_ref in moves:
            conn.execute(
                "UPDATE OR IGNORE source_document_items SET item_ref = ? "
                "WHERE item_type = ? AND item_ref = ?",
                (new_ref, item_type, old_ref),
            )
            conn.execute(
                "DELETE FROM source_document_items WHERE item_type = ? AND item_ref = ?",
                (item_type, old_ref),
            )

    @staticmethod
    def _fill_article_fields(
        conn: sqlite3.Connection, winner: dict, loser: dict
    ) -> None:
        filled = {
            field: loser[field]
            for field in _ARTICLE_FILL_FIELDS
            if not (winner.get(field) or "").strip()
            and (loser.get(field) or "").strip()
        }
        if not filled:
            return
        winner.update(filled)
        conn.execute(
            "UPDATE articles SET "
            + ", ".join(f"{field} = ?" for field in filled)
            + " WHERE id = ?",
            [*filled.values(), winner["id"]],
        )

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
