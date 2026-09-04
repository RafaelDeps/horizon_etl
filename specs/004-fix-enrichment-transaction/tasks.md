---

description: "Task list for 004-fix-enrichment-transaction"
---

# Tasks: Correção da falha da fase de enriquecimento de projetos

**Input**: Design documents from `/specs/004-fix-enrichment-transaction/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/)

**Tests**: Tarefas de teste **são** incluídas — a especificação as exige
explicitamente (FR-009, FR-010 e a User Story 3).

**Organization**: Tarefas agrupadas por user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Pode rodar em paralelo (arquivos distintos, sem dependências pendentes)
- **[Story]**: A qual user story a tarefa pertence (US1, US2, US3)
- Caminhos de arquivo são exatos

## Path Conventions

Projeto único de pipeline ETL: `src/` e `tests/` na raiz do repositório,
conforme a *Structure Decision* do [plan.md](plan.md).

## Nota sobre o tamanho deste trabalho

Esta é uma correção cirúrgica: **um** arquivo de produção alterado (cerca de seis
linhas) e **um** arquivo de teste criado. As User Stories 1 e 2 são atendidas pela
mesma edição de código — o que as separa é o que cada uma verifica. A US1 verifica
que a fase deixa de abortar; a US2 verifica que ela efetivamente grava. Essa
distinção importa porque, no ambiente atual (sem os documentos de entrada), é
perfeitamente possível satisfazer a US1 e continuar sem entregar valor algum.

---

## Phase 1: Setup

**Purpose**: Estabelecer a linha de base antes de qualquer alteração

- [X] T001 Confirmar que a branch ativa é `004-fix-enrichment-transaction` e que `src/core/logic/project_enrichment.py` está idêntico ao HEAD
- [X] T002 Registrar a linha de base executando `.venv/bin/python -m pytest -q` e anotando o total de testes que passam hoje
- [X] T003 [P] Confirmar a reprodução do defeito seguindo o passo 1 de [quickstart.md](quickstart.md), guardando a saída como evidência do "antes"

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Resolver a pendência que altera o que precisa ser produzido

**⚠️ CRÍTICO**: Nenhuma tarefa de user story pode começar antes de T004

- [X] T004 Obter do responsável a decisão sobre a **FR-004** registrada em *Complexity Tracking* do [plan.md](plan.md) — manter o escopo estreito e tratar a atomicidade como follow-up (recomendado), ou ampliar esta branch para configurar o comportamento transacional do engine; registrar a decisão tomada ao final de [research.md](research.md)
- [X] T005 ~~Caso a decisão de T004 seja ampliar o escopo, **interromper** esta lista e retornar ao `/speckit-plan`, porque o desenho da solução muda~~ — **não se aplicou**: T004 manteve o escopo estreito

**Checkpoint**: Decisão tomada — as user stories podem começar

---

## Phase 3: User Story 1 - A fase de enriquecimento deixa de abortar (Priority: P1) 🎯 MVP

**Goal**: A fase executa até o fim e reporta sucesso, em vez de abortar com
`InvalidRequestError`.

**Independent Test**: Executar a fase isoladamente com o banco acessível e
verificar que conclui com sucesso e que o registro em `ingestion_runs` fica
marcado como bem-sucedido.

### Implementation for User Story 1

- [X] T006 [US1] Substituir a fronteira transacional em `src/core/logic/project_enrichment.py` (bloco iniciado na linha 401): remover `transaction = None if self.dry_run else self._session.begin()` e passar a usar `self._session.commit()` quando `not self.dry_run` no caminho de sucesso e `self._session.rollback()` no `except`, mantendo o `raise`
- [X] T007 [US1] Acrescentar em `src/core/logic/project_enrichment.py`, no ponto da alteração, comentário explicando que a sessão já possui transação aberta por *autobegin* das leituras de índice e que por isso não há `begin()` explícito — o comentário existe para impedir que a reordenação futura reintroduza o defeito
- [X] T008 [US1] Atualizar o *docstring* de `run()` em `src/core/logic/project_enrichment.py` para descrever a fronteira transacional real, substituindo qualquer menção que sugira abertura explícita de transação
- [X] T009 [US1] Verificar o caminho de zero documentos executando `PYTHONPATH=. .venv/bin/python app.py enrich_projects` com o servidor Prefect no ar e confirmando conclusão com sucesso relatando zero documentos (o diretório de entrada não existe neste ambiente — isso é o esperado)
- [X] T010 [US1] Confirmar no banco que a execução de T009 gravou uma linha `success` em `ingestion_runs` para `source_system='sigpesq_project_files'`, usando a consulta do passo 1 de [quickstart.md](quickstart.md)

**Checkpoint**: A fase conclui com sucesso; o erro que motivou o trabalho
desapareceu

---

## Phase 4: User Story 2 - Os projetos passam a ser efetivamente enriquecidos (Priority: P1)

**Goal**: Provar que a fase grava descrição e campos ricos — não apenas que ela
termina sem erro.

**Independent Test**: Com documentos conhecidos que casam com iniciativas, rodar a
fase e verificar descrição preenchida e campos ricos persistidos.

**Nota**: como os documentos `PJ_*.json` não existem neste repositório (premissa
registrada na especificação), a verificação desta story é feita contra dados de
fixture construídos pelo próprio teste, conforme D4 de [research.md](research.md).

### Tests for User Story 2

> Escrever primeiro e confirmar que falham antes da correção estar aplicada

- [X] T011 [US2] Criar `tests/test_project_enrichment_db.py` com uma fixture pytest que monte um SQLite em memória contendo `initiative_types`, `initiatives` (deliberadamente **sem** a coluna `enrichment_json`, para exercitar a migração), `source_records` e `attribute_assertions`
- [X] T012 [US2] Na mesma fixture de `tests/test_project_enrichment_db.py`, construir a instância de `ProjectEnrichmentLoader` via `__new__` com `overwrite=False` e `dry_run=False`, injetando a sessão pela cadeia `controller._service._repository._session`, sem instanciar `InitiativeController` (evita conexão ao banco real)
- [X] T013 [P] [US2] Adicionar em `tests/test_project_enrichment_db.py` um auxiliar que escreva documentos `PJ_*.json` em `tmp_path` a partir de um dicionário, cobrindo os campos descritos em [data-model.md](data-model.md)
- [X] T014 [US2] Adicionar teste em `tests/test_project_enrichment_db.py` que exercite `run(pj_dir, ingest_new=False)` com `dry_run=False` sobre uma iniciativa **sem** descrição e afirme que a chamada não levanta, que `description` passou a ser a do documento e que `enrichment_json` ficou preenchido com `match_strategy` correto (cobre FR-001, FR-002, FR-003)
- [X] T015 [P] [US2] Adicionar teste em `tests/test_project_enrichment_db.py` que afirme que uma iniciativa **com** descrição preexistente tem sua descrição preservada e ainda assim recebe `enrichment_json`, contabilizando `desc_kept_existing` (cobre FR-003)
- [X] T016 [P] [US2] Adicionar teste em `tests/test_project_enrichment_db.py` para o caminho de zero documentos, afirmando que `run()` conclui, retorna estatísticas zeradas e não grava nada (cobre FR-001 e o caso de borda que hoje também quebra)
- [X] T017 [P] [US2] Adicionar teste em `tests/test_project_enrichment_db.py` que afirme que `dry_run=True` não grava nada no banco e ainda assim retorna estatísticas (cobre FR-006)

**Checkpoint**: O enriquecimento está comprovadamente acontecendo, e não apenas
"não falhando"

---

## Phase 5: User Story 3 - A falha não pode voltar despercebida (Priority: P2)

**Goal**: Garantir que a suíte acuse a reintrodução do defeito e que ela rode em
qualquer clone do repositório.

**Independent Test**: Reverter a correção, confirmar que a suíte falha; reaplicar,
confirmar que passa.

- [X] T018 [US3] Reverter temporariamente a alteração de T006 em `src/core/logic/project_enrichment.py`, executar `.venv/bin/python -m pytest tests/test_project_enrichment_db.py -v` e confirmar que os testes falham apontando `InvalidRequestError`; em seguida reaplicar a correção e confirmar que passam (cobre FR-009)
- [X] T019 [US3] Auditar `tests/test_project_enrichment_db.py` confirmando que ele não lê nenhum caminho fora de `tmp_path`, não usa `db/horizon.db`, não requer rede, servidor Prefect nem Docker, e não depende de variáveis de ambiente do projeto (cobre FR-010)
- [X] T020 [P] [US3] Acrescentar ao cabeçalho de `tests/test_project_enrichment.py` uma nota curta apontando que a cobertura com banco vive em `tests/test_project_enrichment_db.py`, para que o contrato "DB-free" declarado ali continue verdadeiro e localizável

**Checkpoint**: A regressão está travada por teste automatizado

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T021 Executar `make ci-check` e corrigir eventuais apontamentos de black, isort e flake8 nos arquivos tocados (portão mínimo definido pela constituição)
- [X] T022 Executar a suíte completa com `.venv/bin/python -m pytest -q` e comparar com a linha de base anotada em T002, confirmando que nenhum teste preexistente regrediu
- [X] T023 [P] Percorrer [quickstart.md](quickstart.md) de ponta a ponta e corrigir qualquer divergência entre o roteiro e o comportamento real
- [X] T024 [P] Registrar em `docs/2 - implementacao/ADR/002-sigpesq-project-document-enrichment.md` uma nota de correção informando que a fase esteve inoperante desde a implementação original e o que foi corrigido, para que a consequência declarada "idempotente e reprodutível pelo pipeline" deixe de estar desatualizada
- [X] T025 [P] Registrar os follow-ups da seção final de [research.md](research.md) em `docs/backlog.md`: atomicidade real das gravações, fronteira transacional do `ensure_schema()` e divergência entre constituição e Makefile quanto à verificação de tipos

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Fase 1)**: sem dependências
- **Foundational (Fase 2)**: depende da Fase 1 — **BLOQUEIA** todas as user stories
- **US1 (Fase 3)**: depende da Fase 2
- **US2 (Fase 4)**: depende de T006 (a correção precisa existir para os testes passarem)
- **US3 (Fase 5)**: depende da Fase 4 (precisa dos testes escritos para revertê-los contra a correção)
- **Polish (Fase 6)**: depende de todas as anteriores

### User Story Dependencies

Diferente do caso usual, as stories **não** são independentes entre si aqui:

- **US1 (P1)**: independente — é a correção em si
- **US2 (P1)**: depende de T006 da US1. Não é uma story implementável em separado: a mesma edição atende as duas. O que a US2 acrescenta é a **prova** de que a gravação acontece
- **US3 (P2)**: depende dos testes da US2 existirem

Essa dependência é consequência do tamanho do trabalho, não de acoplamento
acidental. Está declarada aqui para não induzir a divisão do trabalho entre
pessoas diferentes.

### Within Each User Story

- Os testes da US2 falham antes de T006 e passam depois — a verificação está em T018
- Correção antes de verificação; verificação antes de polimento

### Parallel Opportunities

- T013, T015, T016 e T017 tocam o mesmo arquivo de teste mas seções distintas — podem ser escritos em paralelo se quem implementa cuidar dos conflitos de edição
- T023, T024 e T025 são independentes entre si e tocam arquivos diferentes
- T020 toca arquivo distinto dos demais da Fase 5

---

## Parallel Example: Phase 6

```bash
# Tarefas de documentação, independentes entre si:
Task: "Percorrer quickstart.md de ponta a ponta (T023)"
Task: "Nota de correção no ADR-002 (T024)"
Task: "Registrar follow-ups em docs/backlog.md (T025)"
```

---

## Implementation Strategy

### MVP (mínimo defensável)

1. Fase 1 (setup) e Fase 2 (decisão sobre a FR-004)
2. Fase 3 (US1) — a correção
3. **PARAR E VALIDAR**: a fase conclui com sucesso e `ingestion_runs` registra `success`

Isso já elimina o `exit 1` do pipeline semanal. **Mas não é suficiente para
declarar o problema resolvido**: sem a Fase 4, o que se tem é uma fase que termina
bem sem provar que grava alguma coisa — exatamente o risco de falso positivo
apontado na especificação.

### Entrega recomendada

Fases 1 a 5 juntas, mais a Fase 6. É pouco trabalho e entrega a correção com a
prova de que ela funciona e com a proteção contra regressão.

### Estratégia de equipe

Não se aplica: o trabalho é pequeno demais para paralelizar entre pessoas, e as
stories têm dependência sequencial declarada acima.

---

## Notes

- `[P]` = arquivos diferentes, sem dependências pendentes
- Este trabalho **não** toca Docker, não atualiza `agent_sigpesq` e não gera os documentos `PJ_*.json` ausentes — todos fora de escopo por decisão registrada na especificação
- Commits ficam a critério do responsável; nenhuma tarefa desta lista faz commit ou push
