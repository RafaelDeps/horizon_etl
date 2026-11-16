"""Item links of source documents and deletion of dropped items (spec 021).

Each processed document stores the items it carries in
``source_document_items`` (research R6). When a changed document is processed
again, the items it no longer carries are deleted, unless another document
still carries them or a row outside the document still needs them
(data-model.md, "Deletion of a removed item"). Everything runs on the shared
connection of the document transaction, so a deletion is undone with the rest
of a failed document.

Deletions are conservative: an item is kept whenever something still refers
to it (another document's link, a child initiative, another document's team
contribution, an author link, any foreign key to a person). Reference tables
(campus, organization, knowledge area, types, roles, languages, fellowships)
and research groups are never deleted, and neither are the tracking rows of a
deleted item (FR-011b).
"""

from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import text

Item = Tuple[str, str, bool]  # (item_type, item_ref, is_subject)

PERSON_TYPES = ("person", "researcher")
LATTES_SOURCES = ("lattes_projects", "lattes_advisorships")

# Order of deletion: links before the rows they point at, persons last (they
# become orphans only once the rows that referred to them are gone).
_ORDER = (
    "team_contribution",
    "article_author",
    "production_author",
    "award",
    "proficiency",
    "professional_activity",
    "academic_education",
    "initiative",
    "article",
    "research_production",
    "person",
    "researcher",
)

# Tables whose rows belong to the person and go with it; every other foreign
# key to persons or researchers is a reference that keeps the person.
_PERSON_OWN_TABLES = ("person_emails", "researchers")


class Deletion:
    """One deleted item, for the ``delete`` change log (FR-011b)."""

    def __init__(self, entity_type: str, entity_id: int, before: dict):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.before = before


def _int(ref: str) -> Optional[int]:
    try:
        return int(ref)
    except (TypeError, ValueError):
        return None


class DocumentItemStore:
    def __init__(self, connection_getter):
        self._get = connection_getter
        self._fk_cache: Optional[Dict[str, List[Tuple[str, str]]]] = None

    @property
    def _conn(self):
        return self._get()

    # ------------------------------------------------------------------
    # links
    # ------------------------------------------------------------------

    def stored_items(
        self, source_system: str, document_key: str
    ) -> Set[Tuple[str, str]]:
        return {
            (row[0], row[1])
            for row in self._conn.execute(
                text(
                    "SELECT item_type, item_ref FROM source_document_items "
                    "WHERE source_system = :s AND document_key = :k"
                ),
                {"s": source_system, "k": document_key},
            )
        }

    def replace_items(
        self,
        source_system: str,
        document_key: str,
        items: Iterable[Item],
        stored_item_count: int = 0,
    ) -> List[Deletion]:
        """Stores the document's new link set and deletes what it dropped.

        A document processed before the links were recorded (``item_count``
        above zero, no link rows) has an unknown old set: nothing is deleted
        for it this time."""
        conn = self._conn
        new = {(t, str(r)): bool(subject) for t, r, subject in items}
        old = self.stored_items(source_system, document_key)
        conn.execute(
            text(
                "DELETE FROM source_document_items "
                "WHERE source_system = :s AND document_key = :k"
            ),
            {"s": source_system, "k": document_key},
        )
        if new:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO source_document_items (source_system, "
                    "document_key, item_type, item_ref, is_subject) "
                    "VALUES (:s, :k, :t, :r, :subject)"
                ),
                [
                    {
                        "s": source_system,
                        "k": document_key,
                        "t": t,
                        "r": r,
                        "subject": int(subject),
                    }
                    for (t, r), subject in sorted(new.items())
                ],
            )
        if not old and stored_item_count > 0:
            return []
        removed = old - set(new)
        deletions: List[Deletion] = []
        rank = {t: i for i, t in enumerate(_ORDER)}
        for item_type, item_ref in sorted(
            removed, key=lambda i: (rank.get(i[0], len(_ORDER)), i[1])
        ):
            deleter = getattr(self, f"_delete_{item_type}", None)
            if deleter is None:
                continue  # reference rows and research groups are kept
            if self.is_carried(item_type, item_ref):
                continue
            deletions.extend(deleter(item_ref, source_system, document_key, old))
        return deletions

    def is_carried(self, item_type: str, item_ref: str) -> bool:
        types = PERSON_TYPES if item_type in PERSON_TYPES else (item_type,)
        marks = ", ".join(f":t{i}" for i in range(len(types)))
        params = {f"t{i}": t for i, t in enumerate(types)}
        params["r"] = str(item_ref)
        return (
            self._conn.execute(
                text(
                    f"SELECT 1 FROM source_document_items WHERE item_type IN ({marks}) "
                    "AND item_ref = :r LIMIT 1"
                ),
                params,
            ).fetchone()
            is not None
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _row(self, table: str, column: str, value) -> Optional[dict]:
        result = self._conn.execute(
            text(f'SELECT * FROM "{table}" WHERE "{column}" = :v'), {"v": value}
        )
        row = result.fetchone()
        return dict(row._mapping) if row is not None else None

    def _exists(self, sql: str, params: dict) -> bool:
        return self._conn.execute(text(sql), params).fetchone() is not None

    def _table_exists(self, name: str) -> bool:
        return self._exists(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :n",
            {"n": name},
        )

    def _delete(self, table: str, where: str, params: dict) -> None:
        if self._table_exists(table):
            self._conn.execute(text(f'DELETE FROM "{table}" WHERE {where}'), params)

    def _foreign_keys(self) -> Dict[str, List[Tuple[str, str]]]:
        """``referenced table -> [(table, column)]`` from the schema itself, so
        a table added by a library is covered without a list to maintain."""
        if self._fk_cache is None:
            fks: Dict[str, List[Tuple[str, str]]] = {}
            tables = [
                r[0]
                for r in self._conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            ]
            for table in tables:
                for fk in self._conn.execute(
                    text(f'PRAGMA foreign_key_list("{table}")')
                ):
                    fks.setdefault(fk[2], []).append((table, fk[3]))
            self._fk_cache = fks
        return self._fk_cache

    # ------------------------------------------------------------------
    # one delete routine per item type
    # ------------------------------------------------------------------

    def _delete_team_contribution(self, ref, source_system, document_key, old):
        """What this document said about a team; the members no other
        document contributes go with it (the union rule of spec 020)."""
        team, _, contribution_key = ref.partition("|")
        team_id = _int(team)
        if team_id is None:
            return []
        conn = self._conn
        dropped = conn.execute(
            text(
                "SELECT person_id, role_id, COALESCE(start_date, '') FROM "
                "team_member_contributions WHERE team_id = :t AND document_key = :d"
            ),
            {"t": team_id, "d": contribution_key},
        ).fetchall()
        conn.execute(
            text(
                "DELETE FROM team_member_contributions "
                "WHERE team_id = :t AND document_key = :d"
            ),
            {"t": team_id, "d": contribution_key},
        )
        for person_id, role_id, start in dropped:
            still = self._exists(
                "SELECT 1 FROM team_member_contributions WHERE team_id = :t AND "
                "person_id = :p AND role_id = :r AND COALESCE(start_date, '') = :s",
                {"t": team_id, "p": person_id, "r": role_id, "s": start},
            )
            if still:
                continue
            conn.execute(
                text(
                    "DELETE FROM team_members WHERE team_id = :t AND person_id = :p "
                    "AND role_id = :r AND COALESCE(substr(start_date, 1, 10), '') = :s"
                ),
                {"t": team_id, "p": person_id, "r": role_id, "s": start[:10]},
            )
        return []

    def _delete_link(self, table, columns, ref):
        a, _, b = ref.partition(":")
        if _int(a) is None or _int(b) is None:
            return []
        self._delete(
            table,
            f'"{columns[0]}" = :a AND "{columns[1]}" = :b',
            {"a": int(a), "b": int(b)},
        )
        return []

    def _delete_article_author(self, ref, *_):
        return self._delete_link(
            "article_authors", ("article_id", "researcher_id"), ref
        )

    def _delete_production_author(self, ref, *_):
        return self._delete_link(
            "production_authors", ("production_id", "researcher_id"), ref
        )

    def _delete_owned_row(self, table, entity_type, ref):
        row_id = _int(ref)
        before = self._row(table, "id", row_id) if row_id is not None else None
        if before is None:
            return []
        self._delete(table, "id = :id", {"id": row_id})
        return [Deletion(entity_type, row_id, before)]

    def _delete_award(self, ref, *_):
        return self._delete_owned_row("awards", "award", ref)

    def _delete_proficiency(self, ref, *_):
        return self._delete_owned_row("proficiencies", "proficiency", ref)

    def _delete_professional_activity(self, ref, *_):
        return self._delete_owned_row(
            "professional_activities", "professional_activity", ref
        )

    def _delete_academic_education(self, ref, *_):
        row_id = _int(ref)
        if row_id is None:
            return []
        self._delete(
            "academic_education_knowledge_areas",
            "academic_education_id = :id",
            {"id": row_id},
        )
        return self._delete_owned_row("academic_educations", "academic_education", ref)

    def _delete_article(self, ref, *_):
        row_id = _int(ref)
        if row_id is None or self._exists(
            "SELECT 1 FROM article_authors WHERE article_id = :id", {"id": row_id}
        ):
            return []
        return self._delete_owned_row("articles", "article", ref)

    def _delete_research_production(self, ref, *_):
        row_id = _int(ref)
        if row_id is None or self._exists(
            "SELECT 1 FROM production_authors WHERE production_id = :id",
            {"id": row_id},
        ):
            return []
        return self._delete_owned_row(
            "research_productions", "research_production", ref
        )

    def _delete_initiative(self, ref, source_system, document_key, old):
        """An initiative no document carries, with its teams and links. Kept
        while a child initiative points at it, or while another document
        still contributes to one of its teams."""
        row_id = _int(ref)
        if row_id is None:
            return []
        before = self._row("initiatives", "id", row_id)
        if before is None:
            return []
        if self._exists(
            "SELECT 1 FROM initiatives WHERE parent_id = :id", {"id": row_id}
        ):
            return []
        conn = self._conn
        team_ids = [
            r[0]
            for r in conn.execute(
                text("SELECT team_id FROM initiative_teams WHERE initiative_id = :id"),
                {"id": row_id},
            )
        ]
        own = {r for t, r in old if t == "team_contribution"}
        for team_id in team_ids:
            for (key,) in conn.execute(
                text(
                    "SELECT DISTINCT document_key FROM team_member_contributions "
                    "WHERE team_id = :t"
                ),
                {"t": team_id},
            ).fetchall():
                if f"{team_id}|{key}" not in own:
                    return []
        entity_type = "initiative"
        if self._table_exists("advisorships") and self._exists(
            "SELECT 1 FROM advisorships WHERE id = :id", {"id": row_id}
        ):
            entity_type = "advisorship"
            self._delete("advisorship_members", "advisorship_id = :id", {"id": row_id})
            self._delete("advisorships", "id = :id", {"id": row_id})
        for table in (
            "initiative_teams",
            "initiative_knowledge_areas",
            "initiative_persons",
            "initiative_demandantes",
            "initiative_external_groups",
        ):
            self._delete(table, "initiative_id = :id", {"id": row_id})
        for team_id in team_ids:
            shared = self._exists(
                "SELECT 1 FROM initiative_teams WHERE team_id = :t", {"t": team_id}
            ) or self._exists(
                "SELECT 1 FROM research_groups WHERE id = :t", {"t": team_id}
            )
            if shared:
                continue
            self._delete("team_member_contributions", "team_id = :t", {"t": team_id})
            self._delete("team_members", "team_id = :t", {"t": team_id})
            self._delete("teams", "id = :t", {"t": team_id})
        self._delete("initiatives", "id = :id", {"id": row_id})
        return [Deletion(entity_type, row_id, before)]

    def _delete_person(self, ref, *_):
        """A person no document carries and nothing refers to any more
        (FR-011a). The owner of an active Lattes CV is always kept."""
        person_id = _int(ref)
        if person_id is None:
            return []
        before = self._row("persons", "id", person_id)
        if before is None:
            return []
        if self._owns_active_cv(person_id):
            return []
        for table in ("persons", "researchers"):
            for ref_table, column in self._foreign_keys().get(table, []):
                if ref_table in _PERSON_OWN_TABLES:
                    continue
                if self._exists(
                    f'SELECT 1 FROM "{ref_table}" WHERE "{column}" = :p LIMIT 1',
                    {"p": person_id},
                ):
                    return []
        if self._table_exists("team_member_contributions") and self._exists(
            "SELECT 1 FROM team_member_contributions WHERE person_id = :p LIMIT 1",
            {"p": person_id},
        ):
            return []
        entity_type = "person"
        if self._exists("SELECT 1 FROM researchers WHERE id = :p", {"p": person_id}):
            entity_type = "researcher"
        self._delete("person_emails", "person_id = :p", {"p": person_id})
        self._delete("researchers", "id = :p", {"p": person_id})
        self._delete("persons", "id = :p", {"p": person_id})
        return [Deletion(entity_type, person_id, before)]

    _delete_researcher = _delete_person

    def _owns_active_cv(self, person_id: int) -> bool:
        row = self._conn.execute(
            text("SELECT cnpq_url FROM researchers WHERE id = :p"), {"p": person_id}
        ).fetchone()
        url = (row[0] or "").rstrip("/") if row else ""
        lattes_id = url.rsplit("/", 1)[-1]
        if not (lattes_id.isdigit() and len(lattes_id) == 16):
            return False
        return self._exists(
            "SELECT 1 FROM source_document_states WHERE document_key = :k "
            "AND status = 'active' AND source_system IN "
            "('lattes_projects', 'lattes_advisorships')",
            {"k": lattes_id},
        )


def repoint_person_links(conn, winner_id: int, loser_id: int) -> None:
    """Merge hook for ``PersonConsolidator`` (research R6, "Merges"): the
    links of the loser now belong to the winner, so a merged person keeps the
    links of both CVs. Runs on the consolidator's raw ``sqlite3`` connection,
    inside its transaction."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'source_document_items'"
    ).fetchone()
    if not exists:
        return
    conn.execute(
        "UPDATE OR IGNORE source_document_items SET item_ref = ? "
        "WHERE item_type IN ('person', 'researcher') AND item_ref = ?",
        (str(winner_id), str(loser_id)),
    )
    conn.execute(
        "DELETE FROM source_document_items "
        "WHERE item_type IN ('person', 'researcher') AND item_ref = ?",
        (str(loser_id),),
    )
