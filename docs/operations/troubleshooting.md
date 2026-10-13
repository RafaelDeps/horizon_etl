# Troubleshooting

## Banco vazio ou schema ausente

Sintoma comum:

- erros de tabela ausente no inicio do pipeline

Acao recomendada:

```bash
make full-refresh
```

## Prefect Server indisponivel

Sintoma comum:

- falha ao conectar em `http://127.0.0.1:4200/api`

Acao recomendada:

```bash
make prefect-server
make prefect-status
```

## SigPesq: origem de credenciais ausente ou invalida

Sintoma comum:

```
Missing or invalid SIGPESQ_CREDENTIALS_SOURCE: expected 'infisical' or 'legacy', got None.
```

Causa:

- a origem das credenciais do SigPesq e uma escolha explicita e obrigatoria (nao
  ha deteccao automatica nem valor padrao)

Acao recomendada:

- definir `SIGPESQ_CREDENTIALS_SOURCE=legacy` (usa `SIGPESQ_USERNAME` /
  `SIGPESQ_PASSWORD`) ou `SIGPESQ_CREDENTIALS_SOURCE=infisical`
- ambientes que ja existiam precisam adicionar `SIGPESQ_CREDENTIALS_SOURCE=legacy`
  uma unica vez

## SigPesq sem credenciais (modo legacy)

Sintoma comum:

- erro informando ausencia de `SIGPESQ_USERNAME` ou `SIGPESQ_PASSWORD`

Acao recomendada:

- configurar as variaveis no `.env` local
- ou configurar os secrets correspondentes no GitHub

## SigPesq: falha ao resolver credenciais no Infisical (modo infisical)

Sintoma comum (mensagens distinguem a causa):

```
Missing required Infisical configuration: INFISICAL_CLIENT_ID, ...
Infisical authentication failed (HTTP 401): ...
Infisical denied access to secret '<nome>' (HTTP 403) ...
Infisical secret '<nome>' was not found (project=... environment=... path=...) ...
Could not reach Infisical at https://... ...
Infisical secret '<nome>' is missing or empty ...
```

Acao recomendada:

- configuracao ausente: definir `INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`
  e `INFISICAL_PROJECT_ID`
- HTTP 401: conferir/rotacionar as credenciais da machine identity
- HTTP 403: conceder leitura ao path configurado em `INFISICAL_SECRET_PATH`
- HTTP 404: conferir `INFISICAL_PROJECT_ID`, `INFISICAL_ENV` e
  `INFISICAL_SECRET_PATH`, e se os secrets `sigpesq-user` / `sigpesq-password`
  existem nesse ambiente/path
- conectividade: verificar `INFISICAL_HOST` e acesso de rede; usar o modo
  `legacy` como alternativa se o Infisical estiver indisponivel

A execucao aborta antes de qualquer acesso ao portal SigPesq: nenhuma mensagem
de erro ou log contem os valores das credenciais.

## SigPesq retorna HTTP 429 (rate limit no login)

Sintoma comum:

```
ERROR | SigPesq portal returned HTTP 429 while logging in at https://sigpesq.ifes.edu.br/Login.aspx.
```

Causa:

- o portal bloqueia logins rapidos consecutivos (rate limit por IP ou conta)

Comportamento automatico:

O adapter reintenta o download com backoff exponencial antes de falhar:

| Tentativa | Espera antes |
|-----------|-------------|
| 1         | —           |
| 2         | 60s         |
| 3         | 120s        |

Configuravel via `.env`:

```env
SIGPESQ_429_WAIT_SECONDS=60   # base de espera entre tentativas (default: 60)
SIGPESQ_MAX_RETRIES=3         # maximo de tentativas (default: 3)
```

Se o problema persistir apos todas as tentativas:

- verificar se ha outra instancia do pipeline rodando em paralelo
- aguardar alguns minutos antes de reiniciar manualmente
- o pipeline completo (`make full-pipeline`) usa um unico login — nunca chamar os flows individuais (`ingest_research_groups_flow`, `ingest_projects_flow`, `ingest_advisorships_flow`) em sequencia separada

## Playwright sem browser instalado

Sintoma comum:

- erro informando que o executavel do Chromium nao existe

Acao recomendada:

```bash
.venv/bin/python -m playwright install --with-deps chromium
```

## Warnings de versao do Prefect

Sintoma comum:

- warning de diferenca entre versao do client e do server

Impacto esperado:

- a execucao pode continuar
- eventos e telemetria podem ficar degradados

Acao recomendada:

- alinhar a versao do container Prefect com a versao instalada no ambiente Python
