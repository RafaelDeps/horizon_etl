"""The fixed rule for fields written by several documents (branch 030)."""

import itertools

import pytest

from src.core.logic.field_merge import (
    FieldMergeApplier,
    FieldMergeStats,
    claim_sort_key,
    claim_value,
    is_empty,
    lattes_document_date,
    lattes_source,
    project_file_source,
    resolve,
    sigpesq_source,
)
from src.core.ports.field_claim_store import FieldClaim, IFieldClaimStore, IFieldWriter


def _claim(value, *, field="description", source=None, key="doc", entity_id=1):
    doc_date, rank, tie = source or lattes_source("2026-01-01", "0000000000000001")
    return FieldClaim(
        source_system="test",
        document_key=key,
        entity_type="initiative",
        entity_id=entity_id,
        field=field,
        value=value,
        doc_date=doc_date,
        source_rank=rank,
        tie_key=tie,
    )


LATTES_OLD = lattes_source("2026-03-10", "0000000000000009")
LATTES_NEW = lattes_source("2026-09-02", "0000000000000005")
LATTES_NEW_LOW_ID = lattes_source("2026-09-02", "0000000000000001")
SIGPESQ_4882 = sigpesq_source(4882)
SIGPESQ_5120 = sigpesq_source(5120)
PDF = project_file_source("PJ 2342")


def test_a_dated_claim_beats_an_undated_one():
    assert claim_sort_key(_claim("a", source=LATTES_OLD)) < claim_sort_key(
        _claim("b", source=SIGPESQ_5120)
    )


def test_the_later_date_wins():
    assert claim_sort_key(_claim("a", source=LATTES_NEW)) < claim_sort_key(
        _claim("b", source=LATTES_OLD)
    )


def test_at_the_same_date_the_lowest_lattes_id_wins():
    assert claim_sort_key(_claim("a", source=LATTES_NEW_LOW_ID)) < claim_sort_key(
        _claim("b", source=LATTES_NEW)
    )


def test_at_no_date_lattes_beats_sigpesq():
    undated_lattes = lattes_source(None, "0000000000000001")
    assert claim_sort_key(_claim("a", source=undated_lattes)) < claim_sort_key(
        _claim("b", source=SIGPESQ_5120)
    )


def test_the_highest_sigpesq_id_wins():
    assert claim_sort_key(_claim("a", source=SIGPESQ_5120)) < claim_sort_key(
        _claim("b", source=SIGPESQ_4882)
    )


def test_a_sigpesq_report_row_beats_the_pdf():
    assert claim_sort_key(_claim("a", source=SIGPESQ_4882)) < claim_sort_key(
        _claim("b", source=PDF)
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("description", None),
        ("description", ""),
        ("description", "   "),
        ("status", "Unknown"),
        ("status", "unknown"),
        ("value", 0),
        ("value", 0.0),
        ("start_date", None),
    ],
)
def test_empty_values(field, value):
    assert is_empty(field, value)


@pytest.mark.parametrize(
    "field, value",
    [("description", "x"), ("status", "Active"), ("value", 600)],
)
def test_filled_values(field, value):
    assert not is_empty(field, value)


def test_an_empty_claim_never_wins():
    result = resolve(
        [
            _claim(None, source=LATTES_NEW),
            _claim("from sigpesq", source=SIGPESQ_4882),
        ]
    )
    assert result["description"].value == "from sigpesq"
    assert result["description"].decided_by == "single"


def test_all_empty_claims_resolve_nothing():
    assert resolve([_claim(None), _claim("  ", source=SIGPESQ_4882)]) == {}


def test_values_that_differ_only_in_spaces_or_case_are_one_value():
    result = resolve(
        [
            _claim("Projeto  X", source=LATTES_OLD),
            _claim("projeto x", source=LATTES_NEW),
        ]
    )
    assert result["description"].value == "projeto x"
    assert result["description"].decided_by == "single"


def test_decided_by_date():
    result = resolve(
        [_claim("old", source=LATTES_OLD), _claim("new", source=LATTES_NEW)]
    )
    assert (result["description"].value, result["description"].decided_by) == (
        "new",
        "by_date",
    )


def test_a_dated_claim_over_an_undated_one_is_decided_by_date():
    result = resolve(
        [_claim("lattes", source=LATTES_OLD), _claim("sigpesq", source=SIGPESQ_5120)]
    )
    assert result["description"].decided_by == "by_date"


def test_decided_by_source():
    undated_lattes = lattes_source(None, "0000000000000001")
    result = resolve(
        [
            _claim("lattes", source=undated_lattes),
            _claim("sigpesq", source=SIGPESQ_5120),
        ]
    )
    assert (result["description"].value, result["description"].decided_by) == (
        "lattes",
        "by_source",
    )


def test_decided_by_tiebreak():
    result = resolve(
        [_claim("a", source=SIGPESQ_4882), _claim("b", source=SIGPESQ_5120)]
    )
    assert (result["description"].value, result["description"].decided_by) == (
        "b",
        "by_tiebreak",
    )


def test_every_order_gives_the_same_result():
    claims = [
        _claim("old cv", source=LATTES_OLD, key="1"),
        _claim("new cv", source=LATTES_NEW, key="2"),
        _claim("row", source=SIGPESQ_4882, key="3"),
        _claim("pdf", source=PDF, key="4"),
        _claim("Active", field="status", source=SIGPESQ_4882, key="3"),
        _claim("Unknown", field="status", source=LATTES_NEW, key="2"),
    ]
    results = {
        tuple(sorted((f, r.value, r.decided_by) for f, r in resolve(list(p)).items()))
        for p in itertools.permutations(claims)
    }
    assert results == {
        (("description", "new cv", "by_date"), ("status", "Active", "single"))
    }


def test_lattes_document_date():
    cv = {"informacoes_pessoais": {"atualizacao_cv": "30/10/2026"}}
    assert lattes_document_date(cv) == "2026-10-30"


@pytest.mark.parametrize(
    "cv",
    [
        {},
        {"informacoes_pessoais": {}},
        {"informacoes_pessoais": {"atualizacao_cv": "ontem"}},
        {"informacoes_pessoais": {"atualizacao_cv": "31/02/2026"}},
        None,
    ],
)
def test_a_missing_or_unreadable_cv_date_is_none(cv):
    assert lattes_document_date(cv) is None


class _Store(IFieldClaimStore):
    def __init__(self, claims):
        self.claims = claims

    def replace_document_claims(self, source_system, document_key, claims):
        raise NotImplementedError

    def claims_for(self, entity_type, entity_id):
        return [
            c
            for c in self.claims
            if c.entity_type == entity_type and c.entity_id == entity_id
        ]

    def move_claims(self, entity_type, from_id, to_id):
        raise NotImplementedError


class _Writer(IFieldWriter):
    def __init__(self, stored):
        self.stored = stored
        self.writes = []

    def read(self, entity_type, entity_id, fields):
        return {f: self.stored.get(f) for f in fields}

    def write(self, entity_type, entity_id, values):
        self.writes.append(values)
        self.stored.update(values)


def test_the_applier_writes_only_what_changes():
    store = _Store(
        [
            _claim("new", source=LATTES_NEW),
            _claim("2022-08-01", field="start_date", source=LATTES_NEW),
        ]
    )
    writer = _Writer({"description": "old", "start_date": "2022-08-01 00:00:00.000000"})
    stats = FieldMergeStats()
    assert FieldMergeApplier(store, writer, stats).apply([("initiative", 1)]) == 1
    assert writer.writes == [{"description": "new"}]
    assert FieldMergeApplier(store, writer, stats).apply([("initiative", 1)]) == 0


def test_the_applier_keeps_a_value_no_claim_fills():
    store = _Store([_claim(None, field="status", source=LATTES_NEW)])
    writer = _Writer({"status": "Active"})
    assert (
        FieldMergeApplier(store, writer, FieldMergeStats()).apply([("initiative", 1)])
        == 0
    )
    assert writer.stored["status"] == "Active"


def test_stats_count_each_field_once_per_phase():
    store = _Store([_claim("old", source=LATTES_OLD), _claim("new", source=LATTES_NEW)])
    writer = _Writer({"description": "old"})
    stats = FieldMergeStats()
    applier = FieldMergeApplier(store, writer, stats)
    applier.apply([("initiative", 1)])
    applier.apply([("initiative", 1)])
    assert stats.counts() == {
        "fields": 1,
        "by_date": 1,
        "by_source": 0,
        "by_tiebreak": 0,
        "collisions_resolved": 0,
        "collisions_reported": 0,
    }


def test_the_applier_resolves_only_the_claimed_fields():
    store = _Store(
        [
            _claim("new", source=LATTES_NEW),
            _claim("Active", field="status", source=LATTES_NEW),
        ]
    )
    writer = _Writer({"description": "old", "status": "Concluded"})
    applier = FieldMergeApplier(store, writer, FieldMergeStats())
    assert applier.apply({("initiative", 1): {"description"}}) == 1
    assert writer.stored == {"description": "new", "status": "Concluded"}


@pytest.mark.parametrize("stored", [0, False, "0"])
def test_a_stored_flag_and_a_claimed_flag_compare_as_booleans(stored):
    assert claim_value("cancelled", stored) is False
    assert claim_value("cancelled", 1) is True
    assert not is_empty("cancelled", False)


def test_the_newest_workplan_decides_cancelled():
    result = resolve(
        [
            _claim(True, field="cancelled", source=SIGPESQ_4882),
            _claim(False, field="cancelled", source=SIGPESQ_5120),
        ]
    )
    assert (result["cancelled"].value, result["cancelled"].decided_by) == (
        False,
        "by_tiebreak",
    )
