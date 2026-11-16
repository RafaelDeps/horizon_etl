# Quickstart: validating spec 034

**Feature**: `034-keep-professional-activities`

Every step that runs the weekly needs the maintainer's approval first. Before
a local run, back up `db/horizon.db` and `data/`.

## 1. Unit tests

```bash
.venv/bin/python -m pytest -q tests/test_professional_activity_rules.py tests/test_lattes_parser.py tests/test_horizon_identity.py tests/test_horizon_id_assigner.py tests/test_rule_version_guard.py tests/test_incremental_lattes.py
```

Then the full suite, compared with branch 033 (1080 passed, 10 skipped):

```bash
.venv/bin/python -m pytest -q
```

## 2. The rules over the real curricula (read only, no database)

```bash
.venv/bin/python - <<'PY'
import collections, json, pathlib, sys
sys.path.insert(0, ".")
from src.adapters.sources.lattes_parser import LattesParser
parser = LattesParser()
rows, country, only = 0, collections.Counter(), 0
detail = ("period", "start_year", "end_year", "bond", "classification", "work_regime", "role_function")
for f in sorted(pathlib.Path("data/lattes_json").glob("*.json")):
    for a in parser.parse_professional_activities(json.loads(f.read_text())):
        rows += 1
        country[a["institution_country"]] += 1
        only += all(a[k] is None for k in detail)
print("items to store:", rows, "| institution-only:", only)
print("countries:", country.most_common(6))
PY
```

Expected: about 9,555 items, about 163 institution-only, "Brasil" about
8,918, no "IFES" among the countries.

## 3. Local rebuild

One `make weekly-flows`. The database is at rule version 3, the code at 4, so
the log must show "Database rule version differs from the code's; rebuilding
it once before the phases" and the `Horizon ids:` line must say rule version
4.

## 4. Checks on the rebuilt database (read only)

```bash
.venv/bin/python - <<'PY'
import collections, json, pathlib, sqlite3, sys
sys.path.insert(0, ".")
from src.adapters.sources.lattes_parser import LattesParser
c = sqlite3.connect("file:db/horizon.db?mode=ro", uri=True)
q = lambda s, *a: c.execute(s, a).fetchall()
fields = ("institution", "institution_name", "institution_acronym", "institution_country",
          "period", "start_year", "end_year", "bond", "classification", "work_regime",
          "role_function", "activity_type", "current")
detail = "period is null and start_year is null and end_year is null and bond is null and classification is null and work_regime is null and role_function is null"
print("rows:", q("select count(*) from professional_activities")[0][0])
print("SC-003 country in capitals:", q("select count(*) from professional_activities where institution_country is not null and institution_country = upper(institution_country)")[0][0])
print("SC-003 IFES example:", q("select distinct institution_name, institution_acronym, institution_country from professional_activities where institution like 'Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo, IFES, Brasil'"))
print("institution-only rows:", q(f"select count(*) from professional_activities where {detail}")[0][0])
print("SC-002 institution-only beside a filled row:", q(
    f"select count(*) from professional_activities e where {detail} and exists (select 1 from professional_activities f "
    "where f.researcher_id = e.researcher_id and f.institution = e.institution and f.id != e.id)")[0][0])
print("SC-004 ids with a collision suffix:", q("select count(*) from horizon_ids where entity_type = 'professional_activity' and collision_suffix is not null and collision_suffix != ''")[0][0])
print("rule version:", q("select value from horizon_meta where key = 'rule_version'"))
# SC-001: every item the parser returns for a curriculum is a row of its researcher.
parser, missing, checked = LattesParser(), 0, 0
stored = collections.defaultdict(set)
for row in q("select r.cnpq_url, " + ", ".join("a." + f for f in fields) + " from professional_activities a join researchers r on r.id = a.researcher_id"):
    stored[str(row[0] or "")[-16:]].add(tuple(row[1:]))
for f in sorted(pathlib.Path("data/lattes_json").glob("*.json")):
    lattes_id = f.stem.split("_")[-1]
    if lattes_id not in stored:
        continue
    for a in parser.parse_professional_activities(json.loads(f.read_text())):
        checked += 1
        missing += tuple(a[k] for k in fields) not in stored[lattes_id]
print("SC-001 curriculum items checked:", checked, "| missing from the database:", missing)
PY
```

Expected:

- about 9,555 rows (7,855 before); SC-001: 0 items missing;
- SC-003: 0 countries written in capitals; the IFES example gives the full
  name, "IFES" and "Brasil";
- about 163 institution-only rows and 0 beside a filled row (SC-002);
- SC-004: no more ids with a collision suffix than before (114; about 6
  expected);
- rule version `4`.

SC-005, compared with the copy of the database taken before the run: the
counts of `awards`, `academic_educations`, `articles`, `research_productions`,
`initiatives` and `advisorships` are the same, except for the curricula that
changed between the two downloads (compare `data/lattes_json/` with the
backup to list them).

Old ids: from the backup database, take a few ids of
`horizon_ids where entity_type = 'professional_activity'`; each must be in
`horizon_id_aliases` of the new database, with a target or with reason
`retired`. The `Horizon ids:` line of the log gives the totals per reason.

## 5. Second local run

Copy `db/horizon.db` and `data/lattes_json/` first, then one more
`make weekly-flows`. The refresh share cannot be 0, so part of the curricula
is downloaded again. Compare with the copy:

- for the curricula whose file did not change, the rows of
  `professional_activities` and their ids in `horizon_ids` are identical
  (SC-006);
- every activity created or removed belongs to a curriculum whose file
  changed.

## 6. Fork

Only on the RafaelDeps fork, with approval: the first weekly of the branch
and a second one over the restored database. In
`professional_activities_canonical.json` of both: no `institution_country`
in capitals, the same number of rows in both runs apart from changed
curricula, and identical activity rows in `horizon_ids_canonical.json` for
unchanged curricula.
