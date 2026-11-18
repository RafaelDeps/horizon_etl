# Quickstart: validate spec 041

**Feature**: `041-dashboard-visible-fixes`

The batch rule applies: two local validations, then weekly runs on the
RafaelDeps fork. No weekly, `full-refresh` or `db-reset` starts without the
maintainer's go-ahead. Back up `db/horizon.db` and `data/` before any local
run that writes.

## 1. Unit tests

```bash
.venv/bin/python -m pytest tests/test_person_name_rules.py tests/test_title_rules.py tests/test_student_name_rules.py tests/test_lattes_parser.py tests/test_initiative_handlers.py tests/test_canonical_exporter.py tests/test_notify_slack.py tests/test_weekly_etl_workflow.py tests/test_rule_version_guard.py -q
```

Then the full suite, and black, isort and flake8 on the touched files.

## 2. Baseline counts (before)

Count on the published exports of fork main (`c5ffe55`) with a read-only
script in the session scratchpad:

| Check | Expected before |
|---|---|
| One-word people that are fragments (contract 1) | about 40 of 49 one-word people |
| People whose name holds "/" | 55 |
| People whose name holds a citation | 5 |
| Initiatives whose team repeats a `person_id` | 1 |
| Self-edges per collaboration graph | 9 |
| Titles with " ? " (initiatives / productions / articles) | 237 / 57 / 80 |
| Articles with a year outside 1950 to the current year plus one | 3 |
| Degrees whose advisor is a fragment | about 110 |

## 3. Local validation 1 (rebuild)

The local database is at rule version 6, so the guard resets it. After the
maintainer's go-ahead, run the weekly locally, then:

- Every check of section 2 is 0, except the source errors kept on purpose:
  - 1 titleless article;
  - 3 workplans that end before they start;
  - one-word names that are real ("Graciela", "Alan", …);
  - texts listed in `docs/backlog.md`.
- `horizon_meta.rule_version` is 7.
- Every horizon_id of the previous exports resolves: directly, through an
  alias, or as `retired` with a reason. Use the id contract check of the
  2026-11-17 analysis.
- All other counts are equal or higher (articles, initiatives, productions,
  groups, advisorships, graph nodes). The people count changes only by the
  fake people removed and the split students added.
- Spot checks:
  - degrees whose advisor was "Prof" now point to "José Antônio da Silva",
    and so on;
  - the advisorship of "Gladston Campos/Niase Borjaille" has two students;
  - initiative 7622 lists its coordinator once, with start 2019;
  - "Nova Venécia – ES" shows a dash.

## 4. Local validation 2 (fixpoint)

Run again with the same sources:

- No data change against validation 1.
- Only `ingestion_runs` grows.

## 5. Fork runs

1. Push the branch to the fork (origin) only.
2. Dispatch the weekly on `041-dashboard-visible-fixes`, after the go-ahead.
   - The Slack channel gets **no** message.
   - The log of both notice steps shows `::notice::Slack pulado: a branch
     041-dashboard-visible-fixes não é a main.`
   - The run result does not depend on the notice.
3. Check the archives of that run against section 3.
4. The first run after the rebuild may miss items of curricula whose download
   failed (no old data to keep). Compare the second run, as on 2026-11-17.
5. After the merge to fork main, a run on main sends both messages (start, and
   end with the archive commit).
6. `grep -c hooks.slack.com` on every log gives 0.
