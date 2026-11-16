# Quickstart: validating spec 033

## 1. Tests

```bash
.venv/bin/python -m pytest -q tests/test_horizon_identity.py tests/test_lattes_articles.py tests/test_tracking_keys.py tests/test_reference_consolidator.py tests/test_article_consolidation.py tests/test_rule_version_guard.py
.venv/bin/python -m pytest -q
```

Expected: the rule tests (contracts/doi-rule.md) pass; the full suite has no
failure.

## 2. Rebuild on the local database

Ask the maintainer first. Back up `db/horizon.db` and `data/` before. The
local database was written under rule version 2, so the weekly rebuilds it on
its own:

```bash
make weekly-flows
```

Expected in the log: `Database rule version differs from the code's;
rebuilding it once before the phases (FR-024).` and, at the end,
`Horizon ids: … rule version 3`.

## 3. Checks on the rebuilt database (read only)

```bash
.venv/bin/python - <<'PY'
import json, re, sqlite3, collections, unicodedata
c = sqlite3.connect("file:db/horizon.db?mode=ro", uri=True)
q = lambda s: c.execute(s).fetchall()
form = re.compile(r"^10\.\d{4,9}(\.\d+)*/\S+$")
dois = [d for (d,) in q("select doi from articles where doi is not null and doi != ''")]
print("SC-003 stored values that are not DOIs:", sum(not form.match(d) for d in dois))
def norm(t):
    s = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()
titles = collections.defaultdict(set)
for payload, article_id in q(
    "select s.raw_payload_json, m.canonical_entity_id from source_records s "
    "join entity_matches m on m.source_record_id = s.id "
    "where s.source_entity_type = 'article' and m.canonical_entity_type = 'article'"
):
    titles[article_id].add(norm(json.loads(payload).get("title")))
many = {a: t for a, t in titles.items() if len(t) > 1}
no_doi = [a for a in many if not q(f"select doi from articles where id = {a}")[0][0]]
print("articles fed by more than one title:", len(many), "(expected 20, all with a DOI)")
print("SC-001 of those, without a stored DOI:", len(no_doi))
print("rule version:", q("select value from horizon_meta where key = 'rule_version'"))
PY
```

Expected:

- SC-003: `0` stored values that are not DOIs (45 before).
- About 20 articles fed by more than one title, all with a stored DOI
  (SC-004); `0` without one (SC-001; before, 2 articles hid about 69 works
  under a Scopus link and an ISSN).
- SC-002: the titles of a sample of the hidden works (for example "Thermal
  comfort temperature update for broiler chickens up to 21 days of age") exist
  as their own article, linked to the researcher whose curriculum lists them.
- Rule version `3`.
- SC-005: the counts of awards, languages, technical productions, projects
  and advisorships are compared with the 2026-11-10 run (183 awards, 794
  languages, 3,999 technical productions). The weekly downloads part of the
  curricula again, so a count may differ by the items of the curricula that
  changed; any other difference is a defect.
- Old id (spec, edge cases): the permanent id the Scopus `doi=null` article
  had before the rebuild (`article:doi:http://www.scopus.com/…doi=null…`, read
  from the backup database) is found in `horizon_id_aliases` or reported as
  retired in the `Horizon ids:` log line; it is not lost without a record.

## 4. Second run writes nothing

Run the weekly again:

```bash
make weekly-flows
```

The share of curricula downloaded again cannot be zero (`REFRESH_SHARE` only
accepts a fraction above 0 and falls back to 0.25), so some curricula change
between the two runs. The check is therefore made on the curricula that did
not change:

- every `entity_change_logs` row for an article in the second
  `lattes_projects` run comes from a curriculum that was downloaded again and
  changed (list the changed Lattes ids from the run log); none comes from an
  unchanged curriculum (SC-006);
- the articles of the unchanged curricula have the same permanent ids and the
  same stored DOI in both runs, so the incremental database agrees with the
  rebuild (User Story 4, scenario 3);
- record how many aliases the rebuild created (the `Horizon ids:` log line of
  step 2).

## 5. Fork

After the maintainer approves: one weekly on the fork branch restores the
database of the previous run, rebuilds it because of the rule version
(SC-007), and a second weekly writes no article change over unchanged
curricula. The exported `articles_canonical.json` has no `doi` that contains
`scopus.com` or lacks DOI form.
