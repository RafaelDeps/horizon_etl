# Fluxos e Entrypoints

## Entry points principais

Os pontos de entrada mais relevantes hoje sao:

- `make full-refresh`
- `make pipeline-serra`
- `make ingest-sigpesq`
- `make ingest-lattes-full`
- `make export-canonical CAMPUS=Serra`
- `python app.py full_pipeline Serra data/exports`
- `python app.py all_sources Serra`
- `python app.py sigpesq`
- `python app.py cnpq_sync Serra`

## Organizacao dos flows

Os flows agora ficam separados por origem ou responsabilidade:

- `src/flows/sigpesq/`: grupos, projetos, planos de trabalho e flow SigPesq completo.
- `src/flows/lattes/`: download, projetos, orientacoes e flow Lattes completo.
- `src/flows/cnpq/`: sincronizacao de grupos CNPq.
- `src/flows/exports/`: exportacao canonica, marts e grafo de pessoas.
- `src/flows/pipelines/`: pipelines operacionais que combinam ingestao e exportacao.
- `src/flows/all.py`: flow geral de ingestao que chama todas as fontes.

Nao ha wrappers de compatibilidade no topo de `src/flows`; use sempre os caminhos
por pasta, como `src.flows.sigpesq.all` ou `src.flows.exports.canonical_data`.

## Comando recomendado para refresh completo

O comando mais importante para operacao e:

```bash
make full-refresh
```

Ele executa:

1. limpeza do banco local
2. recriacao do schema
3. subida do Prefect Server local
4. execucao do pipeline unificado para todos os campi

## Fluxo unificado

O `full_ingestion_pipeline` coordena, em alto nivel:

1. ingestao SigPesq
2. ingestao Lattes
3. sincronizacao CNPq
4. exportacoes canonicas
5. geracao de marts
6. escrita de reports operacionais

## Lattes

O download de curriculos Lattes chama `scriptLattes`. Essa dependencia ainda
usa Selenium internamente, entao o flow valida a compatibilidade entre o
Chrome/Chromium local e o `./chromedriver` antes de limpar `data/lattes_json` e
baixar novos JSONs.

Quando existir mais de um navegador instalado, informe o binario desejado:

```bash
CHROME_BINARY=/caminho/para/chrome make ingest-lattes-download
CHROME_BINARY=/caminho/para/chrome make ingest-lattes-full
```

Antes da chamada final ao `scriptLattes`, o flow baixa em paralelo os curriculos
ausentes no cache bruto `cache/`. O padrao usa 3 workers para reduzir o tempo de
download sem abrir muitas sessoes do Chrome de uma vez. Ajuste com
`HORIZON_LATTES_DOWNLOAD_WORKERS`; desative com `HORIZON_LATTES_PREFETCH=0`.

### Team lookup and per-CV timing logs (spec 015)

Team matching (`TeamSynchronizer.ensure_team`) reads `teams(id, name)` once per
loader and answers each record from memory. On a miss it first reads only the
teams created since its last read (for example research groups created by
another loader), and only then creates a team.

At the end of each loader's work, one INFO line summarises the lookup:

```text
Team lookup [lattes_advisorships]: loaded=3941 hits=1862 created=7844 refreshes=7844 refresh_found=0 failed=0
```

| Counter | Meaning |
|---|---|
| `loaded` | Teams read when the lookup was built |
| `hits` | Records answered from the lookup with no query |
| `created` | Teams created because no team matched |
| `refreshes` | Incremental reads (`id > last seen id`) made on misses |
| `refresh_found` | Misses answered by those reads: teams created by other code during the phase |
| `failed` | `ensure_team` calls that failed (the record gets no team; see the WARNING line) |

There are four labels per weekly run: `sigpesq_projects`,
`sigpesq_advisorships`, `lattes_projects` and `lattes_advisorships`.

In `lattes_projects` and `lattes_advisorships`, every CV also logs its duration
at INFO. INFO is used because `dgp_cnpq_lib` resets the loguru level to INFO, so
DEBUG never reaches the weekly log:

```text
Lattes lattes_advisorships CV 214/435 lattes_id=1854684270507362 took 1.8s
```

Spec 016 adds two more summary lines. Each loader logs one person-matching line
(`sigpesq_projects`, `sigpesq_advisorships`, `lattes_projects`,
`lattes_advisorships`), and each Lattes phase logs one researcher-resolution
line:

```text
Person matching [lattes_projects]: email=0 canonical=11427 exact=190 normalised=7 invariant=49 fuzzy=86 strict_rejected=177 created=3504 create_failed=0
Researcher resolution [lattes_projects]: lookups=1504 tier200=0 tier150=476 tier100=52 tier90=9 unresolved=967
```

| Counter | Meaning |
|---|---|
| `email` / `canonical` / `exact` / `normalised` / `invariant` / `fuzzy` | Persons found at each matching step, in that order |
| `strict_rejected` | Fuzzy candidates refused because the caller asked for an exact match (score below 100) |
| `created` / `create_failed` | Persons created because nothing matched, and creations that raised an error |
| `lookups` / `tier200`..`tier90` / `unresolved` | Researcher name resolutions, and which score tier the winner reached (identification, exact name, normalised name, particle-invariant name) |

`lattes_advisorships` resolves the CV owner by Lattes ID, not by name, so its
researcher-resolution line shows zeros.

To check that per-CV cost stays flat (SC-003 in
`specs/015-team-lookup-index/spec.md`), compare the mean of the first and the
last 50 such lines of a phase. The ratio should stay at or below 1.5.

### CNPq concurrency (spec 017)

The CNPq phase fetches group pages concurrently and writes them one at a time.
SQLite allows a single writer, so every database write happens on the flow
thread, in the original group order.

| Variable | Default | Meaning |
|---|---|---|
| `HORIZON_CNPQ_WORKERS` | `4` | Maximum simultaneous page fetches. `1` fetches sequentially. Invalid values fall back to 4 with a warning. |

A group whose page returns no data is retried up to 3 times, waiting about 30 s
and then 90 s, with the wait taken outside the fetch slots. If 4 failures happen
within 60 s, the number of simultaneous fetches is halved (never below 1). It
climbs back one step after 120 s without failures. Those changes are logged as
`CNPq fetch: failures clustering, concurrency 4 → 2` and
`CNPq fetch: portal calm, concurrency 2 → 3`.

At the end of the phase:

```text
CNPq fetch: workers=4 fetched=350 retries=0 failed_after_retries=0 concurrency_reductions=0 researcher_index_loaded=525 researcher_hits=3772 researcher_created=6160
```

| Counter | Meaning |
|---|---|
| `fetched` / `failed_after_retries` | Groups with data, and groups still without data after every attempt. The latter are reported as `cnpq_group_sync_failed`. |
| `retries` | Extra attempts beyond the first, summed over all groups |
| `concurrency_reductions` | How many times a failure burst halved the concurrency |
| `researcher_index_loaded` / `researcher_hits` / `researcher_created` | Researchers loaded once for the phase, members matched to them, and researchers created during the phase |

## Persistent database and unchanged documents (spec 021)

Since spec 021 the database persists between runs. `make weekly-flows` no
longer resets it: it depends on `make db-ensure`, which creates
`db/horizon.db` (the path comes from `DATABASE_URL`) only when the file does
not exist, and otherwise only applies the pending ETL migrations. A fresh
machine or CI runner therefore still starts from an empty database. To rebuild
on purpose, use `make full-refresh` (or `make db-reset` followed by the
flows); both keep the horizon id history.

Every per-document phase works one source document at a time: a Lattes CV
(`lattes_projects`, `lattes_advisorships`), a CNPq group page (`cnpq_group`),
a SigPesq report row (`sigpesq_group`, `sigpesq_project`,
`sigpesq_advisorship`). The enrichment phase (`enrich_projects`) is not part
of this. Each document ends in one of these outcomes:

| Outcome | Meaning |
|---|---|
| processed | New or changed content (or a person or initiative it resolved by name may now resolve differently). Written in one transaction with its state; the items it no longer carries are deleted when no other document needs them. |
| skipped | Same content hash, same `HORIZON_RULE_VERSION`, and every name it resolved still resolves the same way. Nothing is written. |
| failed | `download` (no JSON for a listed Lattes id, or a CNPq page that could not be fetched), `unparsable` (the file does not load), `unidentified` (a `Nome-nao-identificado` CV or no Lattes id in the file name), `total_loss` (a readable document that had items now has none), `partial` (a section or row failed). The document is rolled back whole; its stored data and processing state stay as they were, and it is tried again on the next run. |

Each phase logs one line, for example
`documents lattes_projects: processed=3 skipped=432 failed=27 (unidentified=27) inactive=0 reactivated=0 deleted_items=5`.

A document absent from its source's complete listing becomes **inactive**:
its data is kept and still exported, and `source_document_states_canonical.json`
(in `exports_canonical.zip`) lists it as `inactive`. The listings are
`data/lattes_run/lattes.list` for Lattes, the SigPesq reports, and, for CNPq,
the groups active in the SigPesq groups report of the same weekly. A missing,
empty or filtered listing (a campus filter, a standalone CNPq run) changes no
status. A document listed again becomes active.

**When to bump `HORIZON_RULE_VERSION`** (`src/core/logic/horizon_identity.py`):
on any change to a parser, mapping strategy or loader that alters what an
unchanged document produces, besides the key, hash and id rules of spec 020.
Unchanged documents are skipped, so without the bump such a change would
reach only the documents that change for other reasons. A database recorded
with another version is rebuilt once by the weekly, keeping the id history.

## Persistent database in GitHub Actions (spec 022)

The weekly workflow (`.github/workflows/weekly-etl.yml`) keeps the database
between runs through its own artifact. Before `make weekly-flows`, the step
"Restore previous weekly run" (`make restore-weekly`,
`src/scripts/restore_weekly_artifact.py`) looks for the newest successful
weekly run of the **same branch** whose `weekly-etl-artifacts` artifact has
not expired. It puts back three items from it:

- `db/horizon.db`, only if `PRAGMA quick_check` is `ok`;
- `data/raw`;
- `cache/`, the Lattes HTML cache.

`make db-ensure` then migrates the restored database, or creates one when none
was placed, and the run skips the unchanged documents as a local kept run does
(spec 021).

- **Never a failed run.** These cases all end as a rebuild with the reason in
  the log and in the job summary, and the step has `continue-on-error`:
  - no successful run (the first run of a branch);
  - every artifact expired;
  - a download error;
  - a damaged database.
- **Retention**: 90 days, so about twelve failed weeklies in a row still leave
  a database to restore.
- **Force a rebuild**: dispatch the workflow with `fresh_database: true`.
  Scheduled runs always restore.
- **Where the database came from**: the job summary ("Restored from run …" or
  "Rebuilt from scratch: …") and `data/reports/restore_outcome.json`, which
  the artifact also carries.
- **What is not restored**: `data/exports`, `data/reports` and
  `data/lattes_json` are produced again by every run. The SigPesq reports in
  `data/raw/sigpesq/` are restored but still cleared before their download.
- **Compression**: the step that zips files over 10 MB before the upload
  skips `data/raw`. For older artifacts, the restore unpacks a zip whose only
  member has its own name.
- CI databases are only written with the CI `HORIZON_PII_HMAC_KEY`. To test
  the restore locally, run it on a downloaded artifact into a scratch folder,
  never into the repository's `db/horizon.db`:
  `python -m src.scripts.restore_weekly_artifact --from-dir <artifact> --target <scratch>`.

## Rotating raw downloads (spec 023)

Lattes curricula and CNPq group pages are kept between runs, in `cache/` and
`data/raw/cnpq/`; spec 022 restores both folders in CI. Each run downloads:

- the items it has no copy of;
- the share of stored items downloaded longest ago (one quarter by default).
  With the default, every curriculum and page is downloaded again about every
  four runs.

Every other item is processed from its stored copy, which is skipped when
unchanged (spec 021).

- **Download dates**:
  - Lattes: `data/raw/lattes/download_manifest.json` (`lattes_id -> date`);
  - CNPq: inside each `data/raw/cnpq/<group id>.json` (`downloaded_at`, with
    the page under `page`).
- **A copy is replaced only by a successful download.** A failed refresh
  keeps the cached curriculum. A CNPq page that fails to download is
  processed from its stored copy, and with the portal down the run still
  completes with every stored group.
- **Provenance**: every document records the date of the download its data
  comes from (`downloaded_at`). The states export
  `source_document_states_canonical.json` publishes it. SigPesq rows date
  from their report, which is downloaded whole every run.
- **Log line**, one per source:
  `downloads cnpq: new=… refreshed=… reused=… failed=… reused_after_failure=…`.
  The same counts are in `data/reports/source_document_states_report.json`.
- **Tuning**:
  - `HORIZON_REFRESH_SHARE` (`make weekly-flows REFRESH_SHARE=0.5`) sets the
    share, between 0 and 1;
  - `HORIZON_FULL_REFRESH=1` (`FULL_REFRESH=1`) downloads everything again;
  - in CI, the `refresh_share` and `full_refresh` dispatch inputs do the same.
  A campus-filtered CNPq run never does a full refresh.
- **First run after this spec**: every CNPq page is downloaded once (none is
  stored yet). The cached curricula have no date, so they count as the oldest
  and are dated a quarter at a time, in four runs.

## SQLite connection settings (spec 018)

`libbase` commits after every record it adds, so a Lattes phase issues
~180 000 commits for 435 curricula. In SQLite's default rollback-journal mode
each commit waits for the disk (~3.6 ms on NVMe). That was 63% of
`lattes_projects` and 34% of `lattes_advisorships`.

Every process started through `app.py` therefore sets, on each new SQLite
connection, `journal_mode=WAL` and `synchronous=NORMAL`
(`src/adapters/database/sqlite_settings.py`, installed next to the LGPD session
hook). A commit then only appends to `db/horizon.db-wal`; the disk is forced at
checkpoints. The listener sits on the SQLAlchemy `Engine` class, so it reaches
the engines that `eo_lib` and `research_domain` create. It does nothing for
PostgreSQL or in-memory databases.

A power loss can roll back the last transactions; it cannot corrupt the file.
Each source document is committed in one transaction (spec 021), so a lost
transaction is a whole document without a processing state: the next run
processes it again.

| What you may see | Why |
|---|---|
| `db/horizon.db-wal` and `db/horizon.db-shm` during a run | Normal in WAL mode. The `-wal` file holds committed transactions not yet copied into `horizon.db`. |
| `SQLite finalize: {'finalized': True, 'checkpoint': (0, …), 'journal_mode': 'delete'}` at the end of `make weekly-flows` | After the last phase, `run_weekly` copies the log into `horizon.db` and switches the file back to the rollback journal. `db/horizon.db` is then complete on its own, so the CI artifact needs no companion file. |
| `⚠️ SQLite finalize falhou: …` in the Telegram summary | The final step failed, usually because a connection was still open. The data is still in `horizon.db-wal`; the exit code is not affected. |
| `-wal` / `-shm` left after a standalone command (`make sync-cnpq`, `make ingest-lattes-projects`, …) | Only `make weekly-flows` runs the final step. Harmless: the next connection uses them, and `make db-clean` removes them. |

`make db-clean` (and so `make db-reset` and `make full-refresh`) removes
`horizon.db`, `horizon.db-wal` and `horizon.db-shm` together. A stale `-wal`
next to a new database could corrupt it.

## Fluxos legados

Alguns alvos ainda existem para casos especificos:

- `pipeline-serra`
- `sync-cnpq`
- `export`

Esses atalhos sao uteis para execucao parcial, mas nao substituem o `full-refresh` quando a intencao e reconstruir o estado completo.
