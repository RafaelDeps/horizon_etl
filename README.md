# Horizon ETL

Documento tecnico do projeto **Horizon ETL**, responsavel por baixar,
normalizar, persistir e exportar dados academicos e de pesquisa usados pelo
ecossistema Horizon.

## Objetivo

O Horizon ETL consolida dados de fontes institucionais e publicas em um banco
canonico local e em artefatos JSON para consumo por dashboards, auditorias e
marts analiticos.

Fontes suportadas:

- **SigPesq**: grupos de pesquisa, projetos de pesquisa e planos de trabalho
  de bolsas/orientacoes.
- **Lattes**: curriculos, projetos, producoes, formacoes e orientacoes.
- **CNPq**: sincronizacao complementar de grupos e membros.

## Arquitetura

O projeto segue uma organizacao em camadas:

```text
src/
|-- adapters/
|   |-- database/      # clientes e integracoes de persistencia
|   |-- sinks/         # saidas, como JSON
|   `-- sources/       # adaptadores de fontes externas
|-- core/
|   |-- logic/         # loaders, exporters, matchers e regras de negocio
|   `-- ports/         # contratos para fontes e saidas
|-- flows/
|   |-- cnpq/          # flows da fonte CNPq
|   |-- exports/       # exportacoes canonicas, marts e grafos
|   |-- lattes/        # flows da fonte Lattes
|   |-- pipelines/     # pipelines compostos
|   |-- sigpesq/       # flows da fonte SigPesq
|   `-- all.py         # orquestracao geral de ingestao
`-- scripts/           # auditoria, manutencao e diagnostico
```

Componentes principais:

- **Prefect** orquestra os flows e registra execucoes locais.
- **SQLite** em `db/horizon.db` e o banco local de desenvolvimento.
- **research-domain** fornece entidades, controladores e repositorios de
  dominio.
- **agent_sigpesq** automatiza login e download de relatorios SigPesq.
- **Loaders e mapping strategies** transformam arquivos brutos em entidades
  canonicas.

## Modelo de dados

Entidades de maior impacto na carga atual:

- `persons`: pessoas consolidadas a partir das fontes.
- `research_groups`: grupos de pesquisa.
- `initiatives`: projetos e planos de trabalho.
- `initiative_types`: classifica `Research Project` e `Advisorship`.
- `advisorships`: dados especificos do plano de trabalho/bolsa.
- `fellowships`: programa de bolsa composto por nome e patrocinador.
- `organizations`: instituicoes, agencias e patrocinadores.

Regra importante:

- O cancelamento pertence ao plano de trabalho em `advisorships.cancelled` e
  `advisorships.cancellation_date`.
- `fellowships` representa o tipo/programa da bolsa. Uma bolsa como `PIVIC`
  com patrocinador `Voluntario` e diferente de `PIVIC` com patrocinador
  `CNPq`, porque o sponsor compoe a identidade do fellowship.

## Fluxo SigPesq

O flow completo de SigPesq fica em `src/flows/sigpesq/all.py` e deve ser
executado por:

```bash
make ingest-sigpesq
```

ou diretamente:

```bash
PREFECT_API_URL=http://127.0.0.1:4200/api \
PREFECT_CLIENT_SERVER_VERSION_CHECK_ENABLED=false \
HORIZON_QUIET_PREFECT=1 \
PREFECT_LOGGING_TO_API_ENABLED=false \
PYTHONPATH=. \
.venv/bin/python app.py sigpesq
```

Comportamento tecnico:

1. O `SigPesqAdapter` valida credenciais.
2. A pasta `data/raw/sigpesq` e limpa antes de qualquer novo download.
3. O agente faz um unico login no portal SigPesq.
4. Sao baixados relatorios de grupos, projetos e advisorships.
5. Os arquivos baixados sao persistidos no banco local.

A limpeza previa evita que relatorios antigos sejam misturados com a execucao
atual, principalmente em `data/raw/sigpesq/advisorships/<ano>/`.

Arquivos esperados apos uma execucao completa:

```text
data/raw/sigpesq/research_group/Relatorio_<data>.xlsx
data/raw/sigpesq/research_projects/Relatorio_<data>.xlsx
data/raw/sigpesq/advisorships/2016/Relatorio_<data>.xlsx
...
data/raw/sigpesq/advisorships/2026/Relatorio_<data>.xlsx
```

## Fluxo Lattes

O download de curriculos Lattes usa `scriptLattes`, que atualmente depende de
Selenium e de um `chromedriver` local. Antes da execucao, o flow valida se o
Chrome/Chromium encontrado tem a mesma versao major do `./chromedriver`.

Quando houver mais de uma instalacao de Chrome/Chromium, ou quando o Chromium do
sistema vier via Snap, informe um binario explicito:

```bash
CHROME_BINARY=/caminho/para/chrome make ingest-lattes-download
CHROME_BINARY=/caminho/para/chrome make ingest-lattes-full
```

O diretorio `data/lattes_json` e limpo de arquivos `.json` antes de cada novo
download. Isso evita misturar JSONs antigos com a lista atual de pesquisadores.
O cache bruto do `scriptLattes` em `cache/` nao e apagado pelo flow.

Por padrao, o flow faz um prefetch paralelo controlado dos curriculos ausentes
em `cache/` antes de chamar o `scriptLattes` para gerar os JSONs. O limite
padrao e de 3 downloads simultaneos:

```bash
HORIZON_LATTES_DOWNLOAD_WORKERS=4 CHROME_BINARY=/caminho/para/chrome make ingest-lattes-download
HORIZON_LATTES_PREFETCH=0 CHROME_BINARY=/caminho/para/chrome make ingest-lattes-download
```

## Execucao com Docker

Executa o sistema completo (Prefect DB + Prefect Server + ETL app) com Docker Compose.

### Pre-requisitos

- Docker Engine com Compose v2 instalado
- Arquivo `.env` com as credenciais (copie `.env.example` → `.env` e preencha)

### Iniciar servicos

```bash
cp .env.example .env
# Edite .env: defina SIGPESQ_USERNAME, SIGPESQ_PASSWORD e opcionalmente tokens do Telegram
make docker-up
```

### Rodar pipelines

```bash
make docker-pipeline CAMPUS=Serra        # pipeline completo
make docker-ingest-sigpesq               # apenas SigPesq
make docker-sync-cnpq CAMPUS=Serra       # apenas CNPq
make docker-export-canonical CAMPUS=Serra OUTPUT_DIR=data/exports
make docker-full-refresh                 # recria banco e roda pipeline completo
```

Os arquivos exportados aparecem em `data/exports/` no host. O banco SQLite
fica em `db/horizon.db` e pode ser consultado diretamente com ferramentas locais.

### Parar servicos

```bash
make docker-stop   # para containers; dados persistem nos volumes/bind-mounts
```

### Reconstruir a imagem apos mudancas de dependencias

```bash
make docker-build
```

Consulte `specs/002-docker-compose-app/quickstart.md` para cenarios de teste e
troubleshooting de containers.

## Fluxos e entrypoints

Comandos principais:

```bash
make setup
make db-reset
make prefect-server
make ingest-sigpesq
make ingest-lattes-full
make sync-cnpq CAMPUS=Serra
make export-canonical CAMPUS=Serra OUTPUT_DIR=data/exports
make full-refresh
```

Entrypoint Python:

```bash
python app.py sigpesq
python app.py all_sources Serra
python app.py cnpq_sync Serra
python app.py export_canonical data/exports Serra
python app.py full_pipeline Serra data/exports
```

Execucao recomendada para limpar banco e rodar apenas SigPesq:

```bash
make db-reset
make prefect-server
make ingest-sigpesq
```

Execucao recomendada para reconstruir toda a base:

```bash
make full-refresh
```

## Banco e artefatos

Artefatos locais relevantes:

- `db/horizon.db`: banco SQLite local gerado pela execucao.
- `data/raw/`: arquivos brutos baixados das fontes.
- `data/exports/`: exports canonicos e marts.
- `data/reports/`: relatorios de auditoria e conciliacao.
- `logs/`: logs locais de pipeline.

Arquivos gerados nao devem ser tratados como fonte de verdade do codigo. A
fonte de verdade e formada pelos flows, strategies, loaders e entidades de
dominio.

## Configuracao

A origem das credenciais do SigPesq e uma escolha **explicita e obrigatoria**
via `SIGPESQ_CREDENTIALS_SOURCE` (nao ha valor padrao):

```bash
# infisical: resolve sigpesq-user/sigpesq-password no Infisical
# legacy:    usa SIGPESQ_USERNAME/SIGPESQ_PASSWORD do ambiente (comportamento antigo)
SIGPESQ_CREDENTIALS_SOURCE=legacy
```

Um valor ausente ou invalido aborta a execucao com uma mensagem clara, antes de
qualquer acesso ao portal SigPesq.

Modo **legacy** (retrocompativel):

```bash
SIGPESQ_CREDENTIALS_SOURCE=legacy
SIGPESQ_USERNAME=<usuario>
SIGPESQ_PASSWORD=<senha>
```

> Ambientes que ja existiam precisam adicionar `SIGPESQ_CREDENTIALS_SOURCE=legacy`
> uma unica vez: o mode flag e obrigatorio de proposito.

Modo **infisical** (as credenciais saem do `.env`):

```bash
SIGPESQ_CREDENTIALS_SOURCE=infisical
INFISICAL_HOST=https://app.infisical.com      # default
INFISICAL_CLIENT_ID=<machine-identity-id>     # obrigatorio
INFISICAL_CLIENT_SECRET=<machine-identity-secret>  # obrigatorio
INFISICAL_PROJECT_ID=<project-id>             # obrigatorio
INFISICAL_ENV=dev                             # default
INFISICAL_SECRET_PATH=/                       # default
```

Nesse modo o adapter resolve os secrets `sigpesq-user` e `sigpesq-password` e
mantem o download inalterado. Valores de credenciais nunca sao escritos em logs
ou artefatos.

Outras variaveis comuns:

```bash
PREFECT_API_URL=http://127.0.0.1:4200/api
PREFECT_CLIENT_SERVER_VERSION_CHECK_ENABLED=false
HORIZON_TELEGRAM_BOT_TOKEN=<token-do-bot>
HORIZON_TELEGRAM_CHAT_ID=<chat-id-do-grupo-horizon-messages>
```

O adapter tambem aceita `SIGPESQ_USER` como alias para `SIGPESQ_USERNAME`
(no modo legacy).

## Notificacoes Telegram

Todos os flows Prefect registram hooks de conclusao para enviar um relatorio ao
Telegram quando terminam em estado `Completed`, `Failed`, `Crashed` ou
`Cancelled`.

O relatorio inclui:

- nome do flow
- nome/id da execucao
- estado final
- horario de conclusao em UTC
- parametros do flow
- URL local do run no Prefect quando `PREFECT_API_URL` ou `PREFECT_UI_URL`
  estiver configurado
- mensagem final do estado, quando houver

Configuracao para o grupo **Horizon Messages**:

```bash
HORIZON_TELEGRAM_BOT_TOKEN=<token-do-bot>
HORIZON_TELEGRAM_CHAT_ID=<chat-id-numerico-do-grupo>
```

Tambem sao aceitos os aliases genericos:

```bash
TELEGRAM_BOT_TOKEN=<token-do-bot>
TELEGRAM_CHAT_ID=<chat-id-numerico-do-grupo>
```

Observacao: a Bot API do Telegram envia mensagens por `chat_id`, nao pelo nome
visual do grupo. Adicione o bot ao grupo **Horizon Messages** e configure o ID
numerico em `HORIZON_TELEGRAM_CHAT_ID`.

## Validacao

Testes direcionados:

```bash
.venv/bin/python -m pytest tests/test_sigpesq_adapter.py tests/test_sigpesq_full_flow.py -q
```

Suite completa:

```bash
make test
```

Auditorias uteis:

```bash
make etl-report
make etl-report-md
make tracking-audit-report
make audit-duplicates
```

Consultas rapidas no SQLite:

```bash
.venv/bin/python - <<'PY'
import sqlite3

conn = sqlite3.connect("db/horizon.db")
cur = conn.cursor()
for table in ["persons", "research_groups", "initiatives", "advisorships", "fellowships"]:
    count = cur.execute(f"select count(*) from {table}").fetchone()[0]
    print(f"{table}: {count}")
conn.close()
PY
```

## Troubleshooting

### Login SigPesq falha (HTTP 429 — rate limit)

O portal SigPesq aplica rate limit em logins rapidos consecutivos e retorna HTTP 429.

O adapter detecta automaticamente o 429 e reintenta com backoff exponencial:

| Tentativa | Espera antes |
|-----------|-------------|
| 1         | —           |
| 2         | 60s         |
| 3         | 120s        |

Configuravel via `.env`:

```env
SIGPESQ_429_WAIT_SECONDS=60   # base de espera (default: 60)
SIGPESQ_MAX_RETRIES=3         # maximo de tentativas (default: 3)
```

Se o 429 persistir apos todas as tentativas, verifique se ha outra instancia do
pipeline rodando em paralelo ou se o portal esta temporariamente bloqueando o IP.

### Relatorios antigos aparecem na carga

O comportamento esperado e limpar `data/raw/sigpesq` antes do download. Se
arquivos antigos aparecerem, confirme que a execucao passou por
`SigPesqAdapter.extract()` e nao chamou diretamente uma rotina parcial de
persistencia.

### Prefect nao responde

Use:

```bash
make prefect-status
make prefect-server
```

### Banco local inconsistente

Recrie o banco e rode a fonte desejada:

```bash
make db-reset
make ingest-sigpesq
```

## Documentacao complementar

- `docs/flows-and-entrypoints.md`: organizacao dos flows e comandos.
- `docs/architecture.md`: visao arquitetural.
- `docs/outputs-and-artifacts.md`: artefatos produzidos.
- `docs/reports/`: relatorios e snapshots.
