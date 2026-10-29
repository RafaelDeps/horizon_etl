"""Shared pytest configuration for the Horizon ETL test suite."""

import os

# Default test-only HMAC key for the LGPD PII anonymizer. Real runs load
# HORIZON_PII_HMAC_KEY from .env (app.py / flows); tests must not depend on
# machine-local secrets. Individual test modules may override it explicitly.
TEST_HMAC_KEY = "test-only-horizon-pii-hmac-key"


def pytest_configure(config) -> None:
    os.environ.setdefault("HORIZON_PII_HMAC_KEY", TEST_HMAC_KEY)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_rule_version_reset(monkeypatch, tmp_path_factory):
    """run_weekly may rebuild DATABASE_URL when its rule version differs
    (spec 020, FR-024). Tests fake the phases: never let that touch the
    repository's db/horizon.db. Yields the real guard for the tests of it."""
    import src.flows.pipelines.weekly_orchestrator as orchestrator

    real = orchestrator._reset_if_rule_version_changed
    monkeypatch.setattr(orchestrator, "_reset_if_rule_version_changed", lambda: None)
    # Spec 021: the migrations run at weekly start; same protection.
    monkeypatch.setattr(orchestrator, "_run_pending_migrations", lambda: None)
    # Spec 021: the phases' report goes to the test's own folder.
    import src.core.logic.document_skip as document_skip

    monkeypatch.setattr(
        document_skip,
        "REPORT_PATH",
        str(tmp_path_factory.mktemp("reports") / "source_document_states_report.json"),
    )
    # run_weekly sets the weekly start for its phases; restored after the test.
    monkeypatch.setenv("HORIZON_WEEKLY_STARTED_AT", "")
    yield real


# Flow modules that open a ``document_phase`` (spec 021). Tests call these flows
# in-process with mocked controllers; the real document_phase would migrate and
# open DATABASE_URL (the repository's db/horizon.db). Tests of the real thing
# run in subprocesses on temporary databases and are not affected.
DOCUMENT_PHASE_MODULES = (
    "src.flows.lattes.projects",
    "src.flows.lattes.advisorships",
    "src.flows.cnpq.groups",
    "src.flows.sigpesq.groups",
    "src.flows.sigpesq.projects",
    "src.flows.sigpesq.advisorships",
    "src.flows.sigpesq.enrich_projects",
)


class _MemoryDocumentStore:
    """A document state store that keeps nothing: every document is new."""

    def load(self, source_system):
        return {}

    def references(self, source_system, document_key):
        return []

    def delta(self, state):
        from src.core.ports.document_state_store import Delta

        return Delta()

    def target_keys(self, after_person_id=0, after_initiative_id=0):
        return set(), set(), 0, 0

    def begin_document(self):
        pass

    def commit_document(self):
        pass

    def rollback_document(self):
        pass

    def commit_processed(self, outcome):
        pass

    def record_failure(self, source_system, document_key, reason):
        pass

    def clear_failure(self, source_system, document_key):
        pass

    def mark_listing(self, source_system, listed_keys, complete):
        from src.core.ports.document_state_store import ListingResult

        return ListingResult(listed=len(list(listed_keys)))


@pytest.fixture(autouse=True)
def _no_real_document_phase(monkeypatch):
    import importlib
    from contextlib import contextmanager

    from src.core.logic.document_skip import DocumentSkip

    @contextmanager
    def memory_phase(source_system, database_url=None):
        yield DocumentSkip(_MemoryDocumentStore(), source_system)

    @contextmanager
    def memory_phases(*source_systems, database_url=None):
        store = _MemoryDocumentStore()
        yield {s: DocumentSkip(store, s) for s in source_systems}

    # The parent-project recalculation (spec 021) writes DATABASE_URL too; the
    # in-process pipelines call it after their (mocked) source steps.
    for name in ("src.flows.pipelines.weekly", "src.flows.pipelines.unified"):
        module = importlib.import_module(name)
        monkeypatch.setattr(
            module, "recalculate_parent_projects_flow", lambda *a, **k: None
        )

    for name in DOCUMENT_PHASE_MODULES:
        module = importlib.import_module(name)
        if hasattr(module, "document_phase"):
            monkeypatch.setattr(module, "document_phase", memory_phase)
        if hasattr(module, "document_phases"):
            monkeypatch.setattr(module, "document_phases", memory_phases)
    yield
