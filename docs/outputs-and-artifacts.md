# Dados e Artefatos

## Pastas principais

### `data/raw/`

Armazena os arquivos brutos baixados das fontes, principalmente SigPesq e Lattes.

### `data/exports/`

Contem os JSONs canonicos e marts gerados pelo pipeline. Exemplos:

- `initiatives_canonical.json`
- `advisorships_canonical.json`
- `knowledge_areas_mart.json`
- `initiatives_analytics_mart.json`

O artefato `exports_canonical.zip`, gerado ao final do export canonico, e
curado: contem os JSONs canonicos e copias ANONIMIZADAS dos documentos de
projeto SigPesq (`project_sigpesq_files_json/PJ_*.json`, com e-mails e
telefones substituidos pelos tokens LGPD). Nao inclui a pasta bruta do corpus,
arquivos `.zip` aninhados (ex.: `data_snapshot.zip`), as pastas de relatorios
(`formandos/`, `docentes/`, `mestrado/`) nem `parquet/` (pasta antiga, de antes
da spec 013) nem `exports_parquet.zip`.

#### `exports_parquet.zip` (branch 038)

The Parquet layout of the top-level exports, for the dashboard, which can no
longer keep the JSON copies in git (two exports are over GitHub's 100 MB
per-file limit). About 51 MB on 2026-11-14 (the JSON archive is 58 MB).

- **Built from** the top-level members of the `exports_canonical.zip` of the
  same run, by the weekly phase `parquet_archive`, right after `zip_exports`.
  Every value therefore already went through the safety net of spec 029; the
  archive carries nothing the JSON archive does not. It is skipped when
  `zip_exports` did not build the JSON archive in that run.
- **Members**: a list of rows becomes `<name>.parquet` + `<name>.cols.json`; a
  graph becomes `<name>.nodes.parquet`, `<name>.edges.parquet`, their
  `.cols.json` and `<name>.meta.json`; the wrapped tables
  (`horizon_ids_canonical`, `horizon_id_aliases_canonical`,
  `source_document_states_canonical`) become `<name>.parquet` + `.cols.json` +
  `.meta.json` (the other keys); any other object is copied as `<name>.json`.
  Last member: `export_manifest.json`, the JSON archive's, byte for byte.
  `research_group_relationship_graphs/` and `project_sigpesq_files_json/` stay
  in the JSON archive only.
- **Column rule**: a column whose values are nested or of more than one kind
  (text, number, boolean) is JSON text, every value encoded, and named in
  `<name>.cols.json` (`{"json_columns": [...]}`); decode exactly those columns
  with JSON and every value comes back with its original kind. Whole numbers
  are 64-bit integers, other numbers floats.
- **Limits**: the archive and every member at most 100 MB. Members in name
  order with the fixed date 1980-01-01, so the same JSON archive gives the same
  bytes.
- **Failure**: the previous `exports_parquet.zip` is kept, the JSON archive is
  not touched, and the log warns that the Parquet archive is now from an
  earlier run. The weekly phase is not critical.
- **Report**: `data/reports/parquet_archive_report.json` (status, reason and
  member of a failure, sha256 of the JSON archive it came from, members, size,
  largest member, seconds).
- **Publishing**: the weekly workflow checks it with
  `src.scripts.check_publishable_archive`, like the JSON archive, and commits
  both in one commit; CI and the pre-commit hook check it when it changes.
- **Never read by the ETL**: the id history and the previous SigPesq documents
  come from `exports_canonical.zip` only.
- The old `data/exports/parquet/` folder (loose files, from before spec 013) is
  obsolete: nothing produces or reads it, and it can be removed by hand.

Manual build: `make parquet-archive` (or `python app.py parquet_archive
[output_dir]`). Loose files in the same layout, from a folder of JSON files:
`python -m src.scripts.export_parquet --src DIR --dst DIR` (exit 1 when a file
cannot be converted).

### `data/reports/`

Contem os relatorios operacionais e de auditoria. Exemplos:

- `etl_flow_run.md`
- `etl_load_report.md`
- `tracking_audit_report.md`
- `weekly_pipeline_run.json`
- `weekly_pipeline_run.md`

O report semanal inclui uma secao de warnings por fonte. Ela destaca achados
estruturados como duplicidades restantes, tracking com status inesperado e
problemas conhecidos de extracao, por exemplo nomes sentinela vindos do CNPq.

### `db/horizon.db`

Banco SQLite local usado durante a execucao e a validacao do pipeline.

## Artefatos publicados na automacao semanal

A workflow semanal publica duas coisas, por canais diferentes:

1. **Artifact do GitHub Actions** (retencao de 30 dias): a pasta `data` e o
   banco `db/horizon.db`, exceto `data/exports/exports_canonical.zip`. Isso
   facilita auditoria, download dos resultados e analise posterior da execucao.
2. **Commit no repositorio**: `data/exports/exports_canonical.zip` (o entregavel
   curado) and, since branch 038, `data/exports/exports_parquet.zip`, in the
   same commit. Quando o flow `make weekly-flows` gera um arquivo diferente do
   versionado, a workflow o commita e faz push (autor `github-actions[bot]`),
   atualizando o arquivo rastreado. Por isso ele **nao** esta no artifact:
   git e o canal de entrega do entregavel.

O commit so acontece quando as fases semanais terminam com sucesso e o conteudo
mudou — runs falhos nunca publicam um arquivo parcial, e runs sem alteracao nao
geram commit vazio. O arquivo commitado e byte a byte a saida do flow
(`zip_exports_task`); uma etapa de compressao mal configurada nao pode
re-empacota-lo (`docs/operations/automation.md`).

Os demais arquivos publicados como artifact (`data/`, `db/horizon.db`) sao
saidas de runtime. A politica operacional e consumi-las pelo GitHub Actions e
evitar commits automaticos desses resultados. Snapshots em `data/exports/` ou
`data/reports/` so devem ser versionados quando houver curadoria explicita para
documentacao, auditoria ou reproducao de casos — com a unica excecao do
`exports_canonical.zip`, que e versionado automaticamente por ser o entregavel
curado do pipeline.
