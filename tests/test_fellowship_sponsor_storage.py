"""How the domain library stores the sponsor of a new fellowship (spec 036).

Research R5 read the cause of the duplicate "JTC" fellowship from the
library's code: ``Fellowship.__init__`` sets ``sponsor_id`` and then assigns
the ``sponsor`` relationship, which is ``None`` when only the id is given, and
that clears the foreign key when the row is written. These tests see it on a
real (in-memory) database, and see that setting ``sponsor_id`` again after the
row exists stores it, which is what the handler does.
"""

import pytest
from eo_lib.domain.base import Base
from research_domain.domain.entities import Fellowship
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(text("INSERT INTO organizations (id, name) VALUES (3, 'CNPq')"))
        db.commit()
        yield db


def _stored_sponsor(session, fellowship_id):
    return session.execute(
        text("SELECT sponsor_id FROM fellowships WHERE id = :id"),
        {"id": fellowship_id},
    ).scalar()


def test_a_new_fellowship_built_with_a_sponsor_id_is_stored_without_it(session):
    fellowship = Fellowship(name="JTC", value=0.0, sponsor_id=3)
    session.add(fellowship)
    session.commit()

    assert _stored_sponsor(session, fellowship.id) is None


def test_the_sponsor_set_after_the_fellowship_exists_is_stored(session):
    fellowship = Fellowship(name="JTC", value=0.0, sponsor_id=3)
    session.add(fellowship)
    session.flush()

    fellowship.sponsor_id = 3
    session.commit()

    assert _stored_sponsor(session, fellowship.id) == 3
