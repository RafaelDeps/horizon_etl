"""Spec 021: DocumentSkip decides per document whether to skip, process or
fail, with a fake in-memory store (no database)."""

from src.core.logic.document_skip import DocumentSkip, carry, mark_partial
from src.core.ports.document_state_store import (
    ACTIVE,
    DocumentFailed,
    DocumentState,
    IDocumentStateStore,
    ListingResult,
)
from src.tracking.recorder import stable_hash


class FakeStore(IDocumentStateStore):
    def __init__(self, states=None):
        self.states = dict(states or {})
        self.log = []

    def load(self, source_system):
        return dict(self.states)

    def references(self, source_system, document_key):
        return []

    def delta(self, state):
        from src.core.ports.document_state_store import Delta

        return Delta()

    def target_keys(self, after_person_id=0, after_initiative_id=0):
        return set(), set(), 0, 0

    def begin_document(self):
        self.log.append("begin")

    def commit_document(self):
        self.log.append("commit")

    def rollback_document(self):
        self.log.append("rollback")

    def commit_processed(self, outcome):
        self.log.append(("processed", outcome.document_key, outcome.content_hash))
        self.last_outcome = outcome

    def record_failure(self, source_system, document_key, reason):
        self.log.append(("failure", document_key, reason))

    def clear_failure(self, source_system, document_key):
        self.log.append(("clear", document_key))

    def mark_listing(self, source_system, listed_keys, complete):
        return ListingResult(listed=len(list(listed_keys)))


def _state(key, content, rule_version=1):
    return DocumentState(
        source_system="lattes_projects",
        document_key=key,
        content_hash=stable_hash(content),
        dependency_fingerprint=None,
        rule_version=rule_version,
        max_person_id=None,
        max_initiative_id=None,
        item_count=0,
        last_ingestion_run_id=None,
        processed_at="2026-10-28T00:00:00Z",
        last_seen_at="2026-10-28T00:00:00Z",
        status=ACTIVE,
    )


def _process(skip, key, content, work=None):
    with skip.document(key) as doc:
        if doc.unchanged(content):
            return
        doc.begin()
        if work:
            work(doc)


def test_first_sight_is_processed_in_one_transaction():
    store = FakeStore()
    skip = DocumentSkip(store, "lattes_projects", rule_version=1)
    _process(skip, "1", {"nome": "Ana"})
    assert store.log == [
        "begin",
        ("processed", "1", stable_hash({"nome": "Ana"})),
        "commit",
    ]
    assert skip.summary()["processed"] == 1


def test_same_content_and_rules_is_skipped_without_any_store_write():
    content = {"nome": "Ana", "artigos": [1, 2]}
    store = FakeStore({"1": _state("1", content)})
    skip = DocumentSkip(store, "lattes_projects", rule_version=1)
    _process(skip, "1", {"artigos": [1, 2], "nome": "Ana"})  # key order differs
    assert store.log == []
    assert skip.summary()["skipped"] == 1


def test_changed_content_or_rule_version_is_processed():
    store = FakeStore(
        {"1": _state("1", {"nome": "Ana"}), "2": _state("2", {"x": 1}, 0)}
    )
    skip = DocumentSkip(store, "lattes_projects", rule_version=1)
    _process(skip, "1", {"nome": "Ana Maria"})
    _process(skip, "2", {"x": 1})
    assert skip.summary()["processed"] == 2


def test_an_exception_rolls_back_calls_on_rollback_and_counts_partial():
    calls = []
    store = FakeStore()
    skip = DocumentSkip(store, "lattes_projects", on_rollback=lambda: calls.append(1))

    def boom(doc):
        raise ValueError("awards section")

    _process(skip, "1", {"nome": "Ana"}, boom)
    assert store.log == ["begin", "rollback", ("failure", "1", "partial")]
    assert calls == [1]
    assert skip.summary()["failed_by_reason"] == {"partial": 1}


def test_mark_partial_from_swallowed_errors_fails_the_document():
    store = FakeStore()
    skip = DocumentSkip(store, "lattes_projects")
    _process(skip, "1", {"nome": "Ana"}, lambda doc: mark_partial("languages failed"))
    assert "commit" not in store.log
    assert ("failure", "1", "partial") in store.log


def test_document_failed_before_begin_writes_only_the_failure_record():
    store = FakeStore()
    skip = DocumentSkip(store, "lattes_projects")
    with skip.document("1"):
        raise DocumentFailed("unidentified", "Nome-nao-identificado")
    assert store.log == [("failure", "1", "unidentified")]
    summary = skip.summary()
    assert summary["failed_by_reason"] == {"unidentified": 1}
    assert summary["failures"][0]["document_key"] == "1"


def test_total_loss_raised_by_the_store_rolls_back():
    class LossStore(FakeStore):
        def commit_processed(self, outcome):
            raise DocumentFailed("total_loss")

    store = LossStore()
    skip = DocumentSkip(store, "lattes_projects")
    _process(skip, "1", {"nome": "Ana"})
    assert store.log == ["begin", "rollback", ("failure", "1", "total_loss")]


def test_carried_items_and_subject_flag_reach_the_outcome():
    store = FakeStore()
    skip = DocumentSkip(store, "lattes_projects")

    def work(doc):
        carry("researcher", 7, is_subject=True)
        carry("article", 10)
        carry("article", 10)

    _process(skip, "1", {"nome": "Ana"}, work)
    assert store.last_outcome.items == [
        ("article", "10", False),
        ("researcher", "7", True),
    ]


def test_carry_outside_a_document_does_nothing():
    carry("article", 1)
    mark_partial("nothing open")


# --- research R3: references of an unchanged document --------------------


class RefStore(FakeStore):
    def __init__(self, states, refs, targets, delta):
        super().__init__(states)
        self._refs, self._targets_value, self._delta = refs, targets, delta

    def references(self, source_system, document_key):
        return self._refs

    def target_keys(self, after_person_id=0, after_initiative_id=0):
        persons, initiatives = self._targets_value
        return set(persons), set(initiatives), 0, 0

    def delta(self, state):
        return self._delta


def _skip_with(refs, targets, delta):
    from src.core.logic.document_skip import DocumentSkip

    content = {"nome": "Ana"}
    store = RefStore({"1": _state("1", content)}, refs, targets, delta)
    skip = DocumentSkip(store, "lattes_projects", rule_version=1)
    _process(skip, "1", content)
    return skip.summary()


def _refs():
    from src.core.ports.document_state_store import Reference

    return [
        Reference("person_name", "MARIA DA SILVA", "person:h:aaaaaaaaaaaa"),
        Reference("initiative", "|title:projeto x", "initiative:h:bbbbbbbbbbbb"),
    ]


def test_unchanged_document_with_intact_references_is_skipped():
    from src.core.ports.document_state_store import Delta

    targets = ({"person:h:aaaaaaaaaaaa"}, {"initiative:h:bbbbbbbbbbbb"})
    delta = Delta(persons=[("Joao Pereira", None)], initiatives=["Outro Projeto"])
    assert _skip_with(_refs(), targets, delta)["skipped"] == 1


def test_a_target_that_no_longer_exists_reprocesses_the_document():
    from src.core.ports.document_state_store import Delta

    targets = (set(), {"initiative:h:bbbbbbbbbbbb"})  # the person was merged away
    assert _skip_with(_refs(), targets, Delta())["processed"] == 1


def test_a_new_similar_person_reprocesses_the_document():
    from src.core.ports.document_state_store import Delta

    targets = ({"person:h:aaaaaaaaaaaa"}, {"initiative:h:bbbbbbbbbbbb"})
    delta = Delta(persons=[("Maria da Silva", None)])
    assert _skip_with(_refs(), targets, delta)["processed"] == 1
    delta = Delta(persons=[("Maria da Sylva", None)])  # fuzzy, above the threshold
    assert _skip_with(_refs(), targets, delta)["processed"] == 1
    delta = Delta(
        persons=[("Maria Silva", None)]
    )  # score 88: the matcher would not match
    assert _skip_with(_refs(), targets, delta)["skipped"] == 1


def test_a_new_initiative_with_the_same_title_reprocesses_the_document():
    from src.core.ports.document_state_store import Delta

    targets = ({"person:h:aaaaaaaaaaaa"}, {"initiative:h:bbbbbbbbbbbb"})
    delta = Delta(initiatives=["PROJETO X"])
    assert _skip_with(_refs(), targets, delta)["processed"] == 1


def test_a_new_researcher_with_the_cv_lattes_id_reprocesses_the_document():
    from src.core.ports.document_state_store import Delta, Reference

    refs = [
        Reference("researcher_owner", "ANA SOUZA|lattes:1234567890123456", "not_found")
    ]
    delta = Delta(persons=[("Outro Nome", "http://lattes.cnpq.br/1234567890123456")])
    assert _skip_with(refs, (set(), set()), delta)["processed"] == 1


def test_a_name_resolved_to_a_person_of_that_very_name_ignores_new_persons():
    """A lookup that resolved to a person or initiative of the same name came
    from an exact match, which a person or initiative created since cannot
    change: after a rebuild, the documents processed first are not processed
    again because of everything created after them."""
    from src.core.logic.horizon_identity import (
        initiative_reference_key,
        person_reference_key,
    )
    from src.core.ports.document_state_store import Delta, Reference

    person = person_reference_key("MARIA DA SILVA")
    initiative = initiative_reference_key("projeto x")
    refs = [
        Reference("person_name", "MARIA DA SILVA", person),
        Reference("initiative", "|title:projeto x", initiative),
    ]
    targets = ({person}, {initiative})
    delta = Delta(persons=[("Maria da Sylva", None)], initiatives=["PROJETO X"])
    assert _skip_with(refs, targets, delta)["skipped"] == 1


def test_the_phase_report_keeps_one_entry_per_phase(tmp_path, monkeypatch):
    import json

    from src.core.logic import document_skip

    path = tmp_path / "reports" / "source_document_states_report.json"
    monkeypatch.setattr(document_skip, "REPORT_PATH", str(path))
    for source in ("lattes_projects", "cnpq_group", "lattes_projects"):
        skip = DocumentSkip(FakeStore(), source)
        with skip.document("k1"):
            raise DocumentFailed("download", "no page")
        skip.log_summary()
    report = json.loads(path.read_text())
    assert sorted(report["phases"]) == ["cnpq_group", "lattes_projects"]
    entry = report["phases"]["lattes_projects"]
    assert entry["failed"] == 1
    assert entry["failures"] == [
        {"document_key": "k1", "reason": "download", "detail": "no page"}
    ]


def test_an_unchanged_document_read_again_clears_its_old_failure():
    from dataclasses import replace

    content = {"nome": "Ana"}
    state = replace(_state("1", content), last_failure="download")
    store = FakeStore({"1": state})
    skip = DocumentSkip(store, "lattes_projects", rule_version=1)
    _process(skip, "1", content)
    assert skip.summary()["skipped"] == 1
    assert store.log == [("clear", "1")]


def test_order_free_content_hashes_the_same_in_any_list_order():
    from src.core.logic.document_skip import order_free

    a = {"equipamentos": {"items": [["b", 1], ["a", 2]]}, "nome": "G"}
    b = {"nome": "G", "equipamentos": {"items": [["a", 2], ["b", 1]]}}
    assert stable_hash(order_free(a)) == stable_hash(order_free(b))
    assert stable_hash(order_free(a)) != stable_hash(order_free({"nome": "H"}))
