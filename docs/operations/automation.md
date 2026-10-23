# Automacao Semanal

## Workflow

O repositorio possui uma workflow dedicada:

- `.github/workflows/weekly-etl.yml`

## Objetivo

Executar semanalmente um `make weekly-flows`, garantindo:

- banco limpo
- schema recriado
- ingestao das fontes SigPesq, Lattes e CNPq
- download SigPesq com um unico login no portal
- extracao dos documentos de projeto SigPesq (PDF + Mistral) via `extract_project_files`
- exportacao dos dados canonicos, marts e grafo de relacionamentos
- escrita do relatorio `data/reports/weekly_pipeline_run.json`
- publicacao dos artefatos gerados (artifact de 30 dias)
- commit do entregavel curado `exports_canonical.zip` quando ele muda
- notificacao de inicio e conclusao dos flows no grupo Telegram configurado
- notificacao final com resumo do relatorio semanal

## Secrets usados

A workflow depende destes secrets do GitHub:

- `DATABASE_URL`
- `STORAGE_TYPE`
- `SIGPESQ_USERNAME`
- `SIGPESQ_PASSWORD`
- `HORIZON_TELEGRAM_BOT_TOKEN`
- `HORIZON_TELEGRAM_CHAT_ID`

## Origem das credenciais SigPesq

A escolha da origem das credenciais do SigPesq e obrigatoria via
`SIGPESQ_CREDENTIALS_SOURCE` (`infisical` ou `legacy`); ausente ou invalido
aborta a execucao antes de qualquer acesso ao portal.

Esta workflow continua usando os secrets do GitHub, portanto define
explicitamente:

```yaml
env:
  SIGPESQ_CREDENTIALS_SOURCE: legacy
```

Os secrets `SIGPESQ_USERNAME` / `SIGPESQ_PASSWORD` da workflow permanecem a
fonte (modo `legacy`). O modo `infisical` (secrets `sigpesq-user` /
`sigpesq-password` no Infisical) e uma alternativa para execucoes locais/outros
ambientes, nao para esta workflow.

## Parametros manuais

No `workflow_dispatch`, a execucao manual aceita:

- `weekly_campus`: filtro opcional de campus. Em branco processa todos os campi.
- `output_dir`: pasta de saida dos exports. O padrao e `data/exports`.

## Notificacoes Telegram

Cada flow com hook operacional envia uma mensagem ao entrar em execucao e outra
ao finalizar, falhar, cancelar ou crashar. O flow semanal agregado tambem envia
uma mensagem final com:

- quantidade de etapas com sucesso e falha
- deltas de entidades salvas
- totais finais de tabelas
- resumo de duplicidades
- warnings estruturados por fonte
- resumo do tracking, quando disponivel

## Artefatos publicados

Artifact do GitHub Actions (retencao de 30 dias):

- `data/` (exceto `data/exports/exports_canonical.zip`)
- `db/horizon.db`

Commit no repositorio (entregavel curado, quando muda):

- `data/exports/exports_canonical.zip`

## Politica de versionamento dos artefatos

Os artefatos gerados por `make weekly-flows` sao, em geral, saida operacional da
execucao: eles devem ser publicados pelo GitHub Actions como artifacts, nao
commitados automaticamente no repositorio.

A excecao e o entregavel curado `data/exports/exports_canonical.zip`. A workflow
semanal o commita (autor `github-actions[bot]`) e faz push **quando o conteudo
mudou**, de modo que git e a fonte sempre-atual do dataset. Ele nao e publicado
como artifact. Detalhes da mudanca: `specs/003-workflow-ci-zip-exports/`.

O commit so roda quando as fases semanais terminam com sucesso (`if: success()`),
entao um arquivo parcial de run falho nunca e publicado. Para permitir o push, a
workflow declara `permissions: contents: write`; se o branch for protegido contra
o bot, o push e rejeitado e o run sinaliza o erro.

Use commits em `data/exports/` ou `data/reports/` somente quando houver uma
decisao explicita de versionar um snapshot curado para documentacao, auditoria
ou reproducao de um caso. O banco `db/horizon.db`, arquivos `.env`, logs e
configuracoes locais como `lattes.config` continuam sendo artefatos de runtime.

## Observacoes operacionais

- O job cria sua propria `.venv` apenas para a execucao
- `.venv` e arquivos `.env` nao sao publicados como artifact
- A automacao instala Chromium do Playwright porque o `sigpesq-agent` depende dele
- O download Lattes usa `scriptLattes` via Selenium e exige Chrome/Chromium
  compativel com `./chromedriver`; use `CHROME_BINARY` se o ambiente tiver mais
  de um navegador instalado
- O prefetch paralelo do cache Lattes usa 3 workers por padrao; ajuste com
  `HORIZON_LATTES_DOWNLOAD_WORKERS` ou desative com `HORIZON_LATTES_PREFETCH=0`
- O agendamento roda aos sabados, 06:00 UTC, pelo cron `0 6 * * 6`
