# Research: Índice leve de correspondência de pesquisadores

**Feature**: 007-researcher-lookup-index | **Data**: 2026-08-27

Todas as medições abaixo foram feitas contra **cópia isolada** do banco de
produção (`db/horizon.db`, 1060 pesquisadores, 4122 iniciativas, 4445 pessoas),
com os 112 currículos reais em `data/lattes_json/`. O banco de produção não foi
alterado em nenhum momento.

## R1 — Onde está o tempo das fases do Lattes

**Decisão**: atacar a leitura repetida do cadastro de pesquisadores; não
paralelizar.

**Medição**:

| Fase | Total | `get_all()` | Escrita | Parse |
|---|---|---|---|---|
| `lattes_advisorships` | 1424,6 s | 867,1 s (60,9%) | 554,8 s (38,9%) | 0,0 s (0,1 ms/arquivo) |
| `lattes_projects` | 1165,2 s | 874,9 s (75,1%) | 290,4 s (24,9%) | — |

**Racional**: o trabalho útil por currículo (interpretar o JSON) custa 0,1 ms. O
que resta depois da leitura repetida é escrita em SQLite, serializada por
natureza. Não há superfície para paralelismo que justifique o risco.

**Alternativas consideradas e descartadas por medição**:

- *Paralelizar o laço com `ThreadPoolExecutor`*, como sugerido no TD-007 do
  backlog: o parse é 0,0% do tempo e a escrita é serializada pelo SQLite. Ganho
  teórico próximo de zero, risco de `database is locked` real.
- *Paralelizar as fases do orquestrador semanal*: o bloco de relatórios de
  docentes inteiro leva **60,8 s** (medido), contra 8700 s de teto configurado.
  Paralelizá-lo economizaria ~45 s.
- *Paralelizar a coleta OpenAlex*: 9 lotes, 351 DOIs, **12,6 s** no total.

## R2 — Por que `get_all()` custa 7,8 s para 1060 linhas

**Decisão**: a causa é produto cartesiano por carregamento ansioso de coleções,
não lentidão do banco.

**Evidência**: instrumentação de cursor registrou **1 única consulta, executada
em 0,01 s**. O perfil aponta `load_collection_from_joined_existing_row` com 3,3
milhões de chamadas; `fetchall` do driver devolve **828.644 linhas** para montar
1060 objetos.

A entidade `Researcher` declara quatro relações `uselist=True` com
`lazy="joined"`: `knowledge_areas`, `articles`, `productions` e `emails`. Juntar
quatro coleções um-para-muitos no mesmo SELECT multiplica as linhas.

**Contraprova**: `InitiativeController().get_all()` traz 4122 iniciativas em
0,18 s; `PersonController().get_all()`, 4445 pessoas em 0,02 s. O problema é
específico desta entidade.

**Fora de escopo**: corrigir a modelagem pertence à biblioteca `research_domain`.
Esta feature contorna deixando de pedir o que não usa.

## R3 — Formato do índice: quatro opções medidas

**Decisão**: estrutura de dados própria, desacoplada da sessão (opção D).

| Opção | Custo | Objetos | Preso à sessão |
|---|---|---|---|
| A) `get_all()` atual | 6921,6 ms | ORM completos | sim |
| B) ORM com `lazyload("*")` | 3,6 ms | ORM | **sim** |
| C) B + `load_only(campos)` | 3,7 ms | ORM | **sim** |
| D) Consulta direta → estrutura própria | **0,9 ms** | tuplas | **não** |

**Racional para D sobre B**, que seria a mudança menor: objetos ORM pertencem à
sessão e **expiram em qualquer `rollback()`**. `ProjectLoader._rollback_session()`
é chamado a cada linha que falha dentro de `process_records`. Medido:

- varredura do índice após um rollback, com objetos de `get_all()`: **12,25 s / 1060 consultas**
- varredura após rollback, com objetos de `lazyload("*")`: **12,40 s / 1061 consultas**

A opção B **não protege** contra isso: o refresh de um objeto expirado reexecuta
o carregamento padrão do mapper e ignora a opção `lazyload` da consulta original.
Ou seja, B é rápida no caminho feliz e volta a ser lenta — silenciosamente — no
primeiro lote de dados com defeito.

Estruturas próprias não pertencem à sessão, não expiram, e por isso o custo é
estável independentemente de rollback.

**Frequência real do gatilho**: 0 rollbacks em 20 currículos medidos hoje. O
caminho existe, é silencioso (`"Skipping row due to error"` em nível warning) e
depende do dado de entrada — por isso a decisão não se apoia na ausência atual.

## R4 — Compatibilidade com o algoritmo de correspondência

**Decisão**: dar à estrutura do índice os **mesmos nomes de atributo** da
entidade ORM.

**Racional**: `_score_candidate` e `resolve_researcher_by_name` leem candidatos
exclusivamente por `getattr(researcher, "campo", padrão)`. Uma estrutura que
exponha `id`, `name`, `identification_id`, `cnpq_url`, `resume` e
`citation_names` atravessa o algoritmo sem que ele mude. O desempate por dados
vinculados (`_linked_data_score`) usa apenas `id` e a sessão, e continua igual —
ele custa 2,4 ms no total das 112 chamadas porque só roda para candidatos que já
casaram.

**Alternativa rejeitada**: dicionários. Obrigariam a reescrever o scorer, que é
a parte cuja equivalência precisa ser preservada (FR-005).

## R5 — `brand_id` é código morto

**Decisão**: remover o critério.

**Evidência**: os atributos-coluna mapeados de `Researcher` são
`id, name, identification_id, birthday, cnpq_url, google_scholar_url, resume,
citation_names`. Não existe `brand_id` — nem como coluna, nem como atributo de
classe (`hasattr(Researcher, "brand_id")` é `False`). O `getattr(..., None)` no
scorer devolve `None` sempre, e o ramo de +500 pontos, o de maior peso, nunca
dispara.

**Consequência a registrar**: a correspondência real se apoia em `cnpq_url` e
nome. O `identification_id` é anonimizado na escrita, então comparar um Lattes ID
cru contra ele também não casa — o próprio código já reconhece isso num
comentário em `projects.py`. Remover `brand_id` não muda resultado nenhum; muda o
que o código afirma sobre si mesmo.

## R6 — Segurança: pesquisador criado durante o laço

**Decisão**: manter o contrato de acréscimo em `resolve_or_create_researcher`.

**Evidência**: a função já faz `all_researchers.append(researcher)` — foi escrita
esperando lista do chamador. Teste executado na cópia: criar pesquisador,
acrescentar à lista, forçar `rollback()`; o objeto permaneceu `persistent` e **a
linha continuou no banco** (efeito colateral do comportamento de SAVEPOINT do
driver SQLite, já registrado como TD-001 no backlog). Não há divergência entre
índice e banco.

`PersonMatcher.match_or_create` cria **Person**, não Researcher — não existe
caminho de criação de pesquisador que escape do índice.

## R7 — O mesmo defeito existe fora do escopo desta feature

**Achado**, registrado para decisão separada — **não** será corrigido aqui:

- `src/core/logic/strategies/sigpesq_excel.py:100` — `researcher_ctrl.get_all()`
  dentro de `SigPesqResearcherStrategy.ensure()`, chamada por
  `research_group_loader.py:105` uma vez por pesquisador de grupo. Há um cache por
  nome em `_researcher_cache`, então o custo é uma leitura por **nome distinto**,
  não por linha — mas cada falha de cache custa 7,8 s.
- `src/core/logic/strategies/cnpq_sync.py:250` — `self.res_ctrl.get_all()` dentro
  de `sync_members()`, chamada uma vez **por grupo** em `flows/cnpq/groups.py:139`.
  O banco tem 347 grupos de pesquisa.

Essas são as fases `sigpesq` (teto 3600 s) e `cnpq_sync` (teto 5400 s). O
carregador do índice fica em `src/core/logic/researcher_resolution.py`,
compartilhado, de modo que adotá-lo nesses dois pontos depois seja mudança de
poucas linhas. Nenhuma medição de duração dessas fases foi feita.
