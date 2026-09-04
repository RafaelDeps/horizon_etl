import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from src.core.logic.person_identity import is_junk_name
from src.core.logic.person_matcher import PersonMatcher


@dataclass
class DuplicateGroup:
    canonical_name: str
    winner_id: int
    loser_ids: List[int]
    members: List[Dict[str, Any]]
    status: str = "merged"
    reason: Optional[str] = None


class PersonConsolidator:
    """Consolidates duplicate people/researchers in the SQLite database.

    Two participant records are the same person exactly when their normalized
    names agree and no strong identifier disagrees (contract R6-R9). Groups
    that survive the guard are merged as a union; conflicting-identifier
    homonyms and junk names are refused and reported, never merged.
    """

    def __init__(self, db_path: str = "db/horizon.db"):
        self.db_path = db_path
        self._matcher = PersonMatcher(person_controller=None)

    def _load_people(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            advisorship_count_sql = """
                (
                    SELECT COUNT(*) FROM advisorship_members am
                    WHERE am.person_id = p.id
                ) AS advisorship_count,
            """
            if not self._table_exists(conn, "advisorship_members"):
                advisorship_count_sql = """
                    (
                        SELECT COUNT(*) FROM advisorships a
                        WHERE a.supervisor_id = p.id OR a.student_id = p.id
                    ) AS advisorship_count,
                """
            people = conn.execute(
                f"""
                SELECT
                    p.id,
                    p.name,
                    p.identification_id,
                    r.cnpq_url,
                    r.resume,
                    r.citation_names,
                    (
                        SELECT COUNT(*) FROM person_emails pe
                        WHERE pe.person_id = p.id
                    ) AS email_count,
                    {advisorship_count_sql}
                    (
                        SELECT COUNT(*) FROM team_members tm
                        WHERE tm.person_id = p.id
                    ) AS team_member_count,
                    (
                        SELECT COUNT(*) FROM article_authors aa
                        WHERE aa.researcher_id = p.id
                    ) AS article_count,
                    (
                        SELECT COUNT(*) FROM academic_educations ae
                        WHERE ae.researcher_id = p.id
                           OR ae.advisor_id = p.id
                           OR ae.co_advisor_id = p.id
                    ) AS education_count
                FROM persons p
                LEFT JOIN researchers r ON r.id = p.id
                """
            ).fetchall()
        return [dict(row) for row in people]

    def find_all_groups(self) -> List[DuplicateGroup]:
        """Classifies every duplicate candidate: merged, refused-homonym or
        refused-junk. Only the merged groups are returned by
        ``find_duplicate_groups``, so consolidation is driven by the same
        classification the report describes."""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for record in self._load_people():
            canonical = self._matcher.canonicalize_name(record.get("name") or "")
            if canonical:
                groups.setdefault(canonical, []).append(record)

        duplicate_groups: List[DuplicateGroup] = []
        for canonical_name, members in groups.items():
            if len(members) < 2:
                continue

            ordered = sorted(
                members,
                key=lambda item: (self._quality_score(item), -int(item["id"])),
                reverse=True,
            )
            winner_id = int(ordered[0]["id"])
            loser_ids = [int(item["id"]) for item in ordered[1:]]

            if is_junk_name(canonical_name):
                duplicate_groups.append(
                    DuplicateGroup(
                        canonical_name,
                        winner_id,
                        loser_ids,
                        ordered,
                        status="refused_junk",
                        reason="junk name (not a plausible person's name)",
                    )
                )
                continue

            conflict = self._identifier_conflict(ordered)
            if conflict:
                logger.warning(
                    "Skipping duplicate group '{}' (ids {}): conflicting {} — "
                    "likely distinct homonyms, manual review required.",
                    canonical_name,
                    [int(m["id"]) for m in members],
                    conflict,
                )
                duplicate_groups.append(
                    DuplicateGroup(
                        canonical_name,
                        winner_id,
                        loser_ids,
                        ordered,
                        status="refused_homonym",
                        reason=conflict,
                    )
                )
                continue

            duplicate_groups.append(
                DuplicateGroup(canonical_name, winner_id, loser_ids, ordered)
            )

        return duplicate_groups

    def find_duplicate_groups(self) -> List[DuplicateGroup]:
        return [group for group in self.find_all_groups() if group.status == "merged"]

    def build_report(
        self, groups: Optional[List[DuplicateGroup]] = None
    ) -> Dict[str, Any]:
        """Read-only deduplication report: what would/should be merged and what
        refuses to be. Keeps personal data minimal: member ids, member names and
        the refusal reason only."""
        if groups is None:
            groups = self.find_all_groups()
        merged_groups = [group for group in groups if group.status == "merged"]
        refused_groups = [group for group in groups if group.status != "merged"]
        return {
            "db_path": self.db_path,
            "merged_groups": len(merged_groups),
            "merged_records": sum(len(group.loser_ids) for group in merged_groups),
            "refused_groups": len(refused_groups),
            "groups": [
                {
                    "canonical_name": group.canonical_name,
                    "status": group.status,
                    "reason": group.reason,
                    "winner_id": group.winner_id,
                    "loser_ids": group.loser_ids,
                    "member_ids": [int(member["id"]) for member in group.members],
                    "member_names": [member.get("name") for member in group.members],
                }
                for group in groups
            ],
        }

    def _identifier_conflict(self, members: List[Dict[str, Any]]) -> Optional[str]:
        """Returns the conflicting identifier name when members carry distinct
        strong identifiers (i.e. they are homonyms, not duplicates)."""

        def _lattes_key(url: Optional[str]) -> Optional[str]:
            if not url:
                return None
            return url.rstrip("/").rsplit("/", 1)[-1].strip() or None

        cnpq_ids = {
            _lattes_key(m.get("cnpq_url"))
            for m in members
            if _lattes_key(m.get("cnpq_url"))
        }
        if len(cnpq_ids) > 1:
            return f"cnpq_url ({sorted(cnpq_ids)})"

        identifications = {
            (m.get("identification_id") or "").strip()
            for m in members
            if self._has_strong_identification(m)
        }
        if len(identifications) > 1:
            return f"identification_id ({sorted(identifications)})"

        return None

    def consolidate_all(self) -> int:
        """Consolidate every currently detected duplicate group."""
        merged = 0
        for group in self.find_duplicate_groups():
            for loser_id in group.loser_ids:
                self.consolidate_pair(group.winner_id, loser_id)
                merged += 1
        return merged

    def consolidate_pair(self, winner_id: int, loser_id: int) -> None:
        if winner_id == loser_id:
            return

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

            winner = conn.execute(
                "SELECT id, name, identification_id FROM persons WHERE id = ?",
                (winner_id,),
            ).fetchone()
            loser = conn.execute(
                "SELECT id, name, identification_id FROM persons WHERE id = ?",
                (loser_id,),
            ).fetchone()

            if not winner or not loser:
                raise ValueError("Winner or loser person was not found.")

            logger.info(
                "Consolidating duplicate person {} ('{}') into {} ('{}').",
                loser_id,
                loser["name"],
                winner_id,
                winner["name"],
            )

            with conn:
                self._merge_person_record(conn, winner_id, loser_id)
                self._merge_researcher_record(conn, winner_id, loser_id)
                self._merge_person_emails(conn, winner_id, loser_id)
                self._merge_simple_link_table(
                    conn,
                    table="initiative_persons",
                    key_columns=("initiative_id", "person_id"),
                    static_values=("initiative_id",),
                    winner_id=winner_id,
                    loser_id=loser_id,
                    target_column="person_id",
                )
                self._merge_simple_link_table(
                    conn,
                    table="organization_persons",
                    key_columns=("organization_id", "person_id"),
                    static_values=("organization_id",),
                    winner_id=winner_id,
                    loser_id=loser_id,
                    target_column="person_id",
                )
                self._merge_simple_link_table(
                    conn,
                    table="article_authors",
                    key_columns=("article_id", "researcher_id"),
                    static_values=("article_id",),
                    winner_id=winner_id,
                    loser_id=loser_id,
                    target_column="researcher_id",
                )
                self._merge_simple_link_table(
                    conn,
                    table="researcher_knowledge_areas",
                    key_columns=("researcher_id", "area_id"),
                    static_values=("area_id",),
                    winner_id=winner_id,
                    loser_id=loser_id,
                    target_column="researcher_id",
                )
                self._merge_team_members(conn, winner_id, loser_id)
                if self._table_exists(conn, "advisorship_members"):
                    self._merge_advisorship_members(conn, winner_id, loser_id)
                else:
                    self._update_fk_column(
                        conn, "advisorships", "supervisor_id", winner_id, loser_id
                    )
                    self._update_fk_column(
                        conn, "advisorships", "student_id", winner_id, loser_id
                    )
                self._update_fk_column(
                    conn, "academic_educations", "researcher_id", winner_id, loser_id
                )
                self._update_fk_column(
                    conn, "academic_educations", "advisor_id", winner_id, loser_id
                )
                self._update_fk_column(
                    conn, "academic_educations", "co_advisor_id", winner_id, loser_id
                )
                if self._table_exists(conn, "production_authors"):
                    self._merge_simple_link_table(
                        conn,
                        table="production_authors",
                        key_columns=("production_id", "researcher_id"),
                        static_values=("production_id",),
                        winner_id=winner_id,
                        loser_id=loser_id,
                        target_column="researcher_id",
                    )
                if self._table_exists(conn, "awards"):
                    self._update_fk_column(
                        conn, "awards", "researcher_id", winner_id, loser_id
                    )
                if self._table_exists(conn, "professional_activities"):
                    self._update_fk_column(
                        conn,
                        "professional_activities",
                        "researcher_id",
                        winner_id,
                        loser_id,
                    )
                if self._table_exists(conn, "proficiencies"):
                    self._merge_proficiencies(conn, winner_id, loser_id)
                self._remap_lineage(conn, winner_id, loser_id)
                conn.execute("DELETE FROM researchers WHERE id = ?", (loser_id,))
                conn.execute("DELETE FROM persons WHERE id = ?", (loser_id,))

    def _merge_person_record(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        winner = conn.execute(
            "SELECT identification_id, birthday FROM persons WHERE id = ?",
            (winner_id,),
        ).fetchone()
        loser = conn.execute(
            "SELECT identification_id, birthday FROM persons WHERE id = ?",
            (loser_id,),
        ).fetchone()
        if not winner or not loser:
            return

        if not winner["identification_id"] and loser["identification_id"]:
            # Avoid violating the unique index while both rows still exist.
            conn.execute(
                "UPDATE persons SET identification_id = NULL WHERE id = ?",
                (loser_id,),
            )
            conn.execute(
                "UPDATE persons SET identification_id = ? WHERE id = ?",
                (loser["identification_id"], winner_id),
            )
        elif (
            winner["identification_id"]
            and loser["identification_id"]
            and winner["identification_id"] != loser["identification_id"]
        ):
            # Winner wins; the conflicting value is dropped but documented.
            logger.warning(
                "Ignoring identification_id '{}' of person {} while consolidating "
                "into {} which already owns '{}'.",
                loser["identification_id"],
                loser_id,
                winner_id,
                winner["identification_id"],
            )

        if not winner["birthday"] and loser["birthday"]:
            conn.execute(
                "UPDATE persons SET birthday = ? WHERE id = ?",
                (loser["birthday"], winner_id),
            )
        elif (
            winner["birthday"]
            and loser["birthday"]
            and winner["birthday"] != loser["birthday"]
        ):
            logger.warning(
                "Ignoring birthday '{}' of person {} while consolidating into {} "
                "which already holds '{}'.",
                loser["birthday"],
                loser_id,
                winner_id,
                winner["birthday"],
            )

    def _merge_researcher_record(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        winner_exists = conn.execute(
            "SELECT 1 FROM researchers WHERE id = ?",
            (winner_id,),
        ).fetchone()
        loser_row = conn.execute(
            """
            SELECT cnpq_url, google_scholar_url, resume, citation_names
            FROM researchers
            WHERE id = ?
            """,
            (loser_id,),
        ).fetchone()

        if not loser_row:
            return

        if not winner_exists:
            conn.execute(
                """
                INSERT INTO researchers (id, cnpq_url, google_scholar_url, resume, citation_names)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    winner_id,
                    loser_row["cnpq_url"],
                    loser_row["google_scholar_url"],
                    loser_row["resume"],
                    loser_row["citation_names"],
                ),
            )
            return

        conn.execute(
            """
            UPDATE researchers
            SET cnpq_url = COALESCE(cnpq_url, (SELECT cnpq_url FROM researchers WHERE id = ?)),
                google_scholar_url = COALESCE(google_scholar_url, (SELECT google_scholar_url FROM researchers WHERE id = ?)),
                resume = COALESCE(resume, (SELECT resume FROM researchers WHERE id = ?)),
                citation_names = COALESCE(citation_names, (SELECT citation_names FROM researchers WHERE id = ?))
            WHERE id = ?
            """,
            (loser_id, loser_id, loser_id, loser_id, winner_id),
        )

    def _merge_person_emails(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        emails = conn.execute(
            "SELECT id, email FROM person_emails WHERE person_id = ?",
            (loser_id,),
        ).fetchall()
        for row in emails:
            existing = conn.execute(
                """
                SELECT id, person_id FROM person_emails
                WHERE lower(email) = lower(?)
                ORDER BY id
                LIMIT 1
                """,
                (row["email"],),
            ).fetchone()

            if not existing:
                conn.execute(
                    "UPDATE person_emails SET person_id = ? WHERE id = ?",
                    (winner_id, row["id"]),
                )
                continue

            if existing["person_id"] == winner_id:
                conn.execute("DELETE FROM person_emails WHERE id = ?", (row["id"],))
                continue

            if existing["person_id"] == loser_id and existing["id"] == row["id"]:
                conn.execute(
                    "UPDATE person_emails SET person_id = ? WHERE id = ?",
                    (winner_id, row["id"]),
                )
                continue

            logger.warning(
                "Skipping conflicting email '{}' while consolidating {} into {}; already owned by person {}.",
                row["email"],
                loser_id,
                winner_id,
                existing["person_id"],
            )
            conn.execute("DELETE FROM person_emails WHERE id = ?", (row["id"],))
        conn.execute("DELETE FROM person_emails WHERE person_id = ?", (loser_id,))

    def _merge_simple_link_table(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        key_columns: tuple[str, str],
        static_values: tuple[str, ...],
        winner_id: int,
        loser_id: int,
        target_column: str,
    ) -> None:
        select_columns = ", ".join(static_values)
        source_rows = conn.execute(
            f"SELECT {select_columns} FROM {table} WHERE {target_column} = ?",
            (loser_id,),
        ).fetchall()

        for row in source_rows:
            where_clause = " AND ".join(f"{column} = ?" for column in static_values)
            exists = conn.execute(
                f"SELECT 1 FROM {table} WHERE {where_clause} AND {target_column} = ?",
                tuple(row[column] for column in static_values) + (winner_id,),
            ).fetchone()
            if not exists:
                insert_columns = ", ".join((*static_values, target_column))
                placeholders = ", ".join("?" for _ in (*static_values, target_column))
                conn.execute(
                    f"INSERT INTO {table} ({insert_columns}) VALUES ({placeholders})",
                    tuple(row[column] for column in static_values) + (winner_id,),
                )

        conn.execute(f"DELETE FROM {table} WHERE {target_column} = ?", (loser_id,))

    def _merge_team_members(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        rows = conn.execute(
            """
            SELECT id, team_id, role_id, start_date, end_date
            FROM team_members
            WHERE person_id = ?
            ORDER BY id
            """,
            (loser_id,),
        ).fetchall()

        for row in rows:
            existing = conn.execute(
                """
                SELECT id, role_id, start_date, end_date
                FROM team_members
                WHERE person_id = ? AND team_id = ?
                ORDER BY id
                LIMIT 1
                """,
                (winner_id, row["team_id"]),
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
                    "UPDATE team_members SET person_id = ? WHERE id = ?",
                    (winner_id, row["id"]),
                )

    def _merge_advisorship_members(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        rows = conn.execute(
            """
            SELECT id, advisorship_id, role_name
            FROM advisorship_members
            WHERE person_id = ?
            ORDER BY id
            """,
            (loser_id,),
        ).fetchall()

        for row in rows:
            existing = conn.execute(
                """
                SELECT id
                FROM advisorship_members
                WHERE advisorship_id = ?
                  AND person_id = ?
                  AND COALESCE(role_name, '') = COALESCE(?, '')
                ORDER BY id
                LIMIT 1
                """,
                (row["advisorship_id"], winner_id, row["role_name"]),
            ).fetchone()

            if existing:
                conn.execute(
                    "DELETE FROM advisorship_members WHERE id = ?",
                    (row["id"],),
                )
            else:
                conn.execute(
                    "UPDATE advisorship_members SET person_id = ? WHERE id = ?",
                    (winner_id, row["id"]),
                )

    def _merge_proficiencies(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        conn.execute(
            """
            UPDATE proficiencies SET researcher_id = ?
            WHERE researcher_id = ?
              AND language_id NOT IN (
                SELECT language_id FROM proficiencies WHERE researcher_id = ?
              )
            """,
            (winner_id, loser_id, winner_id),
        )
        conn.execute("DELETE FROM proficiencies WHERE researcher_id = ?", (loser_id,))

    def _remap_lineage(
        self, conn: sqlite3.Connection, winner_id: int, loser_id: int
    ) -> None:
        """Repoints tracking/lineage rows at the winner so entity_matches,
        attribute_assertions and entity_change_logs never reference a deleted
        person. UNIQUE-conflicting rows (same source record already linked to
        the winner) are dropped as exact duplicates."""
        for table in ("entity_matches", "attribute_assertions", "entity_change_logs"):
            if not self._table_exists(conn, table):
                continue
            conn.execute(
                f"""
                UPDATE OR IGNORE {table} SET canonical_entity_id = ?
                WHERE canonical_entity_type IN ('person', 'researcher')
                  AND canonical_entity_id = ?
                """,
                (winner_id, loser_id),
            )
            conn.execute(
                f"""
                DELETE FROM {table}
                WHERE canonical_entity_type IN ('person', 'researcher')
                  AND canonical_entity_id = ?
                """,
                (loser_id,),
            )

    def _update_fk_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        winner_id: int,
        loser_id: int,
    ) -> None:
        conn.execute(
            f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
            (winner_id, loser_id),
        )

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    def _quality_score(self, person_row: Dict[str, Any]) -> int:
        score = 0
        if self._has_strong_identification(person_row):
            score += 30
        elif person_row.get("identification_id"):
            score += 5

        for field in ("cnpq_url", "resume", "citation_names"):
            if person_row.get(field):
                score += 20

        score += int(person_row.get("email_count") or 0) * 15
        score += int(person_row.get("advisorship_count") or 0) * 5
        score += int(person_row.get("team_member_count") or 0) * 2
        score += int(person_row.get("article_count") or 0) * 3
        score += int(person_row.get("education_count") or 0) * 3
        return score

    def _has_strong_identification(self, person_row: Dict[str, Any]) -> bool:
        identification = (person_row.get("identification_id") or "").strip()
        if not identification:
            return False

        name = (person_row.get("name") or "").strip()
        canonical_identification = self._matcher.canonicalize_name(identification)
        canonical_name = self._matcher.canonicalize_name(name)
        if canonical_identification and canonical_identification == canonical_name:
            return False

        return any(char.isdigit() for char in identification) or "@" in identification
