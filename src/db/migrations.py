"""Minimal, dependency-free schema migrations for the canonical SQLite database.

The project does not (yet) use Alembic. This module keeps schema changes out of
business logic: each migration is applied at most once and recorded in a
``schema_migrations`` table. ``ALTER TABLE ... ADD COLUMN`` is guarded so it is
idempotent even against databases where the column was already added by the
previous runtime-DDL stopgap.

Run at pipeline/app start, or lazily via ``ProjectEnrichmentLoader.ensure_schema``.
"""

from typing import List, Tuple

from loguru import logger
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

# (id, SQL). Order matters; ids are immutable once shipped.
MIGRATIONS: List[Tuple[str, str]] = [
    (
        "0001_initiatives_enrichment_json",
        "ALTER TABLE initiatives ADD COLUMN enrichment_json TEXT",
    ),
    # Spec 020: ETL-owned identity tables. They sit beside the eo_lib tables and
    # never alter them, so consumers of the existing schema see no change.
    (
        "0002_horizon_ids",
        "CREATE TABLE IF NOT EXISTS horizon_ids ("
        " entity_type TEXT NOT NULL,"
        " entity_id INTEGER NOT NULL,"
        " horizon_id TEXT NOT NULL UNIQUE,"
        " rule TEXT NOT NULL,"
        " natural_key TEXT,"
        " parent_horizon_id TEXT,"
        " collision_suffix TEXT,"
        " assigned_at TEXT NOT NULL,"
        " UNIQUE (entity_type, entity_id))",
    ),
    (
        "0003_horizon_id_candidates",
        "CREATE TABLE IF NOT EXISTS horizon_id_candidates ("
        " horizon_id TEXT NOT NULL,"
        " candidate_id TEXT NOT NULL,"
        " PRIMARY KEY (candidate_id, horizon_id))",
    ),
    (
        "0004_horizon_id_aliases",
        "CREATE TABLE IF NOT EXISTS horizon_id_aliases ("
        " alias_horizon_id TEXT PRIMARY KEY,"
        " horizon_id TEXT,"
        " reason TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL)",
    ),
    (
        "0005_horizon_merge_log",
        "CREATE TABLE IF NOT EXISTS horizon_merge_log ("
        " id INTEGER PRIMARY KEY,"
        " entity_type TEXT NOT NULL,"
        " loser_candidate_ids TEXT NOT NULL,"
        " winner_entity_id INTEGER NOT NULL,"
        " ingestion_run_id INTEGER,"
        " merged_at TEXT NOT NULL,"
        " consumed_at TEXT)",
    ),
    (
        "0006_horizon_meta",
        "CREATE TABLE IF NOT EXISTS horizon_meta ("
        " key TEXT PRIMARY KEY,"
        " value TEXT NOT NULL)",
    ),
    (
        "0007_team_member_contributions",
        "CREATE TABLE IF NOT EXISTS team_member_contributions ("
        " team_id INTEGER NOT NULL,"
        " person_id INTEGER NOT NULL,"
        " role_id INTEGER NOT NULL,"
        " document_key TEXT NOT NULL,"
        " start_date TEXT,"
        " PRIMARY KEY (team_id, person_id, role_id, document_key))",
    ),
]


def _applied_ids(session) -> set:
    session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(id TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    return {row[0] for row in session.execute(text("SELECT id FROM schema_migrations"))}


def run_migrations(session) -> int:
    """Applies pending migrations. Returns the number applied. Commits its own work."""
    applied = _applied_ids(session)
    count = 0
    for migration_id, sql in MIGRATIONS:
        if migration_id in applied:
            continue
        try:
            session.execute(text(sql))
        except OperationalError as exc:
            # ADD COLUMN on an already-migrated DB (legacy runtime DDL) is fine.
            if "duplicate column" not in str(exc).lower():
                session.rollback()
                raise
        session.execute(
            text("INSERT OR IGNORE INTO schema_migrations (id) VALUES (:id)"),
            {"id": migration_id},
        )
        count += 1
        logger.info("Applied migration {}", migration_id)
    session.commit()
    return count
