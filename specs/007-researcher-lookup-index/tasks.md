---

description: "Task list for feature 007-researcher-lookup-index"
---

# Tasks: Índice leve de correspondência de pesquisadores na ingestão do Lattes

**Input**: Design documents from `/specs/007-researcher-lookup-index/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/researcher_resolution.md

**Tests**: incluídos. A feature é uma otimização cujo critério de aceite é
**equivalência de comportamento** (FR-005, SC-002, SC-003, SC-004) — sem teste
comparando o antes e o depois não há como afirmar que a otimização é segura.

**Organization**: agrupadas por história de usuário. US1 e US2 são ambas P1 e
compartilham a mesma mudança de código: US2 é a rede de segurança de US1, então a
entrega mínima é US1+US2, não US1 sozinha.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: pode rodar em paralelo (arquivos diferentes, sem dependência pendente)
- **[Story]**: US1, US2, US3
- Caminhos de arquivo são exatos

---

## Phase 1: Setup

**Purpose**: preparar a base de comparação. Sem ela não é possível provar
equivalência depois.

- [X] T001 Criar cópia de referência do banco em `/tmp/horizon-bench/antes.db` a partir de `db/horizon.db`, e registrar as contagens de linha das 14 tabelas listadas em `specs/007-researcher-lookup-index/quickstart.md` §4 em `/tmp/horizon-bench/contagens_antes.json`
- [X] T002 Registrar, em `/tmp/horizon-bench/escolhas_antes.json`, o pesquisador escolhido para cada um dos 112 currículos de `data/lattes_json/` pela implementação **atual**, executando `resolve_researcher_from_lattes` sobre `ResearcherController().get_all()` contra `/tmp/horizon-bench/antes.db`, sem gravar nada

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: o carregador do índice e a estrutura de registro. Bloqueia todas as
histórias — nada mais pode ser feito antes.

- [X] T003 Adicionar em `src/core/logic/researcher_resolution.py` a estrutura de registro do índice (dataclass mutável) com os campos `id`, `name`, `identification_id`, `cnpq_url`, `resume` e `citation_names`, usando exatamente esses nomes de atributo, conforme `specs/007-researcher-lookup-index/data-model.md`
- [X] T004 Implementar `load_researcher_index(session)` em `src/core/logic/researcher_resolution.py`, emitindo uma única consulta `SELECT r.id, p.name, p.identification_id, r.cnpq_url, r.resume, r.citation_names FROM researchers r JOIN persons p ON p.id = r.id` e devolvendo a lista de registros
- [X] T005 Fazer `load_researcher_index` degradar com segurança quando a sessão for `None` ou a consulta falhar (banco recém-criado, tabelas ausentes), devolvendo lista vazia e registrando aviso, em `src/core/logic/researcher_resolution.py`
- [X] T006 [P] Criar `tests/test_researcher_lookup_index.py` com teste de carregamento contra SQLite em memória: N pesquisadores geram N registros, com os seis campos preenchidos a partir das duas tabelas

**Checkpoint**: o índice carrega e é testável isoladamente; nenhum flow mudou ainda.

---

## Phase 3: User Story 1 — A ingestão deixa de repetir a leitura do cadastro (P1)

**Goal**: cada fase consulta o cadastro uma vez, e a correspondência produz o
mesmo resultado de hoje.

**Independent Test**: executar cada fase sobre os 112 currículos e comparar
duração e escolhas com a base registrada em T001/T002.

- [X] T007 [US1] Verificar que `_score_candidate` e `resolve_researcher_by_name` em `src/core/logic/researcher_resolution.py` leem candidatos apenas via `getattr`, e ajustar qualquer acesso direto a atributo que impeça um registro do índice de atravessar o algoritmo sem alteração
- [X] T008 [US1] Em `src/flows/lattes/advisorships.py`, construir o índice uma vez em `ingest_lattes_advisorships_flow` e passá-lo como parâmetro para `ingest_advisorships_file_task`, removendo `ResearcherController()` e `get_all()` de dentro da tarefa; manter a obtenção da sessão para o desempate por dados vinculados
  - **Desvio**: `ResearcherController()` permaneceu dentro da tarefa, apenas como porta de acesso à sessão (instanciação medida em ~0,0 ms). A alternativa era passar a sessão como parâmetro de tarefa Prefect, o que a exporia à serialização de parâmetros de task run. Só o `get_all()` foi removido, que era o custo.
- [X] T009 [US1] Em `src/flows/lattes/advisorships.py`, usar o nome vindo do registro do índice para `LattesAdvisorshipMappingStrategy`, sem hidratar a entidade — a tarefa só precisa do nome, conforme `contracts/researcher_resolution.md`
- [X] T010 [US1] Em `src/flows/lattes/projects.py`, construir o índice uma vez em `ingest_lattes_projects_flow` e repassá-lo por `ingest_researcher_data` até `_ingest_researcher_file`, seguindo o padrão já usado para `entity_manager` e `parser`
- [X] T011 [US1] Em `src/flows/lattes/projects.py`, remover `ResearcherController()` e `get_all()` de dentro de `_ingest_researcher_file` e hidratar a entidade completa do vencedor por `id` antes das atualizações de dados pessoais e da persistência
- [X] T012 [US1] Em `src/flows/lattes/projects.py`, propagar o índice para `ingest_articles_task` e `ingest_education_task`, que hoje recebem `all_researchers`, mantendo o mesmo parâmetro e a mesma semântica
- [X] T013 [P] [US1] Em `tests/test_researcher_lookup_index.py`, adicionar o teste de **equivalência**: para o mesmo conjunto de dados, `resolve_researcher_from_lattes` sobre registros do índice escolhe o mesmo pesquisador que sobre entidades ORM, incluindo casos de desempate por dados vinculados, por presença de currículo textual e por nomes de citação
- [X] T014 [US1] Atualizar `tests/test_ingest_lattes_projects_flow.py` e `tests/integration/flows/test_ingest_lattes_advisorships.py` para a nova assinatura das funções, preservando o que cada teste já verifica

**Checkpoint**: as duas fases rodam com uma leitura por fase e escolhem os mesmos pesquisadores.

---

## Phase 4: User Story 2 — Pesquisador criado durante a execução continua sendo encontrado (P1)

**Goal**: nenhuma duplicata é criada por causa do índice.

**Independent Test**: processar em sequência um currículo que cria um orientador
inexistente e outro pertencente a essa mesma pessoa; verificar que só um registro
foi criado.

- [X] T015 [US2] Em `src/core/logic/researcher_resolution.py`, garantir que `resolve_or_create_researcher` acrescente ao índice um **registro do índice** correspondente ao pesquisador recém-criado, e não a entidade ORM, mantendo o retorno utilizável por quem só precisa de `id`
- [X] T016 [US2] Preservar a compatibilidade retroativa de `resolve_or_create_researcher` para `src/core/logic/strategies/cnpq_sync.py:268` e `src/core/logic/strategies/sigpesq_excel.py:103`, que continuam passando listas de entidades ORM e devem continuar recebendo entidades ORM, conforme `contracts/researcher_resolution.md`
- [X] T017 [P] [US2] Em `tests/test_researcher_lookup_index.py`, adicionar teste de não-duplicação: criar pesquisador durante o laço, verificar que ele é encontrado na chamada seguinte e que nenhum segundo registro é criado
- [X] T018 [P] [US2] Em `tests/test_researcher_lookup_index.py`, adicionar teste de compatibilidade: passar entidades ORM (caminho de `cnpq_sync` e `sigpesq_excel`) continua devolvendo entidade ORM e acrescentando à lista recebida

**Checkpoint**: o índice acompanha criações e os dois consumidores fora do escopo seguem intactos.

---

## Phase 5: User Story 3 — O critério de correspondência passa a ser verdadeiro (P2)

**Goal**: nenhum campo avaliado é inexistente no cadastro.

**Independent Test**: inspecionar `_score_candidate` e confirmar que todo campo
consultado existe; reexecutar as fases e verificar que as escolhas não mudaram.

- [X] T019 [US3] Remover de `_score_candidate`, em `src/core/logic/researcher_resolution.py`, o ramo que pontua `brand_id`, que não existe como coluna nem como atributo mapeado de `Researcher`, e registrar no docstring da função em que campos a correspondência realmente se apoia
- [X] T020 [P] [US3] Em `tests/test_researcher_lookup_index.py`, adicionar teste que fixa os critérios vigentes de pontuação, de modo que a remoção do ramo morto não altere nenhuma escolha

**Checkpoint**: o algoritmo descreve o que faz de fato.

---

## Phase 6: Polish & Validação

**Purpose**: provar os critérios de sucesso com número, não com impressão.

- [X] T021a Atualizar `tests/test_ingest_academic_education.py`, **não previsto no plano**: o teste resolvia o pesquisador por `brand_id`, a regra removida em T019. Passava apenas porque um mock consegue expor um campo que o banco não tem. Reescrito para casar por nome e carregar a entidade por id, como acontece de fato
- [X] T021 Executar `tests/test_researcher_lookup_index.py`, `tests/test_ingest_lattes_projects_flow.py`, `tests/test_person_matcher.py` e `tests/test_researcher_creation.py`, e corrigir o que reprovar
- [X] T022 Medir SC-001: executar as duas fases contra cópia do banco e comparar com 1424,6 s e 1165,2 s; alvo abaixo de 900 s somados. Registrar os números medidos
  - **Resultado**: os dois lados foram medidos na mesma máquina, a partir de cópias idênticas do banco, trocando os três arquivos de produção por `git show HEAD:`. `lattes_advisorships`: 1433,7 s → **563,1 s** (2,5x). `lattes_projects`: 1171,8 s → **271,6 s** (4,3x). Soma: 2605,5 s → **834,7 s** (13,9 min). **SC-001 atingido.** A releitura do código antigo (1433,7 e 1171,8 s) confirma a medição original (1424,6 e 1165,2 s) dentro de 1%.
- [X] T023 Verificar SC-002: comparar as escolhas contra `/tmp/horizon-bench/escolhas_antes.json`; exigência é 112/112 idênticas
- [X] T024 Verificar SC-003 e SC-004: comparar as contagens de linha contra `/tmp/horizon-bench/contagens_antes.json` conforme `quickstart.md` §4; qualquer diferença reprova
  - **Resultado**: **0 tabelas divergentes em 14**, nas duas fases. A comparação foi feita contra execuções reais do código antigo — e não contra as contagens do banco íntegro, que provariam menos: as fases gravam, então só duas execuções partindo do mesmo ponto comparam o que interessa. `researchers` fecha em 1060 dos dois lados: **nenhum pesquisador duplicado** (SC-004). **SC-003 e SC-004 atingidos.**
- [X] T025 [P] Rodar `black`, `isort` e `flake8` nos três arquivos de produção alterados e nos arquivos de teste
- [X] T026 [P] Registrar em `docs/backlog.md` que o TD-007 foi resolvido por eliminação de leitura repetida — e **não** por paralelização, como o item previa — com os números medidos
- [X] T027 [P] Registrar em `docs/backlog.md` um item novo para os dois pontos fora de escopo identificados em `research.md` §R7 (`sigpesq_excel.py:100` e `cnpq_sync.py:250`), que têm o mesmo defeito e podem adotar o mesmo carregador

---

## Dependencies

```text
Setup (T001-T002)  ──►  Foundational (T003-T006)  ──►  US1 (T007-T014)
                                                          │
                                                          ├──►  US2 (T015-T018)
                                                          │
                                                          └──►  US3 (T019-T020)
                                                                    │
                                            Polish (T021-T027)  ◄────┘
```

- **T001-T002 antes de tudo**: a base de comparação precisa ser capturada com o
  código **atual**. Depois da primeira alteração ela não pode mais ser gerada.
- **US2 depende de US1**: o acréscimo ao índice só faz sentido depois que o índice
  existe e é usado pelos flows.
- **US3 é independente de US2** e pode ser feita em paralelo, mas depois de US1
  para que a validação de "escolhas não mudaram" use um só ponto de comparação.

## Parallel Opportunities

- T006, T013, T017, T018 e T020 tocam o mesmo arquivo de teste novo — **não** são
  paralelizáveis entre si apesar do marcador `[P]` em relação às tarefas de
  produção; são paralelas ao trabalho em `src/`.
- T025, T026 e T027 são independentes entre si.
- T008-T009 (advisorships) e T010-T012 (projects) tocam arquivos diferentes e
  poderiam ser feitas em paralelo, mas ambas dependem de T007.

## Implementation Strategy

**Entrega mínima: US1 + US2 juntas.** US1 sozinha entrega o ganho de tempo, mas é
US2 que garante que ele não venha acompanhado de pesquisadores duplicados. Entregar
US1 isolada seria assumir um risco de corrupção de dado em troca de velocidade, o
que contraria o critério SC-004.

US3 pode ser entregue depois, em commit separado, por não alterar resultado
observável.

**A validação (T022-T024) não é opcional.** O objetivo da feature é desempenho
sem mudança de comportamento; sem os três números medidos, não há como afirmar
que o segundo requisito foi cumprido.
