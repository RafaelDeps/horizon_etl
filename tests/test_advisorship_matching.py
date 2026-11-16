"""Spec 035: when an advisorship item is a stored advisorship. Every case is
a row of specs/035-one-advisorship-per-student/contracts/advisorship-matching.md."""

from datetime import date, datetime

import pytest

from src.core.logic.advisorship_matching import (
    StoredAdvisorship,
    base_title,
    pick_match,
    same_student,
    year_range,
    years_differ,
)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Iniciação Científica", "Iniciação Científica"),
        (
            "Iniciação Científica | Orientacao Maria Silva | 2020",
            "Iniciação Científica",
        ),
        ("Estudo X | Orientacao Ana | 2019 | sigpesq 2320", "Estudo X"),
        ("A | Orientacao B | Orientacao C | 2020", "A | Orientacao B"),
        ("Estudo X | Orientacao", "Estudo X"),
        (None, ""),
        ("", ""),
    ],
)
def test_base_title(name, expected):
    assert base_title(name) == expected


@pytest.mark.parametrize(
    "start, end, expected",
    [
        (datetime(2019, 8, 1), datetime(2020, 7, 31), (2019, 2020)),
        (date(2020, 1, 1), None, (2020, 2020)),
        (None, date(2020, 12, 31), (2020, 2020)),
        (None, None, None),
        (date(2021, 1, 1), date(2020, 12, 31), (2020, 2021)),
        ("2019-08-01 00:00:00", "2020-07-31", (2019, 2020)),
        (2019, 2020, (2019, 2020)),
        ("2020", None, (2020, 2020)),
        ("", "sem data", None),
    ],
)
def test_year_range(start, end, expected):
    assert year_range(start, end) == expected


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ((2019, 2019), (2020, 2020), True),
        ((2019, 2020), (2020, 2020), False),
        ((2019, 2020), (2020, 2021), False),
        ((2019, 2019), None, False),
        (None, (2019, 2019), False),
        (None, None, False),
    ],
)
def test_years_differ(a, b, expected):
    assert years_differ(a, b) is expected


@pytest.mark.parametrize(
    "item, stored, expected",
    [
        ((7, "maria silva"), (7, "maria s. silva"), True),
        ((None, "maria silva"), (9, "maria silva"), True),
        ((7, "maria silva"), (9, "joao souza"), False),
        ((None, ""), (9, "joao souza"), False),
        ((None, ""), (None, ""), False),
    ],
)
def test_same_student(item, stored, expected):
    assert same_student(item[0], item[1], stored[0], stored[1]) is expected


TITLE = "Estágio Supervisionado Obrigatório"
BARE = TITLE
DISTINCT = TITLE + " | Orientacao X | 2020"


def _stored(ident, student, years, name=BARE):
    return StoredAdvisorship(
        id=ident,
        name=name,
        student_id=None,
        student_name=student,
        years=years,
    )


Y19, Y20, Y21 = (2019, 2019), (2020, 2020), (2021, 2021)


@pytest.mark.parametrize(
    "candidates, item, expected",
    [
        ([_stored(1, "ana", Y20)], ("bia", Y20), None),
        ([_stored(1, "ana", Y20)], ("ana", Y20), 1),
        ([_stored(1, "ana", Y19)], ("ana", Y20), None),
        (
            [_stored(1, "ana", Y19), _stored(2, "ana", Y20, DISTINCT)],
            ("ana", Y20),
            2,
        ),
        ([_stored(1, "ana", (2019, 2020))], ("ana", Y20), 1),
        (
            [_stored(1, "ana", None), _stored(2, "ana", Y20, DISTINCT)],
            ("ana", Y20),
            2,
        ),
        (
            [_stored(2, "ana", Y21, DISTINCT), _stored(1, "ana", Y19)],
            ("ana", None),
            1,
        ),
        ([_stored(1, "", None)], ("ana", Y20), 1),
        ([_stored(1, "ana", Y20)], ("", Y20), 1),
        ([_stored(1, "ana", Y20, DISTINCT)], ("", None), None),
        ([], ("ana", Y20), None),
    ],
)
def test_pick_match(candidates, item, expected):
    match = pick_match(None, item[0], item[1], candidates)
    assert (match.id if match else None) == expected


def test_pick_match_prefers_the_bare_title_then_the_lowest_id():
    same = [
        _stored(5, "ana", Y20, DISTINCT),
        _stored(9, "ana", Y20),
        _stored(3, "ana", Y20, DISTINCT),
    ]
    assert pick_match(None, "ana", Y20, same).id == 9
    assert pick_match(None, "ana", Y20, [same[0], same[2]]).id == 3


def test_pick_match_uses_the_person_when_the_names_differ():
    stored = StoredAdvisorship(
        id=1, name=BARE, student_id=7, student_name="maria s. silva", years=Y20
    )
    assert pick_match(7, "maria silva", Y20, [stored]).id == 1
    assert pick_match(8, "maria silva", Y20, [stored]) is None


def test_pick_match_never_returns_another_student():
    others = [_stored(i, f"aluno {i}", Y20) for i in range(10)]
    assert pick_match(None, "ana", Y20, others) is None
