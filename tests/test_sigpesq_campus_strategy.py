"""Campus name resolution must never invent a second record for one campus.

The SigPesq advisorship report's ``Campus`` column arrives unnormalized —
"Serra", "Campus Serra", "serra", "Serra " all appear — and the strategy's
fallback path creates whatever it fails to find. Left unguarded, one dirty
spelling silently adds a 24th organizational unit.
"""

import pytest

from src.core.logic.strategies.sigpesq_excel import SigPesqCampusStrategy
from tests.conftest import FakeCampusController


@pytest.fixture
def strategy() -> SigPesqCampusStrategy:
    return SigPesqCampusStrategy()


@pytest.fixture
def serra(campus_db, campus_session):
    campus_id = campus_db.campus("Serra")
    campus_db.campus("Vitória")
    campus_db.commit()
    return campus_id


@pytest.mark.parametrize(
    "stated_name",
    [
        "Serra",
        "serra",
        "SERRA",
        "Serra ",
        " Serra",
        "Campus Serra",
        "campus serra",
        "Câmpus Serra",
        "Campus  Serra",
    ],
)
def test_dirty_spellings_resolve_to_the_same_campus(
    strategy, campus_ctrl, serra, stated_name
):
    resolved = strategy.ensure(campus_ctrl, stated_name, org_id=1)

    assert resolved == serra
    assert (
        campus_ctrl.created == []
    ), f"{stated_name!r} created a duplicate campus instead of matching Serra"


def test_accented_name_matches_its_unaccented_spelling(strategy, campus_ctrl, serra):
    assert strategy.ensure(campus_ctrl, "Vitoria", org_id=1) is not None
    assert campus_ctrl.created == []


def test_genuinely_new_campus_is_still_created(strategy, campus_ctrl, serra):
    resolved = strategy.ensure(campus_ctrl, "Nova Venécia", org_id=1)

    assert resolved is not None
    assert campus_ctrl.created == ["Nova Venécia"]


def test_campus_word_alone_is_not_treated_as_a_campus_name(
    strategy, campus_ctrl, serra
):
    """Stripping the prefix must not leave an empty name that matches anything."""
    resolved = strategy.ensure(campus_ctrl, "Campus", org_id=1)

    assert resolved != serra


def test_lookup_failure_does_not_propagate(strategy, campus_session, serra):
    controller = FakeCampusController(campus_session, raise_on_get_all=True)

    resolved = strategy.ensure(controller, "Serra", org_id=1)

    # get_all blew up, so the strategy falls through to creation; the point is
    # that it returns rather than raising into the ingestion loop.
    assert resolved is not None
