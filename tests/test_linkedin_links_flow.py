"""The weekly step that stores the LinkedIn links of a local list (spec 037).

Everything runs on files under ``tmp_path``: the real list and the real
database are never touched.
"""

import json
import sqlite3

import pytest

from src.flows.maintenance.linkedin_links import sync_linkedin_links

MARIA = "https://www.linkedin.com/in/maria"
JOAO = "https://www.linkedin.com/in/joao"
PERSONS = [
    (1, "Maria da Silva"),
    (2, "João Souza"),
    (3, "Ana Lima"),
    (4, "Pedro Alves"),
    (5, "Pedro Alves"),
]


@pytest.fixture
def workspace(tmp_path):
    db = tmp_path / "horizon.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE initiatives (id INTEGER PRIMARY KEY, name TEXT)")
    con.executemany("INSERT INTO persons VALUES (?, ?)", PERSONS)
    con.commit()
    con.close()

    class Workspace:
        list_path = tmp_path / "linkedin_run" / "linkedin.list"
        report_path = tmp_path / "reports" / "linkedin_links_report.json"
        database_url = f"sqlite:///{db}"

        def write_list(self, *lines):
            self.list_path.parent.mkdir(exist_ok=True)
            self.list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        def sync(self):
            return sync_linkedin_links(
                str(self.list_path), self.database_url, str(self.report_path)
            )

        def rows(self):
            con = sqlite3.connect(db)
            try:
                return con.execute(
                    "SELECT person_id, linkedin_url, listed_name, updated_at "
                    "FROM person_linkedin_links ORDER BY person_id"
                ).fetchall()
            finally:
                con.close()

        def persons(self):
            con = sqlite3.connect(db)
            try:
                return con.execute(
                    "SELECT id, name FROM persons ORDER BY id"
                ).fetchall()
            finally:
                con.close()

        def report(self):
            return json.loads(self.report_path.read_text(encoding="utf-8"))

    return Workspace()


# User Story 1


def test_the_links_of_the_list_are_stored_on_their_persons(workspace):
    workspace.write_list(
        "http://linkedin.com/in/maria/?utm_source=share,MARIA DA SILVA",
        f"{JOAO},João Souza",
    )

    result = workspace.sync()

    assert [(row[0], row[1], row[2]) for row in workspace.rows()] == [
        (1, MARIA, "MARIA DA SILVA"),
        (2, JOAO, "João Souza"),
    ]
    assert (result["lines"], result["stored"], result["added"]) == (2, 2, 2)
    assert workspace.persons() == PERSONS


# User Story 2

ONE_OF_EACH = (
    f"{MARIA},Maria da Silva",  # stored
    "https://www.linkedin.com/in/carla,Carla Nunes",  # not found
    "https://www.linkedin.com/in/pedro,Pedro Alves",  # two persons
    "https://www.linkedin.com/company/x,Ana Lima",  # invalid link
    f"{JOAO},João Souza",  # conflict: the same name with two links
    "https://www.linkedin.com/in/joao-2,João Souza",
)


def test_every_unused_line_is_counted_and_listed_with_its_reason(workspace):
    workspace.write_list(*ONE_OF_EACH)

    result = workspace.sync()

    counts = {
        key: result[key]
        for key in (
            "lines",
            "stored",
            "added",
            "changed",
            "removed",
            "not_found",
            "several_persons",
            "conflicts",
            "invalid",
        )
    }
    assert counts == {
        "lines": 6,
        "stored": 1,
        "added": 1,
        "changed": 0,
        "removed": 0,
        "not_found": 1,
        "several_persons": 1,
        "conflicts": 2,
        "invalid": 1,
    }
    assert (
        result["stored"]
        + result["not_found"]
        + result["several_persons"]
        + result["conflicts"]
        + result["invalid"]
        == result["lines"]
    )
    assert result["unused"] == [
        {"line": 2, "name": "Carla Nunes", "reason": "not_found"},
        {"line": 3, "name": "Pedro Alves", "reason": "several_persons"},
        {"line": 4, "name": "Ana Lima", "reason": "invalid"},
        {"line": 5, "name": "João Souza", "reason": "conflict"},
        {"line": 6, "name": "João Souza", "reason": "conflict"},
    ]
    assert [row[0] for row in workspace.rows()] == [1]
    assert workspace.persons() == PERSONS  # nobody created


def test_the_report_file_holds_the_same_result(workspace):
    workspace.write_list(*ONE_OF_EACH)

    result = workspace.sync()

    report = workspace.report()
    assert report == result
    assert report["list_found"] is True
    assert report["list_path"] == str(workspace.list_path)


def test_the_summary_names_the_unused_lines_and_never_a_link(workspace):
    from src.flows.maintenance.linkedin_links import format_summary

    workspace.write_list(*ONE_OF_EACH)

    text = format_summary(workspace.sync())

    assert text[0] == (
        "linkedin links: lines 6, stored 1 (added 1, changed 0, removed 0), "
        "not found 1, several persons 1, conflicts 2, invalid 1"
    )
    assert text[1:] == [
        "line 2: Carla Nunes: not found",
        "line 3: Pedro Alves: several persons",
        "line 4: Ana Lima: invalid",
        "line 5: João Souza: conflict",
        "line 6: João Souza: conflict",
    ]
    assert not any("linkedin.com" in line for line in text)


# User Story 3


def test_the_same_list_twice_writes_nothing_the_second_time(workspace):
    workspace.write_list(f"{MARIA},Maria da Silva", f"{JOAO},João Souza")
    workspace.sync()
    before = workspace.rows()

    result = workspace.sync()

    assert (result["added"], result["changed"], result["removed"]) == (0, 0, 0)
    assert result["stored"] == 2
    assert workspace.rows() == before  # updated_at included


def test_a_changed_link_and_a_removed_line_touch_only_their_rows(workspace):
    ana = "https://www.linkedin.com/in/ana"
    workspace.write_list(
        f"{MARIA},Maria da Silva", f"{JOAO},João Souza", f"{ana},Ana Lima"
    )
    workspace.sync()
    before = {row[0]: row for row in workspace.rows()}

    workspace.write_list(
        "https://www.linkedin.com/in/maria-nova,Maria da Silva", f"{ana},Ana Lima"
    )
    result = workspace.sync()

    assert (result["added"], result["changed"], result["removed"]) == (0, 1, 1)
    after = {row[0]: row for row in workspace.rows()}
    assert sorted(after) == [1, 3]
    assert after[1][1] == "https://www.linkedin.com/in/maria-nova"
    assert after[3] == before[3]


# User Story 4


def _with_two_links(workspace):
    workspace.write_list(f"{MARIA},Maria da Silva", f"{JOAO},João Souza")
    workspace.sync()
    return workspace.rows()


def test_without_the_list_nothing_changes_and_nothing_fails(workspace):
    from src.flows.maintenance.linkedin_links import format_summary

    before = _with_two_links(workspace)
    workspace.list_path.unlink()

    result = workspace.sync()

    assert result["list_found"] is False
    assert (result["added"], result["changed"], result["removed"]) == (0, 0, 0)
    assert workspace.rows() == before
    assert workspace.report()["list_found"] is False
    assert format_summary(result) == [
        f"linkedin links: no list at {workspace.list_path}, nothing changed"
    ]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# nothing here yet\n\n",
        "https://www.linkedin.com/company/x,Maria da Silva\nno comma\n",
    ],
)
def test_a_list_with_no_usable_line_changes_nothing(workspace, content):
    from src.flows.maintenance.linkedin_links import format_summary

    before = _with_two_links(workspace)
    workspace.list_path.write_text(content, encoding="utf-8")

    result = workspace.sync()

    assert result["list_found"] is True
    assert result["empty_list"] is True
    assert (result["stored"], result["removed"]) == (0, 0)
    assert workspace.rows() == before
    summary = format_summary(result)
    assert summary[0].startswith(
        "linkedin links: the list has no usable line, nothing changed"
    )
    assert len(summary) == 1 + len(result["unused"])


def test_a_usable_list_is_not_flagged_as_empty(workspace):
    workspace.write_list(f"{MARIA},Maria da Silva")

    assert workspace.sync()["empty_list"] is False


def test_a_database_created_before_the_feature_gets_the_table(workspace):
    # The fixture's database has no person_linkedin_links table yet.
    workspace.write_list(f"{MARIA},Maria da Silva")

    result = workspace.sync()

    assert result["added"] == 1
    assert [row[0] for row in workspace.rows()] == [1]
