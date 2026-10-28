"""Spec 020: HorizonIdAssigner on a real SQLite file (stable, unique ids)."""

import random
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.adapters.database.horizon_id_store import SqliteHorizonIdStore
from src.core.logic.horizon_id_assigner import HorizonIdAssigner
from src.db.migrations import run_migrations

# The columns the store reads, nothing else (the eo_lib schema is much larger).
SCHEMA = """
CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, identification_id TEXT, birthday TEXT);
CREATE TABLE researchers (id INTEGER PRIMARY KEY, cnpq_url TEXT);
CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE research_groups (id INTEGER PRIMARY KEY, cnpq_url TEXT);
CREATE TABLE initiative_types (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE initiatives (id INTEGER PRIMARY KEY, name TEXT UNIQUE, initiative_type_id INTEGER);
CREATE TABLE advisorships (id INTEGER PRIMARY KEY);
CREATE TABLE initiative_teams (initiative_id INTEGER, team_id INTEGER);
CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, doi TEXT, year TEXT, type TEXT,
                       journal_conference TEXT, volume TEXT, pages TEXT);
CREATE TABLE production_types (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE research_productions (id INTEGER PRIMARY KEY, title TEXT, year TEXT,
                                   production_type_id INTEGER);
CREATE TABLE education_types (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE academic_educations (id INTEGER PRIMARY KEY, researcher_id INTEGER,
                                  education_type_id INTEGER, title TEXT, start_year TEXT);
CREATE TABLE professional_activities (id INTEGER PRIMARY KEY, researcher_id INTEGER,
    institution_name TEXT, start_year TEXT, end_year TEXT, role_function TEXT, bond TEXT);
CREATE TABLE awards (id INTEGER PRIMARY KEY, researcher_id INTEGER, title TEXT, year TEXT);
CREATE TABLE languages (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE proficiencies (id INTEGER PRIMARY KEY, researcher_id INTEGER, language_id INTEGER);
CREATE TABLE fellowships (id INTEGER PRIMARY KEY, name TEXT, value REAL);
CREATE TABLE knowledge_areas (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE organizations (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE organizational_units (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE roles (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE source_records (id INTEGER PRIMARY KEY, source_system TEXT,
    source_entity_type TEXT, source_record_id TEXT, source_file TEXT);
CREATE TABLE entity_matches (id INTEGER PRIMARY KEY, source_record_id INTEGER,
    canonical_entity_type TEXT, canonical_entity_id INTEGER);
"""

LATTES_URL = "http://lattes.cnpq.br/9860697624155451"
CNPQ_URL = "http://dgp.cnpq.br/dgp/espelhogrupo/4439471564090237"


def _seed_rows():
    """(table, row) pairs with stable *logical* identities; numeric ids are
    assigned at insertion, in whatever order the caller chooses."""
    return [
        ("persons", {"key": "karin", "name": "Karin Satie Komati"}),
        ("persons", {"key": "carlos", "name": "Carlos Roberto Pires Campos"}),
        ("persons", {"key": "ana1", "name": "Ana Paula Souza"}),
        ("persons", {"key": "ana2", "name": "Ana Paula Souza"}),
        ("knowledge_areas", {"key": "ka", "name": "Educação"}),
        ("organizational_units", {"key": "serra", "name": "Serra"}),
        ("fellowships", {"key": "f700", "name": "PIBITI", "value": 700.0}),
        ("fellowships", {"key": "f900", "name": "PIBITI", "value": 900.0}),
        (
            "articles",
            {
                "key": "art1",
                "title": "Coconut shell gasification",
                "doi": "",
                "year": "2015",
                "type": "Conference Event",
                "journal_conference": "ABCM",
            },
        ),
        (
            "articles",
            {
                "key": "art2",
                "title": "Impact of supplementation",
                "year": "2019",
                "doi": "http://dx.doi.org/10.1016/j.theriogenology.2018.10.032",
                "type": "Journal",
                "journal_conference": "THERIOGENOLOGY",
            },
        ),
        ("groups", {"key": "g1", "name": "DIVIPOP", "cnpq_url": CNPQ_URL}),
        ("initiatives", {"key": "pj", "name": "Projeto SigPesq"}),
        ("initiatives", {"key": "lattes", "name": "Projeto Lattes"}),
        ("awards", {"key": "aw", "parent": "karin", "title": "Prêmio", "year": "2020"}),
    ]


def _build(path, order_seed):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO initiative_types (id, name) VALUES (1, 'Research Project')"
    )
    rows = _seed_rows()
    random.Random(order_seed).shuffle(rows)
    # Different starting offsets make numeric ids differ between databases.
    next_id = {"n": 1 + order_seed * 100}
    ids = {}

    def new_id():
        next_id["n"] += 1
        return next_id["n"]

    for table, row in rows:
        if row.get("parent"):
            continue
        rid = new_id()
        ids[row["key"]] = rid
        if table == "persons":
            con.execute(
                "INSERT INTO persons (id, name) VALUES (?, ?)", (rid, row["name"])
            )
            if row["key"] == "karin":
                con.execute("INSERT INTO researchers VALUES (?, ?)", (rid, LATTES_URL))
        elif table == "groups":
            con.execute("INSERT INTO teams VALUES (?, ?)", (rid, row["name"]))
            con.execute(
                "INSERT INTO research_groups VALUES (?, ?)", (rid, row["cnpq_url"])
            )
        elif table == "initiatives":
            con.execute("INSERT INTO initiatives VALUES (?, ?, 1)", (rid, row["name"]))
            team = new_id()
            con.execute("INSERT INTO teams VALUES (?, ?)", (team, row["name"]))
            con.execute("INSERT INTO initiative_teams VALUES (?, ?)", (rid, team))
        elif table == "articles":
            con.execute(
                "INSERT INTO articles (id, title, doi, year, type, journal_conference) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    row["title"],
                    row["doi"],
                    row["year"],
                    row["type"],
                    row["journal_conference"],
                ),
            )
        elif table == "fellowships":
            con.execute(
                "INSERT INTO fellowships VALUES (?, ?, ?)",
                (rid, row["name"], row["value"]),
            )
        else:
            con.execute(
                f"INSERT INTO {table} (id, name) VALUES (?, ?)", (rid, row["name"])
            )
    for table, row in rows:
        if row.get("parent"):
            con.execute(
                "INSERT INTO awards VALUES (?, ?, ?, ?)",
                (new_id(), ids[row["parent"]], row["title"], row["year"]),
            )

    def match(entity_type, key, rid_text, source_file):
        sid = new_id()
        con.execute(
            "INSERT INTO source_records VALUES (?, 's', 't', ?, ?)",
            (sid, rid_text, source_file),
        )
        con.execute(
            "INSERT INTO entity_matches VALUES (?, ?, ?, ?)",
            (new_id(), sid, entity_type, ids[key]),
        )

    match("initiative", "pj", "PJ 2342", "PJ_2342.json")
    match(
        "initiative",
        "lattes",
        "lattes:9860697624155451|lattes project|projeto lattes|karin|2020|rp",
        "/x/219_Karin_9860697624155451.json",
    )
    # The two homonyms come from different source documents.
    match("researcher", "ana1", "x", "report_a.xlsx")
    match("researcher", "ana2", "y", "report_b.xlsx")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        run_migrations(session)
    engine.dispose()


def _assign(path):
    store = SqliteHorizonIdStore(str(path), snapshot_path="", zip_path="")
    report = HorizonIdAssigner(store).assign()
    con = sqlite3.connect(path)
    rows = con.execute(
        "SELECT entity_type, entity_id, horizon_id, natural_key FROM horizon_ids"
    ).fetchall()
    con.close()
    return report, rows


@pytest.fixture
def db_a(tmp_path):
    path = tmp_path / "a.db"
    _build(path, order_seed=1)
    return path


def test_every_row_gets_exactly_one_id(db_a):
    report, rows = _assign(db_a)
    con = sqlite3.connect(db_a)
    expected = (
        sum(
            con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in (
                "persons",
                "knowledge_areas",
                "organizational_units",
                "fellowships",
                "articles",
                "research_groups",
                "initiatives",
                "awards",
                "initiative_types",
            )
        )
        + con.execute(
            "SELECT COUNT(*) FROM teams WHERE id NOT IN (SELECT id FROM research_groups)"
        ).fetchone()[0]
    )
    con.close()
    assert len(rows) == expected == report["entities"]
    assert len({r[2] for r in rows}) == len(rows)  # no shared horizon_id
    assert len({(r[0], r[1]) for r in rows}) == len(rows)


def test_two_databases_in_different_orders_get_the_same_ids(tmp_path):
    results = []
    for seed in (1, 2):
        path = tmp_path / f"db{seed}.db"
        _build(path, order_seed=seed)
        results.append(_assign(path)[1])
    a, b = ({(t, h, n) for t, _, h, n in rows} for rows in results)
    assert a == b
    # ...while the numeric ids are different.
    assert {r[1] for r in results[0]} != {r[1] for r in results[1]}


def test_expected_ids(db_a):
    _, rows = _assign(db_a)
    ids = {r[2] for r in rows}
    assert "person:lattes:9860697624155451" in ids
    assert "group:cnpq:4439471564090237" in ids
    assert "initiative:sigpesq-pj:2342" in ids
    assert "initiative:sigpesq-pj:2342/team" in ids
    assert "article:doi:10.1016/j.theriogenology.2018.10.032" in ids
    assert {"fellowship:pibiti:700", "fellowship:pibiti:900"} <= ids
    assert "campus:serra" in ids and "knowledge-area:educacao" in ids
    assert any(i.startswith("person:lattes:9860697624155451/award:h:") for i in ids)


def test_homonyms_from_different_documents_get_distinct_stable_ids(tmp_path):
    found = []
    for seed in (1, 2):
        path = tmp_path / f"h{seed}.db"
        _build(path, order_seed=seed)
        report, rows = _assign(path)
        anas = sorted(h for t, _, h, n in rows if n == "ana paula souza")
        found.append(anas)
        assert report["collisions"]["person"]["groups"] == 1
        assert report["collision_groups"] == 1
    assert len(found[0]) == 2 and found[0][0] != found[0][1]
    assert all("~" in h for h in found[0])
    assert found[0] == found[1]


def test_candidates_and_meta_are_written(db_a):
    _assign(db_a)
    con = sqlite3.connect(db_a)
    cands = con.execute(
        "SELECT candidate_id FROM horizon_id_candidates WHERE horizon_id = ?",
        ("person:lattes:9860697624155451",),
    ).fetchall()
    assert len(cands) == 2  # the lattes id and the name-based one
    assert con.execute(
        "SELECT value FROM horizon_meta WHERE key='rule_version'"
    ).fetchone() == ("1",)
    con.close()


def test_reassigning_is_idempotent(db_a):
    _, first = _assign(db_a)
    _, second = _assign(db_a)
    assert sorted(first) == sorted(second)


# --- History and aliases (spec 020, US3) -------------------------------------

import json  # noqa: E402
import zipfile  # noqa: E402

from src.adapters.database.horizon_id_store import record_merge  # noqa: E402
from src.core.logic.horizon_id_assigner import (  # noqa: E402
    write_alias_file,
    write_id_file,
)
from src.core.logic.horizon_identity import hash12, merge_candidates  # noqa: E402


def _sql(path, *statements):
    con = sqlite3.connect(path)
    for statement in statements:
        if isinstance(statement, tuple):
            con.execute(*statement)
        else:
            con.execute(statement)
    con.commit()
    con.close()


def _person_id(path, name):
    con = sqlite3.connect(path)
    (pid,) = con.execute("SELECT id FROM persons WHERE name = ?", (name,)).fetchone()
    con.close()
    return pid


def _current(path):
    con = sqlite3.connect(path)
    rows = dict(con.execute("SELECT horizon_id, entity_type FROM horizon_ids"))
    con.close()
    return rows


def _aliases(path):
    con = sqlite3.connect(path)
    rows = {
        a: (h, r)
        for a, h, r in con.execute(
            "SELECT alias_horizon_id, horizon_id, reason FROM horizon_id_aliases"
        )
    }
    con.close()
    return rows


def _merge(path, winner_name, loser_name, entity_type="person"):
    """What the consolidators do: log the loser's ids, then delete it."""
    winner, loser = _person_id(path, winner_name), _person_id(path, loser_name)
    con = sqlite3.connect(path)
    row = con.execute(
        "SELECT p.id, p.name, r.cnpq_url FROM persons p "
        "LEFT JOIN researchers r ON r.id = p.id WHERE p.id = ?",
        (loser,),
    ).fetchone()
    record_merge(
        con,
        entity_type,
        merge_candidates(entity_type, dict(zip(("id", "name", "cnpq_url"), row))),
        winner,
    )
    con.execute(
        "UPDATE awards SET researcher_id = ? WHERE researcher_id = ?", (winner, loser)
    )
    con.execute("DELETE FROM researchers WHERE id = ?", (loser,))
    con.execute("DELETE FROM persons WHERE id = ?", (loser,))
    con.commit()
    con.close()


CARLOS_NAME_ID = f"person:h:{hash12('Carlos Roberto Pires Campos')}"


def test_merge_keeps_the_lattes_id_and_aliases_the_name_id(db_a):
    _sql(db_a, "INSERT INTO persons (id, name) VALUES (9001, 'Karin S. Komati')")
    _assign(db_a)
    loser_id = f"person:h:{hash12('Karin S. Komati')}"
    assert loser_id in _current(db_a)

    _merge(db_a, "Karin Satie Komati", "Karin S. Komati")
    report, _ = _assign(db_a)

    assert "person:lattes:9860697624155451" in _current(db_a)
    assert _aliases(db_a)[loser_id] == ("person:lattes:9860697624155451", "merge")
    assert report["aliases"]["per_reason"] == {"merge": 1}
    con = sqlite3.connect(db_a)
    assert con.execute(
        "SELECT COUNT(*) FROM horizon_merge_log WHERE consumed_at IS NULL"
    ).fetchone() == (0,)
    con.close()
    # A third run changes nothing.
    _assign(db_a)
    assert _aliases(db_a)[loser_id] == ("person:lattes:9860697624155451", "merge")


@pytest.mark.parametrize("survivor", ["Carlos Roberto Pires Campos", "Carlos Campos"])
def test_equal_priority_merge_keeps_the_alphabetically_first_id(tmp_path, survivor):
    path = tmp_path / "m.db"
    _build(path, order_seed=1)
    _sql(path, "INSERT INTO persons (id, name) VALUES (9002, 'Carlos Campos')")
    _assign(path)
    ids = sorted([CARLOS_NAME_ID, f"person:h:{hash12('Carlos Campos')}"])

    other = ({"Carlos Roberto Pires Campos", "Carlos Campos"} - {survivor}).pop()
    _merge(path, survivor, other)
    _assign(path)

    assert ids[0] in _current(path) and ids[1] not in _current(path)
    assert _aliases(path)[ids[1]] == (ids[0], "merge")


def _give_lattes(path, name, lattes="1234567890123456"):
    pid = _person_id(path, name)
    _sql(
        path,
        (
            "INSERT INTO researchers (id, cnpq_url) VALUES (?, ?)",
            (pid, f"http://lattes.cnpq.br/{lattes}"),
        ),
    )
    return f"person:lattes:{lattes}"


def test_upgraded_key_aliases_the_person_and_its_children(db_a):
    pid = _person_id(db_a, "Carlos Roberto Pires Campos")
    _sql(db_a, ("INSERT INTO awards VALUES (9100, ?, 'Medalha', '2021')", (pid,)))
    _assign(db_a)
    old_award = next(h for h in _current(db_a) if h.startswith(CARLOS_NAME_ID + "/"))

    new_id = _give_lattes(db_a, "Carlos Roberto Pires Campos")
    _assign(db_a)

    aliases = _aliases(db_a)
    assert aliases[CARLOS_NAME_ID] == (new_id, "upgraded key")
    new_award = old_award.replace(CARLOS_NAME_ID, new_id)
    assert new_award in _current(db_a)
    assert aliases[old_award] == (new_award, "upgraded key")


def _publish(path, out_dir):
    """The two new files of a published exports_canonical.zip."""
    store = SqliteHorizonIdStore(str(path), snapshot_path="", zip_path="")
    out_dir.mkdir(exist_ok=True)
    write_id_file(store, str(out_dir))
    write_alias_file(store, str(out_dir))
    zip_path = out_dir / "exports_canonical.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in ("horizon_ids_canonical.json", "horizon_id_aliases_canonical.json"):
            zf.write(out_dir / name, name)
    return zip_path


def test_rebuild_from_the_published_zip_resolves_every_old_id(tmp_path, db_a):
    _assign(db_a)
    zip_path = _publish(db_a, tmp_path / "published")
    published = json.loads(
        (tmp_path / "published" / "horizon_ids_canonical.json").read_text()
    )

    rebuilt = tmp_path / "rebuilt.db"
    _build(rebuilt, order_seed=2)  # fresh tables, other numeric ids
    new_id = _give_lattes(rebuilt, "Carlos Roberto Pires Campos")
    store = SqliteHorizonIdStore(str(rebuilt), snapshot_path="", zip_path=str(zip_path))
    report = HorizonIdAssigner(store).assign()

    current, aliases = _current(rebuilt), _aliases(rebuilt)
    for row in published["ids"]:
        old = row["horizon_id"]
        assert old in current or aliases[old][0] in current  # SC-007
    assert aliases[CARLOS_NAME_ID] == (new_id, "rebuild")
    assert report["aliases"]["history_source"] == ["zip"]
    assert report["aliases"]["retired"] == 0


ART1 = "Coconut shell gasification"


def test_key_corrected_title_becomes_an_alias(db_a):
    _assign(db_a)
    old = next(h for h, t in _current(db_a).items() if t == "article" and ":h:" in h)
    _sql(
        db_a,
        f"UPDATE articles SET title = 'Coconut shell gasificatiom' WHERE title = '{ART1}'",
    )
    report, _ = _assign(db_a)

    target, reason = _aliases(db_a)[old]
    assert reason == "key corrected" and target in _current(db_a)
    assert report["aliases"]["key_corrected_ambiguous"] == 0


def test_two_similar_new_titles_create_no_alias(db_a):
    _assign(db_a)
    old = next(h for h, t in _current(db_a).items() if t == "article" and ":h:" in h)
    _sql(
        db_a,
        f"UPDATE articles SET title = 'Coconut shell gasificatiom' WHERE title = '{ART1}'",
        "INSERT INTO articles (id, title, doi, year, type, journal_conference) "
        "VALUES (9200, 'Coconut shell gasificatiox', '', '2015', "
        "'Conference Event', 'ABCM')",
    )
    report, _ = _assign(db_a)

    assert _aliases(db_a)[old] == (None, "retired")
    assert report["aliases"]["key_corrected_ambiguous"] == 1


def test_rule_change_recomputes_old_ids_from_their_natural_key(tmp_path, db_a):
    _assign(db_a)
    con = sqlite3.connect(db_a)
    natural = con.execute(
        "SELECT horizon_id, natural_key FROM horizon_ids WHERE entity_type = 'article' "
        "AND rule = 'title_year_type_venue'"
    ).fetchone()
    con.execute("DELETE FROM horizon_ids")
    con.commit()
    con.close()
    snapshot = tmp_path / "horizon_id_history.json"
    snapshot.write_text(
        json.dumps(
            {
                "rule_version": 1,
                "ids": [
                    {
                        "entity_type": "article",
                        "horizon_id": "article:v1:abcdef",
                        "rule": "title_year_type_venue",
                        "natural_key": natural[1],
                        "parent_horizon_id": None,
                    }
                ],
            }
        )
    )
    store = SqliteHorizonIdStore(str(db_a), snapshot_path=str(snapshot), zip_path="")
    HorizonIdAssigner(store).assign()

    assert _aliases(db_a)["article:v1:abcdef"] == (natural[0], "rebuild")


def test_history_sources_in_order(tmp_path, db_a):
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        json.dumps({"ids": [{"entity_type": "role", "horizon_id": "role:a"}]})
    )
    other = tmp_path / "other.db"
    _build(other, order_seed=2)
    _assign(other)
    zip_path = _publish(other, tmp_path / "pub")

    def source(snap, zp):
        store = SqliteHorizonIdStore(str(db_a), snapshot_path=snap, zip_path=zp)
        return store.load_history()["source"]

    assert source("", "") == []
    assert source("", str(zip_path)) == ["zip"]
    assert source(str(snapshot), "") == ["snapshot"]
    assert source(str(snapshot), str(zip_path)) == ["snapshot", "zip"]
    _assign(db_a)
    assert source(str(snapshot), str(zip_path)) == ["database"]


def test_alias_of_an_alias_is_repointed(db_a):
    _assign(db_a)
    _sql(
        db_a,
        (
            "INSERT INTO horizon_id_aliases VALUES (?, ?, 'merge', 't0', 't0')",
            ("person:h:000000000000", CARLOS_NAME_ID),
        ),
    )
    new_id = _give_lattes(db_a, "Carlos Roberto Pires Campos")
    _assign(db_a)

    aliases = _aliases(db_a)
    assert aliases["person:h:000000000000"] == (new_id, "merge")
    assert aliases[CARLOS_NAME_ID] == (new_id, "upgraded key")


def test_retired_id_that_reappears_is_current_again(db_a):
    _assign(db_a)
    _sql(
        db_a,
        "INSERT INTO horizon_id_aliases VALUES "
        "('fellowship:pibiti:700', NULL, 'retired', 't0', 't0')",
    )
    _assign(db_a)
    assert "fellowship:pibiti:700" in _current(db_a)
    assert "fellowship:pibiti:700" not in _aliases(db_a)
