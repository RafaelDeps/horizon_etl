"""One database transaction per source document (spec 021, research R5).

``libbase`` and ``eo_lib`` commit inside every write, so the writes of one CV
or CNPq page are many small transactions, and a failure in the middle leaves
half of the document written. The libraries are not edited. Instead, while a
phase runs, the session factories of their two ``PostgresClient`` singletons
(``eo_lib`` and ``research_domain``) are bound to one connection in
``join_transaction_mode="create_savepoint"``: once the phase opens a
transaction on that connection, every library ``commit()`` only releases a
savepoint, and the document is committed or rolled back as a whole.

All writers must share the connection: SQLite has one write lock, and a second
connection would wait on it until ``database is locked``. The ETL's tracking
sessions join it through ``tracking_session()``.

``_SessionLocal`` is a private attribute of the libraries' client, so the
binding fails loudly if a library version renames it.
"""

import os
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from src.adapters.database.sqlite_settings import install_savepoint_support

_active: Optional["DocumentTransaction"] = None


def _library_clients() -> list:
    from eo_lib.infrastructure.database.postgres_client import (
        PostgresClient as EoLibClient,
    )

    clients = [EoLibClient()]
    try:
        from research_domain.infrastructure.database.postgres_client import (
            PostgresClient as ResearchDomainClient,
        )
    except ImportError:  # research_domain without its own client
        return clients
    clients.append(ResearchDomainClient())
    return clients


def active_connection():
    """The shared connection of the active ``DocumentTransaction``, or None."""
    return _active._connection if _active is not None else None


def tracking_session() -> Optional[Session]:
    """A session on the shared connection for the tracking services, or None
    when no ``DocumentTransaction`` is active (they then keep their own)."""
    if _active is None:
        return None
    return Session(
        bind=_active._connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )


class DocumentTransaction:
    """Binds the libraries' sessions to one connection for a phase and gives the
    phase ``begin``/``commit``/``rollback`` per document. Use ``close()`` (or the
    context manager) to restore the libraries' own session factories."""

    def __init__(self, database_url: Optional[str] = None):
        global _active
        if _active is not None:
            raise RuntimeError("A DocumentTransaction is already active")
        url = database_url or os.getenv("DATABASE_URL", "sqlite:///db/horizon.db")
        self._engine = create_engine(url)
        install_savepoint_support(self._engine)
        self._connection = self._engine.connect()
        self._factory = scoped_session(
            sessionmaker(
                bind=self._connection,
                join_transaction_mode="create_savepoint",
                autoflush=False,
                expire_on_commit=False,
            )
        )
        self._saved = []
        self._in_document = False
        try:
            for client in _library_clients():
                if not hasattr(client, "_SessionLocal"):
                    raise RuntimeError(
                        f"{type(client).__module__}.PostgresClient has no "
                        "_SessionLocal; the installed library version is not "
                        "supported by DocumentTransaction"
                    )
                original = client._SessionLocal
                if original is not None:
                    original.remove()
                self._saved.append((client, original))
                client._SessionLocal = self._factory
        except Exception:
            self._restore()
            self._connection.close()
            self._engine.dispose()
            raise
        # The connection is always inside a transaction, so every session that
        # joins it works on savepoints and none ever owns the real transaction.
        # It is committed only at document boundaries: what is written between
        # documents (the ingestion run, caches warmed by reads) is committed
        # when the next document starts.
        self._outer = self._connection.begin()
        _active = self

    @property
    def in_document(self) -> bool:
        return self._in_document

    @property
    def connection(self):
        return self._connection

    def _restart(self, commit: bool) -> None:
        if commit:
            self._outer.commit()
        else:
            self._outer.rollback()
        self._outer = self._connection.begin()

    def begin(self) -> None:
        if self._in_document:
            raise RuntimeError("A document transaction is already open")
        self._factory().commit()
        self._restart(commit=True)
        self._in_document = True

    def commit(self) -> None:
        if not self._in_document:
            return
        self._factory().commit()
        self._restart(commit=True)
        self._in_document = False

    def rollback(self) -> None:
        if not self._in_document:
            return
        try:
            self._factory().rollback()
        except Exception as exc:  # the outer rollback below is what matters
            logger.warning("Session rollback before document rollback failed: {}", exc)
        self._restart(commit=False)
        self._in_document = False
        # Objects loaded during the document describe rows that no longer exist.
        self._factory().expunge_all()

    def _restore(self) -> None:
        for client, original in self._saved:
            client._SessionLocal = original
        self._saved = []

    def close(self) -> None:
        global _active
        if self._in_document:
            self.rollback()
        self._factory().commit()
        self._outer.commit()
        self._factory.remove()
        self._restore()
        self._connection.close()
        self._engine.dispose()
        if _active is self:
            _active = None

    def __enter__(self) -> "DocumentTransaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
