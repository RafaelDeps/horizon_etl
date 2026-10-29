"""SQLite implementation of the document state store (spec 021).

Every read and write goes through the shared connection of the active
``DocumentTransaction``, never a connection of its own: SQLite has one write
lock, and the document's data is written on that connection too, so the state
is committed in the same transaction as the data (FR-006).
"""

from bisect import bisect_right
from datetime import datetime, timezone
from typing import Dict, Iterable, List

from sqlalchemy import text

from src.adapters.database.document_item_store import DocumentItemStore
from src.adapters.database.document_transaction import DocumentTransaction
from src.core.logic.horizon_identity import (
    initiative_reference_key,
    person_reference_key,
)
from src.core.ports.document_state_store import (
    ACTIVE,
    INACTIVE,
    Delta,
    DocumentFailed,
    DocumentOutcome,
    DocumentState,
    IDocumentStateStore,
    ListingResult,
    Reference,
)

# Lattes CVs and CNPq pages always carry items; a SigPesq row or a PJ file maps
# to one entity, so losing "every item" means nothing there (R4).
TOTAL_LOSS_SOURCES = ("lattes_projects", "lattes_advisorships", "cnpq_group")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SqliteDocumentStateStore(IDocumentStateStore):
    def __init__(self, transaction: DocumentTransaction, rule_version: int):
        self._delta_cache = None
        self._tx = transaction
        self._rule_version = rule_version

    @property
    def _conn(self):
        return self._tx.connection

    def load(self, source_system: str) -> Dict[str, DocumentState]:
        rows = self._conn.execute(
            text("SELECT * FROM source_document_states WHERE source_system = :s"),
            {"s": source_system},
        ).mappings()
        return {row["document_key"]: DocumentState(**row) for row in rows}

    def references(self, source_system: str, document_key: str) -> List[Reference]:
        rows = self._conn.execute(
            text(
                "SELECT kind, lookup_key, outcome, score FROM source_document_references "
                "WHERE source_system = :s AND document_key = :k "
                "ORDER BY kind, lookup_key"
            ),
            {"s": source_system, "k": document_key},
        ).mappings()
        return [Reference(**row) for row in rows]

    def delta(self, state: DocumentState) -> Delta:
        """Persons and initiatives created after the state was written, plus
        those renamed since its run. Read from per-phase caches: a skipped
        document writes nothing, so after a rebuild the same thousands of
        rows would otherwise be read again for every document."""
        persons, person_ids, initiatives, initiative_ids = self._delta_rows()
        renamed_persons, renamed_initiatives = self._renamed_since(
            state.last_ingestion_run_id
        )
        cut = bisect_right(person_ids, state.max_person_id or 0)
        found = persons[cut:]
        seen = set(person_ids[cut:])
        by_id = self._person_by_id
        found = found + [by_id[i] for i in sorted(renamed_persons - seen) if i in by_id]
        cut = bisect_right(initiative_ids, state.max_initiative_id or 0)
        titles = initiatives[cut:]
        seen = set(initiative_ids[cut:])
        names = self._initiative_by_id
        titles = titles + [
            names[i] for i in sorted(renamed_initiatives - seen) if i in names
        ]
        return Delta(persons=found, initiatives=titles)

    def _delta_rows(self):
        if self._delta_cache is None:
            conn = self._conn
            people = conn.execute(
                text(
                    "SELECT p.id, p.name, r.cnpq_url FROM persons p "
                    "LEFT JOIN researchers r ON r.id = p.id ORDER BY p.id"
                )
            ).fetchall()
            inits = conn.execute(
                text("SELECT id, name FROM initiatives ORDER BY id")
            ).fetchall()
            self._person_by_id = {r[0]: (r[1] or "", r[2]) for r in people}
            self._initiative_by_id = {r[0]: r[1] or "" for r in inits}
            self._delta_cache = (
                [(r[1] or "", r[2]) for r in people],
                [r[0] for r in people],
                [r[1] or "" for r in inits],
                [r[0] for r in inits],
            )
            self._renamed_cache = {}
        return self._delta_cache

    def _renamed_since(self, run_id):
        if run_id is None:
            return set(), set()
        self._delta_rows()
        if run_id not in self._renamed_cache:
            renamed = {"person": set(), "initiative": set(), "advisorship": set()}
            for etype, eid in self._conn.execute(
                text(
                    "SELECT canonical_entity_type, canonical_entity_id "
                    "FROM entity_change_logs WHERE operation = 'update' "
                    "AND ingestion_run_id > :run "
                    "AND changed_fields_json LIKE '%\"name\"%'"
                ),
                {"run": run_id},
            ):
                if etype in renamed:
                    renamed[etype].add(eid)
            self._renamed_cache[run_id] = (
                renamed["person"],
                renamed["initiative"] | renamed["advisorship"],
            )
        return self._renamed_cache[run_id]

    def target_keys(self, after_person_id: int = 0, after_initiative_id: int = 0):
        conn = self._conn
        rows = conn.execute(
            text("SELECT id, name FROM persons WHERE id > :m"),
            {"m": after_person_id},
        ).fetchall()
        persons = {person_reference_key(name) for _id, name in rows}
        max_person = max((r[0] for r in rows), default=after_person_id)
        rows = conn.execute(
            text("SELECT id, name FROM initiatives WHERE id > :m"),
            {"m": after_initiative_id},
        ).fetchall()
        initiatives = {initiative_reference_key(name) for _id, name in rows}
        max_initiative = max((r[0] for r in rows), default=after_initiative_id)
        return persons, initiatives, max_person, max_initiative

    def begin_document(self) -> None:
        self._tx.begin()

    def commit_document(self) -> None:
        self._delta_cache = None  # rows may have been added or renamed
        self._tx.commit()

    def rollback_document(self) -> None:
        self._delta_cache = None  # rows may have been added or renamed
        self._tx.rollback()

    def _stored_item_count(self, source_system: str, document_key: str) -> int:
        row = self._conn.execute(
            text(
                "SELECT item_count FROM source_document_states "
                "WHERE source_system = :s AND document_key = :k"
            ),
            {"s": source_system, "k": document_key},
        ).fetchone()
        return row[0] if row else 0

    def commit_processed(self, outcome: DocumentOutcome) -> list:
        """Writes the document's links, references and state inside its
        transaction, deleting the items it dropped (R6). Returns the
        deletions, for the change log."""
        s, k = outcome.source_system, outcome.document_key
        item_count = sum(1 for _t, _r, subject in outcome.items if not subject)
        stored_count = self._stored_item_count(s, k)
        if s in TOTAL_LOSS_SOURCES and item_count == 0 and stored_count > 0:
            raise DocumentFailed("total_loss", "no items left in a readable document")

        deletions = DocumentItemStore(lambda: self._conn).replace_items(
            s, k, outcome.items, stored_count
        )
        conn, now = self._conn, _now()
        conn.execute(
            text(
                "DELETE FROM source_document_references "
                "WHERE source_system = :s AND document_key = :k"
            ),
            {"s": s, "k": k},
        )
        if outcome.references:
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO source_document_references "
                    "(source_system, document_key, kind, lookup_key, outcome, score) "
                    "VALUES (:s, :k, :kind, :lookup, :outcome, :score)"
                ),
                [
                    {
                        "s": s,
                        "k": k,
                        "kind": r.kind,
                        "lookup": r.lookup_key,
                        "outcome": r.outcome,
                        "score": r.score,
                    }
                    for r in outcome.references
                ],
            )
        max_person = conn.execute(text("SELECT MAX(id) FROM persons")).scalar()
        max_initiative = conn.execute(text("SELECT MAX(id) FROM initiatives")).scalar()
        conn.execute(
            text(
                "INSERT INTO source_document_states (source_system, document_key, "
                "content_hash, dependency_fingerprint, rule_version, max_person_id, "
                "max_initiative_id, item_count, last_ingestion_run_id, processed_at, "
                "last_seen_at, status, last_failure, last_failure_at) VALUES "
                "(:s, :k, :h, :f, :v, :mp, :mi, :n, :run, :now, :now, :active, NULL, NULL) "
                "ON CONFLICT (source_system, document_key) DO UPDATE SET "
                "content_hash = :h, dependency_fingerprint = :f, rule_version = :v, "
                "max_person_id = :mp, max_initiative_id = :mi, item_count = :n, "
                "last_ingestion_run_id = :run, processed_at = :now, "
                "last_failure = NULL, last_failure_at = NULL"
            ),
            {
                "s": s,
                "k": k,
                "h": outcome.content_hash,
                "f": outcome.dependency_fingerprint,
                "v": outcome.rule_version,
                "mp": max_person,
                "mi": max_initiative,
                "n": item_count,
                "run": outcome.ingestion_run_id,
                "now": now,
                "active": ACTIVE,
            },
        )
        return deletions

    def record_failure(
        self, source_system: str, document_key: str, reason: str
    ) -> None:
        now = _now()
        self._conn.execute(
            text(
                "INSERT INTO source_document_states (source_system, document_key, "
                "rule_version, last_seen_at, status, last_failure, last_failure_at) "
                "VALUES (:s, :k, :v, :now, :active, :reason, :now) "
                "ON CONFLICT (source_system, document_key) DO UPDATE SET "
                "last_failure = :reason, last_failure_at = :now"
            ),
            {
                "s": source_system,
                "k": document_key,
                "v": self._rule_version,
                "now": now,
                "active": ACTIVE,
                "reason": reason,
            },
        )

    def clear_failure(self, source_system: str, document_key: str) -> None:
        self._conn.execute(
            text(
                "UPDATE source_document_states SET last_failure = NULL, "
                "last_failure_at = NULL WHERE source_system = :s AND document_key = :k"
            ),
            {"s": source_system, "k": document_key},
        )

    def mark_listing(
        self, source_system: str, listed_keys: Iterable[str], complete: bool
    ) -> ListingResult:
        keys = sorted(set(listed_keys))
        conn, now, result = self._conn, _now(), ListingResult(listed=len(keys))
        before = {
            row[0]: row[1]
            for row in conn.execute(
                text(
                    "SELECT document_key, status FROM source_document_states "
                    "WHERE source_system = :s"
                ),
                {"s": source_system},
            )
        }
        # A partial listing (campus filter, limit, unknown completeness) still
        # saw the listed documents, but changes no status (data model).
        status_update = ", status = :active" if complete else ""
        if complete:
            result.reactivated = sum(1 for k in keys if before.get(k) == INACTIVE)
        if keys:
            conn.execute(
                text(
                    "INSERT INTO source_document_states (source_system, document_key, "
                    "rule_version, last_seen_at, status) VALUES (:s, :k, :v, :now, :active) "
                    "ON CONFLICT (source_system, document_key) DO UPDATE SET "
                    "last_seen_at = :now" + status_update
                ),
                [
                    {
                        "s": source_system,
                        "k": k,
                        "v": self._rule_version,
                        "now": now,
                        "active": ACTIVE,
                    }
                    for k in keys
                ],
            )
        if complete:
            listed = set(keys)
            gone = [
                k
                for k, status in before.items()
                if status == ACTIVE and k not in listed
            ]
            if gone:
                conn.execute(
                    text(
                        "UPDATE source_document_states SET status = :inactive "
                        "WHERE source_system = :s AND document_key = :k"
                    ),
                    [{"s": source_system, "k": k, "inactive": INACTIVE} for k in gone],
                )
            result.newly_inactive = len(gone)
        return result


def read_document_states(db_path: str) -> List[dict]:
    """Status and dates of every document, for the export (contract
    source-document-states-export.md). Read-only, on a connection of its own:
    the export runs after the phases, outside any document transaction. Empty
    when the database predates spec 021."""
    import sqlite3

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'source_document_states'"
        ).fetchone()
        if not exists:
            return []
        rows = con.execute(
            "SELECT source_system, document_key, status, last_seen_at, processed_at "
            "FROM source_document_states ORDER BY source_system, document_key"
        ).fetchall()
    finally:
        con.close()
    fields = ("source_system", "document_key", "status", "last_seen_at", "processed_at")
    return [dict(zip(fields, row)) for row in rows]
