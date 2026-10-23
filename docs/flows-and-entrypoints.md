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

## Fluxos legados

Alguns alvos ainda existem para casos especificos:

- `pipeline-serra`
- `sync-cnpq`
- `export`

Esses atalhos sao uteis para execucao parcial, mas nao substituem o `full-refresh` quando a intencao e reconstruir o estado completo.
