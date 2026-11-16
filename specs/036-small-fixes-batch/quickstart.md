# Quickstart: validating spec 036

**Feature**: `036-small-fixes-batch`

Every step that runs the weekly needs the maintainer's approval first. Before
a local run, back up `db/horizon.db` and `data/`. The checks below only read
the database and the curricula. They print counts and public names, never a
CPF or a phone number.

## 1. Unit tests

```bash
.venv/bin/python -m pytest -q tests/test_student_name_rules.py tests/test_lattes_parser.py tests/test_initiative_handlers.py tests/test_project_enrichment_db.py tests/test_sigpesq_project_mapping.py tests/test_project_loader_matching.py tests/test_rule_version_guard.py
```

Then the full suite, compared with branch 035 (1251 passed, 10 skipped):

```bash
.venv/bin/python -m pytest -q
```

## 2. First local run: the rebuild

A database recorded under rule version 5 is reset by the weekly before use.

```bash
make weekly-flows > logs/weekly_036_run1.log 2>&1; echo "exit=$?" >> logs/weekly_036_run1.log
```

The log must show the rule-version reset and the line with the student name
counts. Then:

```bash
.venv/bin/python - <<'PY'
import collections, glob, json, sqlite3, sys
sys.path.insert(0, ".")
from src.core.logic.student_name_rules import clean_student_name

c = sqlite3.connect("file:db/horizon.db?mode=ro", uri=True)
one = lambda q: c.execute(q).fetchone()[0]
print("rule version:", c.execute("select * from horizon_meta").fetchall())
print("persons:", one("select count(*) from persons"))
print("advisorships:", one("select count(*) from advisorships"))
print("without a Supervisor:", one(
    "select count(*) from advisorships a where not exists (select 1 from "
    "advisorship_members m where m.advisorship_id=a.id and m.role_name='Supervisor')"))
print("without a Student:", one(
    "select count(*) from advisorships a where not exists (select 1 from "
    "advisorship_members m where m.advisorship_id=a.id and m.role_name='Student')"))

# Fix 1: students of advisorships whose stored name the rule would still change
kinds = collections.Counter()
for (name,) in c.execute(
    "select distinct p.name from persons p join advisorship_members m "
    "on m.person_id=p.id where m.role_name='Student'"):
    for k in clean_student_name(name).kinds:
        kinds[k] += 1
print("students the rule would still change:", dict(kinds))

# The same count over the curricula, to compare with the run summary line
texts = collections.Counter()
for path in glob.glob("data/lattes_json/*.json"):
    def walk(o):
        if isinstance(o, dict):
            v = o.get("orientando") or o.get("nome_do_orientado")
            if isinstance(v, str) and "titulo" in o:
                for k in clean_student_name(v).kinds:
                    texts[k] += 1
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(json.load(open(path, encoding="utf-8")))
print("curriculum items by kind:", dict(texts))

# Fix 2
print("fellowships:", one("select count(*) from fellowships"),
      "without a sponsor:", one("select count(*) from fellowships where sponsor_id is null"))
print("JTC:", c.execute(
    "select f.id, f.value, o.name from fellowships f left join organizations o "
    "on o.id=f.sponsor_id where f.name='JTC'").fetchall())

# Fix 3
print("advisorships with PDF data:", one(
    "select count(*) from initiatives i join advisorships a on a.id=i.id "
    "where i.enrichment_json is not null"))
print("projects with PDF data:", one(
    "select count(*) from initiatives i where i.enrichment_json is not null "
    "and not exists (select 1 from advisorships a where a.id=i.id)"))
PY
```

Expected:

| Check | Before (branch 035) | Expected | Criterion |
|-------|---------------------|----------|-----------|
| Rule version | 5 | 6 | SC-009 |
| Students the rule would still change | work_title 160, title 1, link 1, not_a_name 6 | only `several` (about 147) and `uncut` (1) | SC-001, SC-002, SC-003 |
| Run summary line | absent | equal to "curriculum items by kind" | SC-010 |
| Persons | 18,429 | fewer, by up to about 160 | SC-001 |
| Advisorships | 11,876 | about 11,876 | SC-004 |
| Advisorships without a Supervisor | 0 | 0 | SC-004 |
| Advisorships without a Student | 0 | up to 4 | SC-002 |
| Fellowships | 20 | 20 | SC-005 |
| Fellowships without a sponsor | 2 ("JTC", "PICTI") | 0 | SC-005 |
| Advisorships with PDF data | 4 | 0 | SC-006 |
| Projects with PDF data | 273 | about 273 | SC-008 |

Other tables (SC-008): compare the counts of projects, articles, professional
activities, awards, academic educations and research groups with the database
of branch 035 (`db/horizon.db` before this run, saved in the backup);
differences must come only from curricula downloaded again.

Old ids (FR-023): from the id report of the run, the number of person and
advisorship ids that became aliases and the number retired. Both are recorded
in `tasks.md`.

## 3. Second local run: nothing changes

Keep a copy of the database of step 2, then:

```bash
make weekly-flows > logs/weekly_036_run2.log 2>&1; echo "exit=$?" >> logs/weekly_036_run2.log
```

Compare the two databases. Expected (SC-005, SC-007, FR-020):

- `fellowships`: the same rows; one "JTC";
- `persons`, `advisorships`, `advisorship_members`: no difference for a
  source that did not change (the supervisor changes of TD-047 are known);
- `initiatives.description` and `enrichment_json`: no advisorship changed; no
  description written for an unchanged PDF;
- SigPesq project documents: the log's document summary shows the rows
  skipped; a row whose only difference from the first download is the order
  of "Estudantes" or "Pesquisadores" is among the skipped ones. If the portal
  returned no reordered row between the two downloads, the unit test of the
  contract (section 5) is the evidence and this is recorded as such.

## 4. Fork

Two weekly runs on the fork, on this branch, only with the maintainer's
approval. The first run rebuilds the persistent database (rule version 6);
the second must write no person, fellowship or description change for
unchanged sources. The same numbers are read from `exports_canonical.zip` of
each run.
