"""SQLite store of field claims and writer of the resolved values (branch 030).

Both run on the connection they are given: inside a phase it is the shared
connection of the ``DocumentTransaction``, so a document that fails is rolled
back with its claims and the values resolved from them.
"""

import json
from typing import Any, Callable, Dict, Iterable, List, Set

from sqlalchemy import text

from src.core.logic.field_merge import DATE_FIELDS, claim_value
from src.core.logic.pii_anonymizer import scrub_pii_deep
from src.core.ports.field_claim_store import (
    Entity,
    FieldClaim,
    IFieldClaimStore,
    IFieldWriter,
)

_INITIATIVE_COLUMNS = {
    f: "initiatives" for f in ("status", "description", "start_date", "end_date")
}
# Field -> table that holds it (an advisorship row spans both tables).
_TABLES = {
    "initiative": _INITIATIVE_COLUMNS,
    "advisorship": {**_INITIATIVE_COLUMNS, "cancelled": "advisorships"},
    "fellowship": {"value": "fellowships"},
}


def _by_table(entity_type: str, fields: Iterable[str]) -> Dict[str, List[str]]:
    tables: Dict[str, List[str]] = {}
    for f in fields:
        table = _TABLES[entity_type].get(f)
        if table:
            tables.setdefault(table, []).append(f)
    return tables


def _dump(field: str, value: Any) -> str:
    return json.dumps(
        scrub_pii_deep(claim_value(field, value)),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


class SqliteFieldClaimStore(IFieldClaimStore):
    def __init__(self, connection_getter: Callable[[], Any]):
        self._get = connection_getter

    def _fields_of(
        self, source_system: str, document_key: str
    ) -> Dict[Entity, Set[str]]:
        fields: Dict[Entity, Set[str]] = {}
        for row in self._get().execute(
            text(
                "SELECT entity_type, entity_id, field FROM source_field_claims "
                "WHERE source_system = :s AND document_key = :k"
            ),
            {"s": source_system, "k": document_key},
        ):
            fields.setdefault((row[0], int(row[1])), set()).add(row[2])
        return fields

    def replace_document_claims(
        self, source_system: str, document_key: str, claims: Iterable[FieldClaim]
    ) -> Dict[Entity, Set[str]]:
        conn = self._get()
        claims = list(claims)
        touched = self._fields_of(source_system, document_key)
        conn.execute(
            text(
                "DELETE FROM source_field_claims "
                "WHERE source_system = :s AND document_key = :k"
            ),
            {"s": source_system, "k": document_key},
        )
        rows = {}
        for c in claims:
            # One claim per document and field: the first one the document made.
            rows.setdefault(
                (c.entity_type, c.entity_id, c.field),
                {
                    "s": source_system,
                    "k": document_key,
                    "t": c.entity_type,
                    "i": c.entity_id,
                    "f": c.field,
                    "v": _dump(c.field, c.value),
                    "d": c.doc_date,
                    "r": c.source_rank,
                    "tie": c.tie_key,
                },
            )
            touched.setdefault((c.entity_type, c.entity_id), set()).add(c.field)
        if rows:
            conn.execute(
                text(
                    "INSERT INTO source_field_claims (source_system, document_key, "
                    "entity_type, entity_id, field, value_json, doc_date, "
                    "source_rank, tie_key) VALUES (:s, :k, :t, :i, :f, :v, :d, :r, :tie)"
                ),
                [rows[key] for key in sorted(rows)],
            )
        return touched

    def claims_for(self, entity_type: str, entity_id: int) -> List[FieldClaim]:
        return [
            FieldClaim(
                source_system=row[0],
                document_key=row[1],
                entity_type=entity_type,
                entity_id=entity_id,
                field=row[2],
                value=json.loads(row[3]) if row[3] is not None else None,
                doc_date=row[4],
                source_rank=row[5],
                tie_key=row[6],
            )
            for row in self._get().execute(
                text(
                    "SELECT source_system, document_key, field, value_json, doc_date, "
                    "source_rank, tie_key FROM source_field_claims "
                    "WHERE entity_type = :t AND entity_id = :i"
                ),
                {"t": entity_type, "i": entity_id},
            )
        ]

    def move_claims(self, entity_type: str, from_id: int, to_id: int) -> None:
        conn = self._get()
        params = {"t": entity_type, "a": from_id, "b": to_id}
        conn.execute(
            text(
                "UPDATE OR IGNORE source_field_claims SET entity_id = :b "
                "WHERE entity_type = :t AND entity_id = :a"
            ),
            params,
        )
        conn.execute(
            text(
                "DELETE FROM source_field_claims "
                "WHERE entity_type = :t AND entity_id = :a"
            ),
            params,
        )


def _stored_date(value: Any) -> Any:
    """The format the ORM stores datetimes in on SQLite."""
    iso = claim_value("start_date", value)
    return f"{iso} 00:00:00.000000" if iso else None


class SqliteFieldWriter(IFieldWriter):
    def __init__(self, connection_getter: Callable[[], Any]):
        self._get = connection_getter

    def read(self, entity_type: str, entity_id: int, fields: Iterable[str]) -> dict:
        stored = {}
        for table, columns in _by_table(entity_type, fields).items():
            row = (
                self._get()
                .execute(
                    text(f"SELECT {', '.join(columns)} FROM {table} WHERE id = :i"),
                    {"i": entity_id},
                )
                .mappings()
                .fetchone()
            )
            if not row:
                return {}  # the row is gone (deleted with its document)
            stored.update(row)
        return stored

    def write(self, entity_type: str, entity_id: int, values: dict) -> None:
        for table, columns in _by_table(entity_type, values).items():
            row = {
                f: (_stored_date(values[f]) if f in DATE_FIELDS else values[f])
                for f in columns
            }
            assignments = ", ".join(f"{f} = :{f}" for f in sorted(row))
            self._get().execute(
                text(f"UPDATE {table} SET {assignments} WHERE id = :_id"),
                {**row, "_id": entity_id},
            )
