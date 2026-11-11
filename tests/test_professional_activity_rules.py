"""Spec 034: the rules of a Lattes professional activity
(specs/034-keep-professional-activities/contracts/activity-rules.md)."""

from types import SimpleNamespace

import pytest

from src.core.logic.professional_activity_rules import (
    DETAIL_FIELDS,
    STORED_FIELDS,
    activity_key,
    distinct_activities,
    split_institution,
)

IFES = "Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo"
IMPER = "Imper - Imperial, Comércio, Industria e Serviços Ltda."


def _item(institution="Universidade X, UX, Brasil", **fields):
    item = {name: None for name in STORED_FIELDS}
    item.update(
        institution=institution,
        institution_name="Universidade X",
        institution_acronym="UX",
        institution_country="Brasil",
        activity_type="Atuação profissional",
        current=False,
    )
    item.update(fields)
    return item


# --- activity_key ---


def test_activity_key_reads_a_dict_and_a_row_alike():
    item = _item(period="2010 - 2012", start_year=2010, end_year=2012, bond="Servidor")
    key = activity_key(item)
    assert key == activity_key(SimpleNamespace(**item))
    assert key == tuple(item[name] for name in STORED_FIELDS)
    assert len(key) == len(STORED_FIELDS) == 13
    assert set(DETAIL_FIELDS) < set(STORED_FIELDS) and len(DETAIL_FIELDS) == 7


def test_activity_key_of_a_missing_field_is_none():
    key = activity_key({"institution": "UFES"})
    assert key[0] == "UFES"
    assert key[1:-1] == (None,) * 11
    assert key[-1] is False


@pytest.mark.parametrize("stored, expected", [(0, False), (1, True), (None, False)])
def test_activity_key_returns_current_as_a_bool(stored, expected):
    assert activity_key(_item(current=stored))[-1] is expected


@pytest.mark.parametrize("field", STORED_FIELDS)
def test_items_that_differ_in_one_field_have_different_keys(field):
    other = True if field == "current" else "another value"
    assert activity_key(_item()) != activity_key(_item(**{field: other}))


# --- distinct_activities ---


def test_two_different_periods_are_both_kept():
    a = _item(period="2010 - 2012", start_year=2010, end_year=2012)
    b = _item(period="2010 - 2015", start_year=2010, end_year=2015)
    assert distinct_activities([a, b]) == [a, b]


def test_the_same_item_twice_is_kept_once():
    a = _item(period="2010 - 2012", start_year=2010)
    assert distinct_activities([a, dict(a)]) == [a]


def test_two_institution_only_items_give_one():
    assert distinct_activities([_item(), _item()]) == [_item()]


def test_an_institution_only_item_beside_a_filled_one_is_dropped():
    a = _item(period="2010 - 2012", start_year=2010)
    assert distinct_activities([_item(), a]) == [a]
    assert distinct_activities([a, _item()]) == [a]


def test_an_institution_only_item_at_another_institution_is_kept():
    a = _item(period="2010 - 2012", start_year=2010)
    other = _item(institution="Empresa Y, EY, Brasil", institution_name="Empresa Y")
    assert distinct_activities([a, other]) == [a, other]


def test_order_of_first_appearance_is_kept():
    a = _item(period="2010 - 2012")
    b = _item(institution="Empresa Y, EY, Brasil", bond="Celetista")
    c = _item(period="2013 - 2015")
    assert distinct_activities([c, b, a, dict(b), dict(c)]) == [c, b, a]


def test_current_and_type_do_not_count_as_detail():
    only = _item(activity_type="Atuação profissional", current=False)
    filled = _item(bond="Servidor")
    assert distinct_activities([only, filled]) == [filled]


@pytest.mark.parametrize(
    "field",
    [
        "period",
        "end_year",
        "bond",
        "classification",
        "work_regime",
        "role_function",
        "current",
    ],
)
def test_items_that_differ_in_one_field_are_both_kept(field):
    base = _item(start_year=2010, period="2010 - Atual")
    other = dict(base, **{field: True if field == "current" else "another value"})
    assert distinct_activities([base, other]) == [base, other]


def test_the_input_list_is_not_changed():
    items = [_item(), _item(bond="Servidor"), _item()]
    before = [dict(i) for i in items]
    distinct_activities(items)
    assert items == before


# --- split_institution ---

_SPLIT_EXAMPLES = [
    (f"{IFES}, IFES, Brasil", f"{IFES}, IFES, Brasil", IFES, "IFES", "Brasil"),
    (
        "Universidade Federal do Espírito Santo, UFES, Brasil",
        "Universidade Federal do Espírito Santo, UFES, Brasil",
        "Universidade Federal do Espírito Santo",
        "UFES",
        "Brasil",
    ),
    (
        "Universidade Federal do Espírito Santo, UFES, Brasil.",
        "Universidade Federal do Espírito Santo, UFES, Brasil",
        "Universidade Federal do Espírito Santo",
        "UFES",
        "Brasil",
    ),
    (
        "Universidade de Brasília, UnB, Brasil",
        "Universidade de Brasília, UnB, Brasil",
        "Universidade de Brasília",
        "UnB",
        "Brasil",
    ),
    (
        "Suwannee American Cement, SAC, Estados Unidos",
        "Suwannee American Cement, SAC, Estados Unidos",
        "Suwannee American Cement",
        "SAC",
        "Estados Unidos",
    ),
    (f"{IMPER}, IMPER, Brasil.", f"{IMPER}, IMPER, Brasil", IMPER, "IMPER", "Brasil"),
    (
        "Quimivale Industrial Ltda, QUIMI",
        "Quimivale Industrial Ltda, QUIMI",
        "Quimivale Industrial Ltda",
        "QUIMI",
        None,
    ),
    (
        "Cia Níquel Tocantins - Grupo Votorantim, Brasil",
        "Cia Níquel Tocantins - Grupo Votorantim, Brasil",
        "Cia Níquel Tocantins - Grupo Votorantim",
        None,
        "Brasil",
    ),
    ("zAgile, Inc", "zAgile, Inc", "zAgile, Inc", None, None),
    (
        "Universidade Federal de",
        "Universidade Federal de",
        "Universidade Federal de",
        None,
        None,
    ),
    (
        "Rádio Universitária 104,7, UNI",
        "Rádio Universitária 104,7, UNI",
        "Rádio Universitária 104,7",
        "UNI",
        None,
    ),
]


@pytest.mark.parametrize("text, institution, name, acronym, country", _SPLIT_EXAMPLES)
def test_split_institution_contract(text, institution, name, acronym, country):
    assert split_institution(text) == (institution, name, acronym, country)


@pytest.mark.parametrize("text", [None, "", "   ", " . "])
def test_split_institution_of_nothing(text):
    assert split_institution(text) == ("", None, None, None)


@pytest.mark.parametrize("ending", [".", ". ", "..", " .. "])
def test_every_final_full_stop_and_space_is_removed(ending):
    assert split_institution("Universidade X, UX, Brasil" + ending) == (
        "Universidade X, UX, Brasil",
        "Universidade X",
        "UX",
        "Brasil",
    )


def test_a_two_part_text_ending_in_capitals_has_an_acronym_not_a_country():
    assert split_institution("Empresa X, BRASIL") == (
        "Empresa X, BRASIL",
        "Empresa X",
        "BRASIL",
        None,
    )


def test_a_known_country_is_recognised_without_case_and_accents():
    assert split_institution("Empresa X, brasil")[1:] == ("Empresa X", None, "brasil")
    assert split_institution("Empresa X, Franca")[1:] == ("Empresa X", None, "Franca")


@pytest.mark.parametrize("example", _SPLIT_EXAMPLES)
def test_split_institution_is_stable(example):
    first = split_institution(example[0])
    assert split_institution(first[0]) == first


@pytest.mark.parametrize("example", _SPLIT_EXAMPLES)
def test_no_part_is_returned_in_two_fields(example):
    _, name, acronym, country = split_institution(example[0])
    name_parts = [part.strip() for part in name.split(",")]
    taken = [value for value in (acronym, country) if value is not None]
    # The acronym and the country are the last parts of the text, so the name
    # ends before them.
    assert len(name_parts) + len(taken) == len(example[1].split(","))


def test_split_institution_applies_the_column_limits():
    institution, name, _, _ = split_institution("x" * 600)
    assert len(institution) == 500 and len(name) == 255
    _, _, acronym, country = split_institution(f"Nome, {'A' * 150}, {'b' * 150}")
    assert len(acronym) == 100 and len(country) == 100
