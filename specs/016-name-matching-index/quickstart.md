# Quickstart: Verifying the Name-Matching Index

Commands run from the repository root with the project venv. `$REPLAY` is the
spec 015 replay directory outside the repository. It holds `inputs/`,
`pre_lattes.db`, `feature_sigpesq.db` (the reference), `feature_lattes.db` (the
reference), `prep_run.sh`, `env.sh`, `replay_sigpesq.py` and `compare.py`.

## 1. Tests

The equivalence tests must pass under both implementations:

```bash
.venv/bin/python -m pytest -q tests/test_person_matcher_index.py tests/test_researcher_resolution_cache.py tests/test_lattes_task_quoting.py
```

```bash
RAPIDFUZZ_IMPLEMENTATION=python .venv/bin/python -m pytest -q tests/test_person_matcher_index.py
```

The equivalence tests compare the new `PersonMatcher` with a frozen copy of the
pre-016 algorithm, kept in the test module as the oracle, on:
- fixtures with duplicate normalised keys;
- re-registered raw names;
- strict mode;
- empty and punctuation-only names;
- a few thousand perturbed real-style names.

## 2. Controlled replay (SC-004)

Run only the spec 016 code, against the spec 015 reference:

1. `D=$($REPLAY/prep_run.sh /home/rafael/horizon_etl s016_sigpesq)`, then
   `source $REPLAY/env.sh`.
2. `DATABASE_URL=sqlite:///$REPLAY/s016_sigpesq.db` on a fresh file: run
   `db/create_db.py`, then `replay_sigpesq.py` (with `PYTHONPATH=$D`, from `$D`).
3. Run `compare.py $REPLAY/feature_sigpesq.db $REPLAY/s016_sigpesq.db`. It must
   print `RESULT: IDENTICAL`.
4. `D=$($REPLAY/prep_run.sh /home/rafael/horizon_etl s016_lattes)`. Copy
   `pre_lattes.db` to `s016_lattes.db`, then run
   `app.py ingest_lattes_projects` and `app.py lattes_advisorships` against it.
5. Run `compare.py $REPLAY/feature_lattes.db $REPLAY/s016_lattes.db`. It must
   print `RESULT: IDENTICAL`.

Record the two Lattes phase durations and the new summary lines.

## 3. Full timing run (SC-001, SC-002, SC-003, SC-005)

```bash
make weekly-flows > logs/weekly_016_validation.log 2>&1
```

Disable Telegram (empty `HORIZON_TELEGRAM_*` variables) for validation runs.
Check:
- **SC-001 / SC-002:** both Lattes phases under 20 min, with exit 0.
- **SC-003:** the mean of the last 50 / first 50
  `Lattes lattes_advisorships CV ... took Xs` lines is ≤ 1.2.
- **SC-005:** the total excluding `cnpq` is below the spec 015 run, 104.5 min
  (181.3 min minus 76.8 min for CNPq).
- **Summary lines:** four `Person matching [...]` lines and two
  `Researcher resolution [...]` lines are present, with `create_failed=0`.

Do not run the full validation right after another full CNPq crawl: the spec 015
validation hit 85 connection resets that way. Space them out by several hours.
