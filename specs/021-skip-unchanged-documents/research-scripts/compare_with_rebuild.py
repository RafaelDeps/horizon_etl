"""Compare an incremental database with a rebuild from scratch (spec 021, R11).

usage: compare_with_rebuild.py <incremental.db> <rebuild.db> [--schema-base <base.db>]

Numeric ids differ between the two databases (rows are created in a different
order), so every row is compared through ``horizon_ids``: the row's own id and
every declared foreign key are replaced by the target's ``horizon_id``. Rows
are compared as multisets per table.

Left out (spec "How equivalence is measured"): the tracking tables, the ETL
bookkeeping tables, and, in both databases, the items of documents that are
inactive or failed in the incremental database. Reported but not failing:
reference rows present on one side only (orphan vocabulary kept on purpose)
and membership rows (person resolution order, spec 020 R9.3).

With ``--schema-base``, the definition of every table of that database must be
unchanged in the incremental one (FR-002, SC-007).

Read-only: both databases are opened with ``mode=ro``.
"""

import sqlite3
import sys
from collections import Counter

SKIP_TABLES = {
    "ingestion_runs",
    "source_records",
    "entity_matches",
    "attribute_assertions",
    "entity_change_logs",
    "schema_migrations",
    "horizon_ids",
    "horizon_id_candidates",
    "horizon_id_aliases",
    "horizon_merge_log",
    "horizon_meta",
    "source_document_states",
    "source_document_items",
    "source_document_references",
}
REFERENCE_TABLES = {
    "knowledge_areas",
    "organizations",
    "organizational_units",
    "initiative_types",
    "production_types",
    "roles",
    "languages",
    "education_types",
}
MEMBERSHIP_TABLES = {"team_members", "advisorship_members", "team_member_contributions"}

# Tables that share the id of another table (joined inheritance).
BASE_TABLE = {
    "researchers": "persons",
    "advisorships": "initiatives",
    "research_groups": "teams",
    "external_research_groups": "teams",
}
# horizon_ids.entity_type -> the table its entity_id belongs to.
ENTITY_TABLE = {
    "person": "persons",
    "research_group": "teams",
    "team": "teams",
    "initiative": "initiatives",
    "advisorship": "initiatives",
    "article": "articles",
    "research_production": "research_productions",
    "academic_education": "academic_educations",
    "professional_activity": "professional_activities",
    "award": "awards",
    "proficiency": "proficiencies",
    "fellowship": "fellowships",
    "knowledge_area": "knowledge_areas",
    "organization": "organizations",
    "campus": "organizational_units",
    "initiative_type": "initiative_types",
    "production_type": "production_types",
    "role": "roles",
    "language": "languages",
    "education_type": "education_types",
}
# source_document_items.item_type -> table of its item_ref (integer refs only).
ITEM_TABLE = {
    "person": "persons",
    "researcher": "persons",
    "initiative": "initiatives",
    "advisorship": "initiatives",
    "team": "teams",
    "research_group": "teams",
    "article": "articles",
    "research_production": "research_productions",
    "academic_education": "academic_educations",
    "award": "awards",
    "proficiency": "proficiencies",
    "professional_activity": "professional_activities",
    "fellowship": "fellowships",
}


def connect(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def tables(con):
    return [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def id_map(con):
    """(base table, numeric id) -> horizon_id."""
    out = {}
    if "horizon_ids" not in tables(con):
        return out
    for etype, eid, hid in con.execute(
        "SELECT entity_type, entity_id, horizon_id FROM horizon_ids"
    ):
        table = ENTITY_TABLE.get(etype)
        if table:
            out[(table, eid)] = hid
    return out


def excluded_items(con):
    """(base table, id) of the items of inactive or failed documents."""
    names = tables(con)
    if "source_document_states" not in names or "source_document_items" not in names:
        return set()
    rows = con.execute(
        "SELECT i.item_type, i.item_ref FROM source_document_items i "
        "JOIN source_document_states s ON s.source_system = i.source_system "
        "AND s.document_key = i.document_key "
        "WHERE s.status = 'inactive' OR s.last_failure IS NOT NULL"
    )
    out = set()
    for item_type, item_ref in rows:
        table = ITEM_TABLE.get(item_type)
        if table and str(item_ref).isdigit():
            out.add((table, int(item_ref)))
    return out


def table_rows(con, table, ids, excluded):
    """Rows of ``table`` with ids replaced by horizon ids. Returns
    (Counter of rows, columns, number of rows left out)."""
    cols = [c[1] for c in con.execute(f"PRAGMA table_info('{table}')")]
    fks = {
        f[3]: BASE_TABLE.get(f[2], f[2])
        for f in con.execute(f"PRAGMA foreign_key_list('{table}')")
    }
    own = BASE_TABLE.get(table, table)
    counter = Counter()
    left_out = 0
    for row in con.execute(f"SELECT * FROM '{table}'"):
        values = dict(zip(cols, row))
        refs = []
        if "id" in values and "id" not in fks:
            refs.append((own, values["id"]))
        refs += [(fks[c], values[c]) for c in fks if values.get(c) is not None]
        if any(ref in excluded for ref in refs):
            left_out += 1
            continue
        key = []
        for c in cols:
            v = values[c]
            if c in fks and v is not None:
                v = ids.get((fks[c], v), f"unmapped:{fks[c]}:{v}")
            elif c == "id" and (own, v) in ids:
                v = ids[(own, v)]
            elif c == "id":
                continue  # a row id with no horizon id (members, e-mails): not compared
            key.append((c, v))
        counter[tuple(key)] += 1
    return counter, cols, left_out


def schema(con):
    return {
        name: " ".join((sql or "").split())
        for name, sql in con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') "
            "AND name NOT LIKE 'sqlite_%'"
        )
    }


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    inc, reb = connect(argv[1]), connect(argv[2])
    failed = False

    if "--schema-base" in argv:
        base = schema(connect(argv[argv.index("--schema-base") + 1]))
        current = schema(inc)
        changed = sorted(n for n, sql in base.items() if current.get(n) != sql)
        print(
            f"SCHEMA of {len(base)} existing tables/indexes: "
            + ("IDENTICAL" if not changed else f"CHANGED {changed}")
        )
        failed |= bool(changed)

    inc_ids, reb_ids = id_map(inc), id_map(reb)
    excluded_inc = excluded_items(inc)
    excluded_hids = {inc_ids[x] for x in excluded_inc if x in inc_ids}
    excluded_reb = {k for k, h in reb_ids.items() if h in excluded_hids}
    print(
        f"horizon ids: incremental {len(inc_ids)}, rebuild {len(reb_ids)}; "
        f"items left out (inactive/failed documents): {len(excluded_inc)}"
    )

    notes = []
    for table in sorted(set(tables(inc)) & set(tables(reb))):
        if table in SKIP_TABLES:
            continue
        a, _, out_a = table_rows(inc, table, inc_ids, excluded_inc)
        b, _, out_b = table_rows(reb, table, reb_ids, excluded_reb)
        only_a, only_b = a - b, b - a
        n = sum(only_a.values()) + sum(only_b.values())
        if not n:
            print(
                f"{table:40s} IDENTICAL ({sum(a.values())} rows, left out {out_a}/{out_b})"
            )
            continue
        if table in REFERENCE_TABLES and not only_b:
            kind = "ORPHAN REFERENCE ROWS (not failing)"
        elif table in MEMBERSHIP_TABLES:
            kind = "MEMBERSHIP DIFFERENCES, review against R9.3 (not failing)"
        else:
            kind = "DIFFERENT"
            failed = True
        print(
            f"{table:40s} {kind} ({sum(only_a.values())} only incremental, "
            f"{sum(only_b.values())} only rebuild)"
        )
        notes.append((table, only_a, only_b))

    for table, only_a, only_b in notes:
        print(f"\n--- {table}: up to 5 rows on each side")
        for label, side in (("incremental", only_a), ("rebuild", only_b)):
            for row in list(side)[:5]:
                print(f"  {label}: {dict(row)}")

    print("\nRESULT:", "DIFFERENT" if failed else "IDENTICAL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
