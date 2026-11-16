"""Contract of the LinkedIn list rule (spec 037, contracts/linkedin-links.md)."""

import pytest

from src.core.logic.linkedin_links import (
    LineOutcome,
    ListLine,
    Plan,
    normalize_profile_link,
    parse_list,
    plan,
)

MARIA = "https://www.linkedin.com/in/maria-silva"


@pytest.mark.parametrize(
    "text, expected",
    [
        (MARIA, MARIA),
        ("http://linkedin.com/in/maria-silva/", MARIA),
        ("linkedin.com/in/maria-silva", MARIA),
        ("www.linkedin.com/in/maria-silva?utm_source=share&utm_medium=x", MARIA),
        ("https://br.linkedin.com/in/maria-silva#about", MARIA),
        (
            "HTTPS://WWW.LinkedIn.com/in/Maria-Silva",
            "https://www.linkedin.com/in/Maria-Silva",
        ),
        (
            "https://www.linkedin.com/in/jo%C3%A3o-souza-1a2b3c",
            "https://www.linkedin.com/in/jo%C3%A3o-souza-1a2b3c",
        ),
        ("https://www.linkedin.com/in/maria-silva/details/experience/", MARIA),
        ("  https://www.linkedin.com/in/maria-silva  ", MARIA),
        ("https://www.linkedin.com/company/ifes", None),
        ("https://www.linkedin.com/school/ifes/", None),
        ("https://www.linkedin.com/posts/maria-silva_activity-1", None),
        ("https://www.linkedin.com/feed/", None),
        ("https://www.linkedin.com/in/", None),
        ("https://www.linkedin.com/in", None),
        ("https://example.com/in/maria-silva", None),
        ("https://notlinkedin.com/in/x", None),
        ("https://linkedin.com.evil.example/in/x", None),
        ("maria-silva", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_profile_link(text, expected):
    assert normalize_profile_link(text) == expected


def test_parse_list_reads_link_and_name():
    lines = parse_list(
        [
            "https://www.linkedin.com/in/maria,Maria da Silva",
            "  linkedin.com/in/joao/ ,  João Souza  ",
        ]
    )

    assert lines == [
        ListLine(1, "https://www.linkedin.com/in/maria", "Maria da Silva", None),
        ListLine(2, "https://www.linkedin.com/in/joao", "João Souza", None),
    ]


def test_parse_list_splits_at_the_first_comma_only():
    (line,) = parse_list(["https://www.linkedin.com/in/maria,Silva, Maria da"])

    assert line.name == "Silva, Maria da"
    assert line.problem is None


def test_parse_list_ignores_empty_lines_and_comments_but_counts_them():
    lines = parse_list(
        [
            "# alumni of 2026",
            "",
            "   ",
            "https://www.linkedin.com/in/maria,Maria da Silva\n",
            "  # another comment",
            "https://www.linkedin.com/in/joao,João Souza",
        ]
    )

    assert [(line.number, line.name) for line in lines] == [
        (4, "Maria da Silva"),
        (6, "João Souza"),
    ]


@pytest.mark.parametrize(
    "text, name",
    [
        ("https://www.linkedin.com/in/maria", ""),
        ("https://www.linkedin.com/in/maria,", ""),
        ("https://www.linkedin.com/in/maria,   ", ""),
        ("https://www.linkedin.com/company/x,Maria da Silva", "Maria da Silva"),
        (",Maria da Silva", "Maria da Silva"),
        (
            "Maria da Silva,https://www.linkedin.com/in/maria",
            "https://www.linkedin.com/in/maria",
        ),
    ],
)
def test_parse_list_marks_invalid_lines(text, name):
    (line,) = parse_list([text])

    assert line.problem == "invalid"
    assert line.name == name


# --- plan (contract section 3) ---

JOAO = "https://www.linkedin.com/in/joao"
ANA = "https://www.linkedin.com/in/ana"
PERSONS = [(1, "Maria da Silva"), (2, "João Souza"), (3, "Ana Lima")]


def _lines(*pairs):
    return parse_list(f"{link},{name}" for link, name in pairs)


def _outcomes(result):
    return [(o.number, o.name, o.outcome) for o in result.outcomes]


# User Story 1: a usable line stores the link on its person.


def test_a_name_of_one_person_is_stored():
    lines = _lines((MARIA, "Maria da Silva"))
    persons, stored = list(PERSONS), {}

    result = plan(lines, persons, stored)

    assert result == Plan(
        add=[(1, MARIA, "Maria da Silva")],
        change=[],
        remove=[],
        outcomes=[LineOutcome(1, "Maria da Silva", "stored")],
    )
    assert persons == PERSONS and stored == {}


@pytest.mark.parametrize(
    "written",
    ["MARIA DA SILVA", "maria da silva", "Maria  da   Sílva", " Maria da Silva "],
)
def test_case_accents_and_spaces_do_not_matter(written):
    result = plan(_lines((MARIA, written)), PERSONS, {})

    assert result.add == [(1, MARIA, written.strip())]


def test_a_person_outside_the_list_gets_nothing():
    result = plan(_lines((MARIA, "Maria da Silva")), PERSONS, {})

    assert [row[0] for row in result.add] == [1]
    assert result.change == [] and result.remove == []


def test_a_link_already_stored_is_not_written_again():
    stored = {1: (MARIA, "Maria da Silva")}

    result = plan(_lines((MARIA, "Maria da Silva")), PERSONS, stored)

    assert (result.add, result.change, result.remove) == ([], [], [])
    assert _outcomes(result) == [(1, "Maria da Silva", "stored")]


def test_another_link_replaces_the_stored_one():
    stored = {1: ("https://www.linkedin.com/in/old", "Maria da Silva")}

    result = plan(_lines((MARIA, "Maria da Silva")), PERSONS, stored)

    assert result.change == [(1, MARIA, "Maria da Silva")]
    assert result.add == [] and result.remove == []


# User Story 2: a line that cannot be used stores nothing and is reported.

PEOPLE_WITH_TWINS = PERSONS + [(4, "Pedro Alves"), (5, "PEDRO  ALVES")]


def test_a_name_of_no_person_is_not_found():
    result = plan(_lines((MARIA, "Carla Nunes")), PERSONS, {})

    assert (result.add, result.change, result.remove) == ([], [], [])
    assert _outcomes(result) == [(1, "Carla Nunes", "not_found")]


def test_a_name_of_two_persons_gives_the_link_to_neither():
    link = "https://www.linkedin.com/in/pedro"

    result = plan(_lines((link, "Pedro Alves")), PEOPLE_WITH_TWINS, {})

    assert result.add == []
    assert _outcomes(result) == [(1, "Pedro Alves", "several_persons")]


def test_the_same_name_and_link_twice_count_once():
    result = plan(
        _lines((MARIA, "Maria da Silva"), (MARIA + "/", "MARIA DA SILVA")),
        PERSONS,
        {},
    )

    assert result.add == [(1, MARIA, "Maria da Silva")]
    assert _outcomes(result) == [
        (1, "Maria da Silva", "stored"),
        (2, "MARIA DA SILVA", "stored"),
    ]


def test_the_same_name_with_two_links_is_a_conflict():
    result = plan(
        _lines((MARIA, "Maria da Silva"), (JOAO, "maria da silva")), PERSONS, {}
    )

    assert result.add == []
    assert [o.outcome for o in result.outcomes] == ["conflict", "conflict"]


def test_the_same_link_under_two_names_is_a_conflict():
    result = plan(
        _lines((MARIA, "Maria da Silva"), (MARIA, "João Souza"), (ANA, "Ana Lima")),
        PERSONS,
        {},
    )

    assert result.add == [(3, ANA, "Ana Lima")]
    assert [o.outcome for o in result.outcomes] == ["conflict", "conflict", "stored"]


def test_every_line_has_an_outcome_in_file_order():
    lines = parse_list(
        [
            "# header",
            f"{MARIA},Maria da Silva",
            "https://www.linkedin.com/company/x,Empresa X",
            f"{JOAO},Carla Nunes",
            "not a line",
        ]
    )

    result = plan(lines, PERSONS, {})

    assert _outcomes(result) == [
        (2, "Maria da Silva", "stored"),
        (3, "Empresa X", "invalid"),
        (4, "Carla Nunes", "not_found"),
        (5, "", "invalid"),
    ]
    assert result.add == [(1, MARIA, "Maria da Silva")]


# User Story 3: the stored links follow the list.


def test_a_line_that_is_gone_removes_the_link():
    stored = {1: (MARIA, "Maria da Silva"), 2: (JOAO, "João Souza")}

    result = plan(_lines((MARIA, "Maria da Silva")), PERSONS, stored)

    assert (result.add, result.change, result.remove) == ([], [], [2])


@pytest.mark.parametrize(
    "second_line, outcome",
    [
        (("https://www.linkedin.com/in/joao-2", "João Souza"), "conflict"),
        (("https://www.linkedin.com/company/x", "João Souza"), "invalid"),
    ],
)
def test_a_line_that_is_no_longer_usable_removes_the_link(second_line, outcome):
    stored = {1: (MARIA, "Maria da Silva"), 2: (JOAO, "João Souza")}
    pairs = [(MARIA, "Maria da Silva"), second_line]
    if outcome == "conflict":
        pairs.append((JOAO, "João Souza"))

    result = plan(_lines(*pairs), PERSONS, stored)

    assert result.remove == [2]
    assert outcome in [o.outcome for o in result.outcomes]


def test_a_person_stored_twice_loses_the_link():
    stored = {
        1: (MARIA, "Maria da Silva"),
        4: ("https://www.linkedin.com/in/pedro", "Pedro Alves"),
    }

    result = plan(
        _lines(
            (MARIA, "Maria da Silva"),
            ("https://www.linkedin.com/in/pedro", "Pedro Alves"),
        ),
        PEOPLE_WITH_TWINS,
        stored,
    )

    assert result.remove == [4]


def test_a_link_of_a_person_that_no_longer_exists_is_removed():
    stored = {1: (MARIA, "Maria da Silva"), 99: (JOAO, "Someone Merged Away")}

    result = plan(_lines((MARIA, "Maria da Silva")), PERSONS, stored)

    assert result.remove == [99]


def test_planning_again_after_applying_changes_nothing():
    lines = _lines((MARIA, "Maria da Silva"), (JOAO, "João Souza"), (ANA, "Nobody"))
    first = plan(lines, PERSONS, {})
    stored = {person_id: (link, name) for person_id, link, name in first.add}

    second = plan(lines, PERSONS, stored)

    assert (second.add, second.change, second.remove) == ([], [], [])
    assert second.outcomes == first.outcomes


def test_a_name_not_found_gets_its_link_once_the_person_exists():
    lines = _lines((MARIA, "Maria da Silva"), (ANA, "Carla Nunes"))
    stored = {1: (MARIA, "Maria da Silva")}

    assert plan(lines, PERSONS, stored).add == []
    later = plan(lines, PERSONS + [(8, "Carla Nunes")], stored)

    assert later.add == [(8, ANA, "Carla Nunes")]
    assert later.remove == []


# User Story 4: a list with no usable line changes nothing.


@pytest.mark.parametrize(
    "raw_lines",
    [
        [],
        ["# only a comment", ""],
        ["https://www.linkedin.com/company/x,Maria da Silva", "no comma here"],
        ["https://www.linkedin.com/in/carla,Carla Nunes"],
    ],
)
def test_a_list_with_no_usable_line_removes_nothing(raw_lines):
    stored = {1: (MARIA, "Maria da Silva"), 2: (JOAO, "João Souza")}
    lines = parse_list(raw_lines)

    result = plan(lines, PERSONS, stored)

    assert (result.add, result.change, result.remove) == ([], [], [])
    assert len(result.outcomes) == len(lines)
    assert all(o.outcome != "stored" for o in result.outcomes)
