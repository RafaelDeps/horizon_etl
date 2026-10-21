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
(`formandos/`, `docentes/`, `mestrado/`) nem `parquet/` (o espelho Parquet nao
e mais gerado pelo fluxo semanal; conversao manual via
`python -m src.scripts.export_parquet`).

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
   curado). Quando o flow `make weekly-flows` gera um arquivo diferente do
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
