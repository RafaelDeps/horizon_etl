# Quickstart: Verifying the Concurrent CNPq Sync

`$R` is the scratchpad directory
`/tmp/claude-1000/-home-rafael-horizon-etl/326c8482-b2cb-4ce7-918a-b95d4469a905/scratchpad`.
Spec 015 replay assets live in `$R/replay`; this feature's assets live in
`$R/replay017`. Nothing there is committed.

## 1. Tests

```bash
.venv/bin/python -m pytest -q tests/test_cnpq_concurrent_fetch.py tests/test_cnpq_sync.py
```

The tests use a fake adapter with controllable delays and failures, and cover:
- at most N in flight;
- writes on the flow thread, in the original order;
- retries with waits, using an injected sleep;
- the burst rule reducing the limit;
- N = 1;
- the researcher index loaded once, with a researcher created by one group found
  by a later group.

## 2. Controlled replay (SC-004)

Inputs:
- `$R/replay017/cnpq_payloads.json`: the 350 captured payloads, exported from
  the spec 016 validation database;
- the frozen SigPesq inputs in `$R/replay/inputs`.

Steps:
1. **Pre-CNPq snapshot.** Use `$R/replay/prep_run.sh <code> <name>` and
   `$R/replay/env.sh`. Then `db/create_db.py` and `$R/replay/replay_sigpesq.py`
   on a fresh database. Copy it to `$R/replay017/pre_cnpq.db`.
2. **Harness.** `$R/replay017/replay_cnpq.py` is a throwaway Prefect flow that
   patches `CnpqCrawlerAdapter.get_group_data` to return the captured payload
   for the URL, with a random 0.5–3 s delay, and then calls
   `sync_cnpq_groups_flow()`.
3. **Base run.** Run the harness with the **base** code (a copy of the spec 016
   source, branch `019-name-matching-index`) on a copy of `pre_cnpq.db`, giving
   `base_cnpq.db`.
4. **Feature run.** Run it with the **feature** code on another copy, giving
   `feature_cnpq.db`.
5. **Compare** with an extended `compare.py`:
   - counts of `research_groups`, `team_members`, `persons`, `researchers`,
     `knowledge_areas` and `group_knowledge_areas`;
   - the name-based membership set;
   - `source_records` counts by `source_entity_type`.

   It must print `RESULT: IDENTICAL`.

## 3. Full timing run (SC-001)

```bash
make weekly-flows > logs/weekly_017_validation.log 2>&1
```

- Run it with the Telegram variables exported empty.
- Do not start it within a few hours of another full CNPq crawl.

Check:
- the `cnpq` phase duration against the spec 016 run (54.4 min);
- `CNPq sync: 350/350`;
- the `CNPq fetch: …` line (retries, failed after retries, reductions);
- no `database is locked` anywhere in the log.
