# Quickstart: Validating the Enrichment Lock Fix

`$R` = `~/.cache/horizon_wal_replay` (created by spec 018; on disk, outside the
repository). It already holds:
- `ci_artifact/`: the `weekly-etl-artifacts` of CI run 40002646510 (database and
  `data/`);
- `ci_pre_enrich.db`: a copy of that run's database;
- `base.db`: a local database right after both Lattes phases (spec 018 replay),
  i.e. right before `extract_project_files` and `enrich_projects`.

Telegram off for every run:

```bash
export HORIZON_TELEGRAM_BOT_TOKEN= HORIZON_TELEGRAM_CHAT_ID= TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= HORIZON_QUIET_PREFECT=1 PREFECT_LOGGING_TO_API_ENABLED=false
```

If `$R/ci_artifact` is gone, download it again (≈ 281 MB):
`gh run download 40002646510 -R RafaelDeps/horizon_etl -n weekly-etl-artifacts -D $R/ci_artifact`.

## 1. Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_project_enrichment_db.py tests/test_project_enrichment_lock.py
```

With the base code, the cross-type duplicate test reports `created == 1` and the
lock test gets `database is locked`; with the fix, both pass.

## 2. CI replay (the failure)

`enrich_projects` reads `data/exports/project_sigpesq_files_json/` relative to
the working directory, so each run uses its own working directory with a copy of
the artifact's `data/`:

```bash
for v in base feature; do
  rm -rf $R/w019_$v && mkdir -p $R/w019_$v && cp -r $R/ci_artifact/data $R/w019_$v/data
  cp $R/ci_pre_enrich.db $R/ci019_$v.db
done
# base: a copy of the code before the fix in $R/base019_code (with .env symlinked)
(cd $R/w019_base && PYTHONPATH=$R/base019_code DATABASE_URL=sqlite:///$R/ci019_base.db \
  /home/rafael/horizon_etl/.venv/bin/python $R/base019_code/app.py enrich_projects)
(cd $R/w019_feature && PYTHONPATH=/home/rafael/horizon_etl DATABASE_URL=sqlite:///$R/ci019_feature.db \
  /home/rafael/horizon_etl/.venv/bin/python /home/rafael/horizon_etl/app.py enrich_projects)
```

Expected: base fails with `database is locked`; feature exits 0 with
`enriched 251, created 17, errors 0, skipped_duplicate 1` in
`Enrichment finished`.

## 3. Local replay (no collision → identical output)

Same as §2, but with `$R/base.db` copied to `$R/loc019_<v>.db` and a working
directory holding a copy of the repository's `data/exports/project_sigpesq_files_json/`
(322 documents). Both runs must exit 0. Compare the two databases:

```sql
SELECT name, initiative_type_id, coalesce(description,''), coalesce(enrichment_json,'')
FROM initiatives ORDER BY name;

SELECT source_system, source_entity_type, COUNT(*) FROM source_records GROUP BY 1, 2;
SELECT COUNT(*) FROM entity_matches;
SELECT COUNT(*) FROM attribute_assertions;
SELECT COUNT(*) FROM entity_change_logs;
```

Expected: identical. `enrichment_json` carries no run-time timestamp
(`extracted_at` comes from the document, `reviewed_at` from the prior payload),
and new initiatives' `status` depends only on the date, so run both replays on
the same day.

## 4. Lint and full suite

```bash
black --check src/core/logic/project_enrichment.py tests/test_project_enrichment_db.py tests/test_project_enrichment_lock.py
isort --check src/core/logic/project_enrichment.py tests/test_project_enrichment_db.py tests/test_project_enrichment_lock.py
flake8 . --count --select=E9,F63,F7,F82 --statistics
PYTHONPATH=. .venv/bin/python -m pytest -q tests/
```

Expected: no new failures beyond the 6 pre-existing ones. Also run the two test
files on Python 3.12 with SQLAlchemy 2.1 (the CI combination).
