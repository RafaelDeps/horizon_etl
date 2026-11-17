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
- `HORIZON_SLACK_WEBHOOK_URL` (opcional, spec 040; sem ele o aviso no Slack e
  apenas pulado)

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

## Aviso no Slack (spec 040)

A weekly do GitHub Actions avisa um canal do Slack duas vezes, por qualquer
branch em que rodar (main ou branches de spec), com o nome da branch:

- **ao comecar** (passo "Notify Slack: start", logo depois do checkout): branch,
  se foi `agendada` ou `manual`, e o link da run;
- **ao terminar** (passo "Notify Slack: end", sempre o ultimo, roda mesmo depois
  de falha ou cancelamento): o resultado, a branch, o tempo total e o link da
  run. O resultado e um destes:
  - `passou`: mostra o commit dos zips (hash curto com link) ou "nao mudaram";
  - `passou com avisos`: igual, mais as fases nao criticas que falharam;
  - `falhou`: o primeiro passo que falhou e, se foi "Run weekly flows", as
    fases criticas que falharam;
  - `cancelada`.

As mensagens nao citam ninguem nem mostram totais de dados. Runs locais
(`make weekly-flows`) nao avisam. O Telegram continua igual.

As fases vem de `data/reports/weekly_phase_summary.json`, que a weekly grava
ao final; o passo que falhou vem da API do GitHub da propria run.

### Como configurar

1. Em https://api.slack.com/apps, criar um app (**Create New App** → **From
   scratch** → **Pick features**) com o escopo `incoming-webhook`.
2. Em **Incoming Webhooks**, clicar em **Add New Webhook to Workspace** e
   escolher o canal. O webhook posta so nesse canal; para trocar de canal, criar
   outro webhook e trocar o secret.
3. Salvar a Webhook URL como secret `HORIZON_SLACK_WEBHOOK_URL` em **Settings →
   Secrets and variables → Actions**.

A URL e uma credencial: o script `src/scripts/notify_slack.py` nunca a
imprime, e os dois passos do aviso tem `continue-on-error`. Sem o secret, ou
com o Slack fora do ar, a run so mostra um `::warning::` e termina com o mesmo
resultado que teria sem o aviso.

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
- O download Lattes usa `scriptLattes`, que tambem abre esse Chromium do
  Playwright; o workflow nao instala nenhum outro navegador (spec 039: o
  Chromium via apt/snap foi removido porque nada o usava e uma queda da Snap
  Store parava a weekly)
- O prefetch paralelo do cache Lattes usa 3 workers por padrao; ajuste com
  `HORIZON_LATTES_DOWNLOAD_WORKERS` ou desative com `HORIZON_LATTES_PREFETCH=0`
- O agendamento roda aos sabados, 06:00 UTC, pelo cron `0 6 * * 6`
