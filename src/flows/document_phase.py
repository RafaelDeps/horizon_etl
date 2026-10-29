"""Wiring of a per-document phase (spec 021).

A phase that processes source documents one by one opens a ``document_phase``
before it creates any controller: the libraries' sessions are then bound to
the shared connection of the ``DocumentTransaction``, every document runs in
one transaction, and unchanged documents are skipped (contract
document-processing.md). The migrations run first, so a database kept from an
older version of the ETL has the state tables.
"""

import os
from contextlib import contextmanager
from typing import Optional

from loguru import logger

from src.adapters.database.document_state_store import SqliteDocumentStateStore
from src.adapters.database.document_transaction import DocumentTransaction
from src.core.logic.document_skip import DocumentSkip
from src.core.logic.horizon_identity import HORIZON_RULE_VERSION


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///db/horizon.db")


@contextmanager
def document_phase(source_system: str, database_url: Optional[str] = None):
    """Yields a ``DocumentSkip`` for ``source_system``; set its
    ``on_rollback`` to reload the phase's in-memory caches."""
    from src.flows.maintenance.horizon_ids import _run_migrations

    url = database_url or _database_url()
    _run_migrations(url)
    transaction = DocumentTransaction(url)
    try:
        store = SqliteDocumentStateStore(transaction, HORIZON_RULE_VERSION)
        skip = DocumentSkip(store, source_system)
        logger.info("Document states for {}: {} known", source_system, len(skip.states))
        yield skip
        skip.log_summary()
    finally:
        transaction.close()


@contextmanager
def document_phases(*source_systems: str, database_url: Optional[str] = None):
    """Like ``document_phase`` for a phase that reads several kinds of
    document (the SigPesq reports): one transaction, one skip per kind."""
    from src.flows.maintenance.horizon_ids import _run_migrations

    url = database_url or _database_url()
    _run_migrations(url)
    transaction = DocumentTransaction(url)
    try:
        store = SqliteDocumentStateStore(transaction, HORIZON_RULE_VERSION)
        skips = {s: DocumentSkip(store, s) for s in source_systems}
        yield skips
        for skip in skips.values():
            skip.log_summary()
    finally:
        transaction.close()


def finish_report_listing(skip: DocumentSkip, loader) -> None:
    """A SigPesq report is downloaded whole each run, so its rows are the
    listing of its documents (research R8). Complete only when every report
    file was read and gave at least one row; otherwise no status changes."""
    complete = bool(skip.seen) and not getattr(loader, "read_failures", 0)
    if not complete:
        logger.warning(
            "{}: report not read or empty, no document changes status",
            skip.source_system,
        )
    skip.finish(sorted(skip.seen), complete=complete)
