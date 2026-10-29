# Quickstart: validating the skip of unchanged documents

Replays work on copies in the scratchpad (`$S`). The local weekly (§4) runs
on `db/horizon.db` itself, by the maintainer's decision of 2026-10-28, after
the backup in `data/_backup_2026-10-28_pre021/` (some phases ignore
`DATABASE_URL`, TD-026). Leave the Telegram variables empty in every replay.
SigPesq and CNPq are replayed from frozen inputs, not from the portals, with
the throwaway harnesses described in spec 020's quickstart §2 (rebuild them in
the scratchpad; they are not committed).

```bash
S=/tmp/claude-1000/-home-rafael-horizon-etl/<session>/scratchpad/skip021
mkdir -p $S
cp db/horizon.db $S/base.db           # a database built by the spec 020 code
```

## 1. Automated tests

```bash
make ci-check
```

New tests (temporary SQLite files, no portal):

| Test | Covers |
|---|---|
| unchanged inputs: every document skipped, every table identical before/after except `ingestion_runs` and `last_seen_at` | SC-001, FR-004 |
| one changed CV: only that CV processed; result equals a rebuild on the same inputs, compared as the spec's "How equivalence is measured" says | SC-003, FR-011 |
| CV drops an article only it carried → article deleted, id retired; co-authored article → only the link removed | FR-011, FR-012 |
| person referenced only by a dropped item → deleted; person with an active CV → kept | FR-011a |
| unreadable CV (`Nome-nao-identificado`), CV with zero items after having items, CNPq page that fails, listed lattes_id without JSON → nothing deleted, processing state unchanged (only the failure record is written) | SC-004, FR-008 |
| section failure inside a CV → `failed:partial`, nothing deleted | R4 |
| document absent from a complete listing → inactive; failed or partial listing → nothing; listed again → active | SC-005, FR-009, FR-010 |
| new SigPesq initiative matching an advisorship of an unchanged CV → only that CV reprocessed | FR-005 |
| new person whose name fuzzy-matches a team member of an unchanged CV better than the recorded match → only that CV reprocessed | FR-005 |
| merge of two persons → links re-pointed; the documents that resolved to the loser reprocessed once | R6, R3 |
| library commits inside a document are not visible to another connection until the document commits; both library clients share the connection | FR-006, R5 |
| exception after some writes of a document → no row of the attempt remains, phase caches reloaded, next document correct | FR-006, R5 |
| process killed in the middle of a document → database as before the document; next run processes it | FR-006, R5 |
| a per-document phase never opens a second writing connection; the rebinding of `_SessionLocal` still applies to the installed library versions | R5 |
| `make weekly-flows` on an existing database does not reset it; rule-version mismatch rebuilds once | FR-013, FR-014 |
| `source_document_states_canonical.json` present, sorted, fields as in the contract, no PII | FR-016, FR-017 |

## 1a. Proof of concept inside the ETL (first task)

On a copy, run `lattes_projects` for one CV and `cnpq` for one group with the
document transaction (R5), then with today's code on another copy, and compare
every table: identical. Then make the CV fail after its first writes (inject an
exception) and check that no row of it remains. If either check fails and
cannot be fixed without editing a library, switch to the fallback of the
contract (rule 9) and record it in the plan.

## 2. Unchanged inputs on a populated copy

```bash
cp $S/base.db $S/inc.db
DATABASE_URL=sqlite:///$S/inc.db TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= \
  <replay harness: sigpesq, cnpq, lattes_projects, lattes_advisorships, enrich_projects>
```

- First pass: every document `processed` (bootstrap, no states yet), no item
  deleted.
- Second pass: every document `skipped`; dump every table before and after:
  identical apart from the `ingestion_runs` rows and `last_seen_at` (SC-001). Record the time of each phase.

## 3. One changed CV, then several changes

Copy the frozen Lattes JSONs to `$S/lattes_json/`, then:

1. edit one CV: add one article, remove one article only it carries, remove
   one co-authored article;
2. run the incremental pass on `$S/inc.db`;
3. run a rebuild on the same inputs on `$S/rebuild.db`:
   `DATABASE_URL=sqlite:///$S/rebuild.db .venv/bin/python db/create_db.py`,
   then the replay. Do **not** use `make db-reset` here: `db-clean` deletes
   `db/horizon.db` whatever `DATABASE_URL` says;
4. compare:

```bash
.venv/bin/python -I specs/021-skip-unchanged-documents/research-scripts/compare_with_rebuild.py \
  $S/inc.db $S/rebuild.db
```

Expected: only the edited CV processed; the comparison (research R11) shows no
difference apart from the listed person-resolution order rows of spec 020 R9.3
and orphan reference rows.

Repeat with three more rounds of changes (a new CV in the list, a CV removed
from the list, an unreadable CV, a SigPesq row added that matches an existing
advisorship). After the last round, compare again (SC-006).

## 4. Local weekly and timing

```bash
sha256sum -c data/_backup_2026-10-28_pre021/SHA256SUMS.original   # before the first run only: db equals the backup
TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= make weekly-flows
TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID= make weekly-flows
```

Restore if needed: `cp -p data/_backup_2026-10-28_pre021/db/horizon.db db/horizon.db`.

Check that the second run did not reset the database, read
`data/reports/source_document_states_report.json`, and compare the phase times
with `logs/weekly_018_validation.log` (2026-10-24: `lattes_projects` 7.4 min,
`lattes_advisorships` 12.4 min). Target (reference, SC-002): both at most
2 min together on the second run. Also time the first run (every document
processed, one commit per document instead of ~180 000 per phase) against the
same baseline.

## 5. CI

Only after §1–§4: push to the fork and dispatch the weekly workflow. The
database starts empty, so the run is a rebuild: it must succeed with the same
exports as the last CI run plus `source_document_states_canonical.json`
(SC-008). Record the numbers in `docs/reports/2026-XX-XX-skip-unchanged-validation.md`.
