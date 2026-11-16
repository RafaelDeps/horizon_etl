# Quickstart: validating spec 037

**Feature**: `037-alumni-linkedin-links`

Every step that runs the weekly needs the maintainer's approval first. The
checks only read the database and the exports, and print counts. The feature
is validated locally only: GitHub Actions never has the list.

## 0. The list

The list is made by the maintainer, outside the run. It is never committed
(`data/` is ignored). One way to make it from the maintainer's alumni file,
run by hand with `ALUMNI_FILE` set to the path of that file (kept out of this
repository's documents on purpose); it only reads that file and writes the list:

```bash
mkdir -p data/linkedin_run && python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); print("\n".join(r["linkedin"]+","+r["nome"] for c in d["cursos"].values() for r in c.get("vitrine",[]) if r.get("linkedin")))' "$ALUMNI_FILE" > data/linkedin_run/linkedin.list
```

```bash
wc -l data/linkedin_run/linkedin.list
```

Expected: 182 lines. `git status` must not show the file.

## 1. Unit tests

```bash
.venv/bin/python -m pytest -q tests/test_linkedin_links.py tests/test_linkedin_link_store.py tests/test_linkedin_links_flow.py tests/test_canonical_exporter.py
```

Then the full suite, compared with branch 036 (1371 passed, 10 skipped).

## 2. The step alone, on the current database

Back up `db/horizon.db` first. Then:

```bash
.venv/bin/python app.py linkedin_links
```

```bash
.venv/bin/python - <<'PY'
import json, sqlite3
c = sqlite3.connect("file:db/horizon.db?mode=ro", uri=True)
one = lambda q: c.execute(q).fetchone()[0]
print("links:", one("select count(*) from person_linkedin_links"))
print("links on a missing person:", one(
    "select count(*) from person_linkedin_links l where not exists "
    "(select 1 from persons p where p.id = l.person_id)"))
print("links not in normal form:", one(
    "select count(*) from person_linkedin_links "
    "where linkedin_url not like 'https://www.linkedin.com/in/%'"))
print("persons:", one("select count(*) from persons"))
r = json.load(open("data/reports/linkedin_links_report.json", encoding="utf-8"))
print({k: v for k, v in r.items() if k != "unused"})
print("unused by reason:", {x: sum(1 for u in r["unused"] if u["reason"] == x)
                            for x in {u["reason"] for u in r["unused"]}})
PY
```

Expected:

| Check | Expected | Criterion |
|-------|----------|-----------|
| Lines | 182 | SC-004 |
| Links stored | about 148 | SC-001 |
| Not found | about 34 | SC-004 |
| Several persons, conflicts, invalid | 0 | SC-004 |
| Stored + unused | equals lines | SC-004 |
| Links on a missing person, not in normal form | 0 | SC-002 |
| Persons | the same as before the step | SC-003 |

Run the step again: the summary must show added 0, changed 0, removed 0, and
the `updated_at` of every row must be unchanged (SC-005).

## 3. The list is the source of truth

Remove one line of a stored name from the list, change the link of another,
run the step: removed 1, changed 1, every other row unchanged (SC-006). Put
the two lines back and run again.

## 4. No list, empty list

Move the list away and run the step: it ends with exit 0, says there is no
list, and the table has the same rows. Put an empty file in its place and run:
a warning, the same rows (SC-007, clarification of 2026-11-13). Put the list
back.

## 5. Local weekly run

```bash
make weekly-flows > logs/weekly_037_run1.log 2>&1; echo "exit=$?" >> logs/weekly_037_run1.log
```

The log must show the phase `linkedin_links` after `consolidate_duplicates`
with its summary line. Then, on the exports:

```bash
.venv/bin/python - <<'PY'
import json
for name in ("researchers_canonical", "students_canonical"):
    d = json.load(open(f"data/exports/{name}.json", encoding="utf-8"))
    print(name, len(d), "with the key:", sum(1 for x in d if "linkedin_url" in x),
          "with a link:", sum(1 for x in d if x.get("linkedin_url")))
PY
```

Expected: every entry has the key; about 148 entries of
`researchers_canonical.json` and about 146 of `students_canonical.json` have a
link (SC-001, SC-008). Persons, advisorships, projects and the permanent ids
equal those of the run before (SC-003): compare `horizon_ids` with the backup.

A second weekly run writes no link change (SC-005).

## 6. GitHub Actions

Not validated with the list. If the maintainer asks for a fork run, it must
end as before, with the phase reporting "no list" and `linkedin_url` empty in
every entry (SC-007).
