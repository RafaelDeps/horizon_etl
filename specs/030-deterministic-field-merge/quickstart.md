# Quickstart: Fixed Rule for Fields Written by Several Documents

**Branch**: `030-deterministic-field-merge`

## 1. Unit tests

```bash
.venv/bin/python -m pytest -q tests/test_field_merge.py tests/test_field_claim_store.py tests/test_field_merge_loaders.py
```

What they cover:
- the rule;
- the permutations of SC-002;
- the empty and "Unknown" values;
- the claims lifecycle;
- the TD-029 collision.

Then run the full suite. The known failures are the same 6 as before, plus
the 4 that need `db/horizon.db` when the suite runs outside the main checkout.

```bash
.venv/bin/python -m pytest -q
```

## 2. Reproduce TD-029 on the 2026-10-29 database

Download the artifact of CI run 40952053776 into the scratch folder, never
into `db/`:

```bash
gh run download 40952053776 --repo RafaelDeps/horizon_etl -n weekly-etl-artifacts -D /tmp/td029
```

Load CV `1703547133505721` against a copy of that database. Before the fix the
CV is `partial` with `UNIQUE constraint failed: initiatives.name`. After the
fix it loads fully, with no partial status.

## 3. Replay (SC-001, SC-003)

Back up `db/horizon.db` and `data/` first. That backup is required before any
write to the real database.

1. `make full-refresh`, then copy the database to `rebuild_a.db`.
2. `make weekly-flows` once more. This pass is not an unchanged one: it
   always downloads the SigPesq reports again, and it refreshes a share of the
   Lattes curricula and CNPq pages (`REFRESH_SHARE` must be in (0, 1]; `0` is
   rejected and replaced by 0.25). It checks that a second weekly on a
   populated database runs clean.
3. Unchanged pass: run only the phases that read files already on disk, with
   no download:

   ```bash
   .venv/bin/python app.py ingest_lattes_projects
   .venv/bin/python app.py lattes_advisorships
   .venv/bin/python app.py enrich_projects
   ```

   Every document is skipped and no table changes, apart from
   `ingestion_runs` and `last_seen_at` (compare a copy taken before the pass
   with one taken after, table by table).
4. Change two CVs in `data/lattes_json/` (a description, a status) and one
   SigPesq row. Then run the same local phases once.
5. Rebuild from the same final inputs, into `rebuild_b.db`.
6. Compare:

   ```bash
   .venv/bin/python specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py db/horizon.db rebuild_b.db
   ```

   Expected: 0 different rows in `initiatives`, `advisorships` and
   `fellowships`. Before this feature: about 130, 123 and 5.

## 4. Log check (SC-005)

In the weekly log, each writing phase has one line:

```
field merge lattes_projects: fields=… by_date=… by_source=… by_tiebreak=… collisions_resolved=… collisions_reported=…
```

The first three counts add up to the number of fields that had more than one
different non-empty value.

## 5. Rule version

On a database kept from before this feature, the first `make weekly-flows`
logs the rule version change and rebuilds once.

In GitHub Actions, the first run of the branch starts from scratch anyway,
because the restore only reads runs of the same branch.

## 6. Fork run

Dispatch `weekly-etl.yml` on `030-deterministic-field-merge`. Ask the
maintainer before dispatching. Then check:
- every phase ends with exit 0;
- the `field merge` lines appear;
- the `SQLite finalize` line ends with `'finalized': True`.
