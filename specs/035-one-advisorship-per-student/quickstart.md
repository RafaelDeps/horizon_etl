# Quickstart: validating spec 035

**Feature**: `035-one-advisorship-per-student`

Every step that runs the weekly needs the maintainer's approval first. Before
a local run, back up `db/horizon.db` and `data/`. The checks below only read
the database. They print counts, never a CPF or a phone number.

## 1. Unit tests

```bash
.venv/bin/python -m pytest -q tests/test_advisorship_matching.py tests/test_project_loader_matching.py tests/test_initiative_handlers.py tests/test_rule_version_guard.py
```

Then the full suite, compared with branch 034 (1188 passed, 10 skipped):

```bash
.venv/bin/python -m pytest -q
```

## 2. First local run: the rebuild

A database recorded under rule version 4 is reset by the weekly before use.

```bash
make weekly-flows > logs/weekly_035_run1.log 2>&1; echo "exit=$?" >> logs/weekly_035_run1.log
```

The log must show the rule-version reset. Then:

```bash
.venv/bin/python - <<'PY'
import collections, json, re, sqlite3, sys
sys.path.insert(0, ".")
from src.core.logic.advisorship_matching import base_title, year_range, years_differ
from src.core.logic.horizon_identity import normalize_text

c = sqlite3.connect("file:db/horizon.db?mode=ro", uri=True)
one = lambda q: c.execute(q).fetchone()[0]
print("rule version:", c.execute("select * from horizon_meta").fetchall())
print("advisorships:", one("select count(*) from advisorships"))
print("with more than one Student:", one(
    "select count(*) from (select advisorship_id from advisorship_members "
    "where role_name='Student' group by 1 having count(*)>1)"))
print("without a Student:", one(
    "select count(*) from advisorships a where not exists (select 1 from "
    "advisorship_members m where m.advisorship_id=a.id and m.role_name='Student')"))
print("duplicate initiative names:", one(
    "select count(*) from (select name from initiatives group by 1 having count(*)>1)"))
print("distinct names:", one(
    "select count(*) from initiatives i join advisorships a on a.id=i.id "
    "where i.name like '% | Orientacao%'"))

# Stored advisorships: base title -> [(student, years)]
stored = collections.defaultdict(list)
for name, start, end, student in c.execute(
    "select i.name, i.start_date, i.end_date, p.name from initiatives i "
    "join advisorships a on a.id=i.id "
    "left join advisorship_members m on m.advisorship_id=a.id and m.role_name='Student' "
    "left join persons p on p.id=m.person_id"):
    stored[base_title(name)].append((normalize_text(student or ""), year_range(start, end)))

def sig_year(value):
    m = re.match(r"\d{2}-\d{2}-(\d{2})$", str(value or "").strip())
    return 2000 + int(m.group(1)) if m else None

missing = collections.Counter()
for system, payload in c.execute(
    "select source_system, raw_payload_json from source_records "
    "where source_entity_type='advisorship'"):
    row = json.loads(payload)
    if system == "lattes_advisorships":
        title = (row.get("title") or "").strip()
        student = normalize_text(row.get("student_name") or "")
        years = year_range(row.get("start_year"), row.get("end_year"))
    else:
        title = str(row.get("TituloPT") or "").strip()
        student = normalize_text(str(row.get("Orientado") or ""))
        years = year_range(sig_year(row.get("Inicio")), sig_year(row.get("Fim")))
    if not title or not student:
        continue
    if not any(s == student and not years_differ(years, y) for s, y in stored[title]):
        missing[system] += 1
print("items without an advisorship of their student and years:", dict(missing))
print("'Estágio Supervisionado Obrigatório':",
      len(stored["Estágio Supervisionado Obrigatório"]), "advisorships,",
      len({s for s, _ in stored["Estágio Supervisionado Obrigatório"]}), "students")
print("ids:", c.execute(
    "select rule, count(*) from horizon_ids where entity_type='advisorship' group by 1").fetchall())
PY
```

Expected:

| Check | Before | Expected | Criterion |
|-------|--------|----------|-----------|
| Rule version | 4 | 5 | SC-008 |
| Advisorships | 10,260 | about 11,890 | SC-001 |
| Items without an advisorship of their student and years | 1,537 Lattes pairs, 89 SigPesq rows | 0 for both sources | SC-001, SC-002 |
| "Estágio Supervisionado Obrigatório" | 1 advisorship | one per student (49 items) | SC-003 |
| Advisorships with more than one Student | 0 | 0 | SC-005 |
| Advisorships without a Student | 0 | 0 | SC-005 |
| Duplicate initiative names | 0 | 0 | SC-005 |

The item check compares student names. A SigPesq row whose student was matched
by e-mail to a person with another spelling can appear as missing; each such
row is checked by hand against its advisorship before it counts as a failure.

Other tables (SC-006): compare the counts of projects, articles, professional
activities, awards, academic educations and technical productions with
`data/_backup_2026-11-11_post034_run1/`; differences must come only from
curricula downloaded again.

Old ids (FR-015): from the id report of the run, the number of advisorship ids
that became aliases and the number retired. Both are recorded in `tasks.md`.

Replaced students (SC-002): for the SigPesq titles with a cancelled row and a
row of another student, both students have an advisorship and only the
cancelled row's advisorship has `cancelled = 1`.

## 3. Second local run: nothing changes

Keep a copy of the database of step 2, then:

```bash
make weekly-flows > logs/weekly_035_run2.log 2>&1; echo "exit=$?" >> logs/weekly_035_run2.log
```

Compare `initiatives` (id, name), `advisorships`, `advisorship_members` and the
advisorship rows of `horizon_ids` between the two databases. Expected: no
difference for an advisorship whose sources did not change (SC-007); every
difference is explained by a curriculum downloaded again or a changed SigPesq
report.

## 4. Fork (end of the batch)

Two weekly runs on the fork, once, on this branch, for specs 034 and 035
together, only with the maintainer's approval. The first run rebuilds the
persistent database (rule version 5); the second must write no advisorship or
professional-activity change for unchanged sources.
