---

description: "Task list for 005-resilient-pdf-download"
---

# Tasks: Descoberta resiliente dos anexos de projeto do SigPesq

**Input**: Design documents from `/specs/005-resilient-pdf-download/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/)

**Tests**: Incluídos — a especificação os exige (FR-010 e User Story 3).

**Organization**: Agrupadas por user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: pode rodar em paralelo (arquivos distintos, sem dependências pendentes)
- **[Story]**: US1, US2 ou US3
- Caminhos de arquivo são exatos

---

## Phase 1: Setup

- [X] T001 Confirmar a branch `005-resilient-pdf-download` e registrar a linha de base da suíte com `PYTHONPATH=. .venv/bin/python -m pytest -q`
- [X] T002 [P] Confirmar que os quatro cenários da prova de conceito de [research.md](research.md) D3 continuam reproduzíveis offline com Playwright

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: a estrutura de classificação que as duas stories P1 usam

- [X] T003 Criar `src/adapters/sources/sigpesq/project_files_strategy.py` com as quatro situações de [data-model.md](data-model.md) (`downloaded`, `no_attachment`, `unrecognized`, `modal_failed`) mais `skipped_existing`, e um contador por situação inicializado por execução
- [X] T004 No mesmo arquivo, definir a subclasse de `ProjectFilesDownloadStrategy` importada de `agent_sigpesq.strategies`, reaproveitando login, navegação, paginação e retomabilidade da biblioteca — sem alterar a biblioteca (FR-009)

**Checkpoint**: esqueleto pronto; as stories podem começar

---

## Phase 3: User Story 1 - Os documentos voltam a ser baixados (Priority: P1) 🎯 MVP

**Goal**: localizar o anexo sem depender de identificador fixo.

**Independent Test**: apontar a descoberta para uma página com anexo, em marcação conhecida e alternativa, e verificar que o anexo é localizado nas duas.

### Tests for User Story 1

- [X] T005 [US1] Criar `tests/test_project_files_strategy.py` com uma fixture que abra um navegador Playwright e sirva HTML local via `set_content`, sem qualquer acesso à rede
- [X] T006 [P] [US1] Adicionar em `tests/test_project_files_strategy.py` os fixtures de página dos quatro cenários de [contracts/discovery.md](contracts/discovery.md): marcação conhecida com anexo, marcação alternativa com anexo, área de anexos vazia, e página sem área de anexos
- [X] T007 [US1] Adicionar teste em `tests/test_project_files_strategy.py` afirmando que na marcação **conhecida** o anexo é localizado e escolhido **pelo rótulo** `"Projeto"`, não por posição (cobre FR-001, FR-002, FR-003)
- [X] T008 [P] [US1] Adicionar teste em `tests/test_project_files_strategy.py` afirmando que na marcação **alternativa** o anexo é localizado e que o escolhido é o do rótulo — cenário em que o primeiro da lista é o documento errado (cobre FR-002, FR-003)

### Implementation for User Story 1

- [X] T009 [US1] Implementar em `src/adapters/sources/sigpesq/project_files_strategy.py` a descoberta por duas características independentes — identificador contendo `download`/`baixar`/`arquiv`, ou texto terminando em `.pdf`/`.doc`/`.docx`/`.odt` — conforme D3 de [research.md](research.md)
- [X] T010 [US1] Implementar a seleção pelo rótulo desejado com recurso ao primeiro candidato, registrando quando a escolha foi por recurso (FR-003)
- [X] T011 [US1] Sobrescrever a inspeção de um projeto de modo a usar a descoberta nova, preservando o download com a **extensão original** do arquivo e o fechamento da janela (FR-008)

**Checkpoint**: a localização funciona nas duas marcações

---

## Phase 4: User Story 2 - Ausência de anexo deixa de se confundir com falha de leitura (Priority: P1)

**Goal**: tornar visível a diferença entre "não tem anexo" e "não reconheci a página".

**Independent Test**: rodar contra a página vazia e contra a irreconhecível e verificar relatos distintos.

### Tests for User Story 2

- [X] T012 [US2] Adicionar teste em `tests/test_project_files_strategy.py` afirmando que a página com área de anexos **vazia** resulta em `no_attachment` (cobre FR-004)
- [X] T013 [P] [US2] Adicionar teste em `tests/test_project_files_strategy.py` afirmando que a página **sem** área de anexos resulta em `unrecognized`, distinto do caso anterior (cobre FR-004)
- [X] T014 [P] [US2] Adicionar teste em `tests/test_project_files_strategy.py` afirmando a invariante do resumo: `examined` é igual à soma das demais contagens (cobre FR-005)

### Implementation for User Story 2

- [X] T015 [US2] Implementar em `src/adapters/sources/sigpesq/project_files_strategy.py` a detecção da área de anexos (cabeçalho, tabela ou bloco cujo texto inicial mencione "arquivo(s)") para separar `no_attachment` de `unrecognized`
- [X] T016 [US2] Emitir por projeto uma mensagem distinta para cada situação, deixando `unrecognized` visivelmente diferente de `no_attachment` (FR-004)
- [X] T017 [US2] Emitir ao fim do download o resumo com todas as contagens (FR-005), garantindo que um projeto não interpretável não interrompa os demais (FR-006)
- [X] T018 [US2] Alterar `src/adapters/sources/sigpesq/project_files.py` para usar a estratégia resiliente no lugar da estratégia da biblioteca e propagar as contagens no retorno de `download_pdfs`
- [X] T019 [US2] Alterar `src/flows/sigpesq/project_files.py` para registrar o resumo por situação no log do flow

**Checkpoint**: uma quebra de compatibilidade passa a se anunciar

---

## Phase 5: User Story 3 - O diagnóstico em aberto pode ser encerrado (Priority: P2)

**Goal**: transformar uma execução real na resposta sobre qual leitura é a verdadeira.

- [X] T020 [US3] Documentar em [quickstart.md](quickstart.md) a leitura do resumo — qual combinação de contagens corresponde a cada conclusão — de forma que a execução responda sozinha
- [X] T021 [US3] Executado em 25/08 21:05 com a região corrigida, 60 projetos: `no_attachment: 60, unrecognized: 0`. Inspeção dos controles confirmou que o modal só tem links "Lattes" e o botão "Fechar" — nenhum controle de download. **Diagnóstico encerrado**: os projetos realmente não têm anexo; ver [research.md](research.md)

**Checkpoint**: diagnóstico encerrado ou pendência declarada

---

## Phase 6: Polish

- [X] T022 Rodar black, isort e flake8 nos arquivos tocados e corrigir apontamentos
- [X] T023 Rodar `PYTHONPATH=. .venv/bin/python -m pytest -q` e comparar com a linha de base de T001, confirmando nenhuma regressão
- [X] T024 [P] Registrar em `docs/backlog.md` o follow-up de relatar ao `sigpesq_agent` a fragilidade do seletor fixo, deixando claro que o ETL não depende dessa correção

---

## Dependencies & Execution Order

- **Setup (F1)** → **Foundational (F2)** → **US1 (F3)** e **US2 (F4)** → **US3 (F5)** → **Polish (F6)**
- US2 depende de US1 apenas no arquivo compartilhado: a descoberta (T009) precisa existir para a classificação (T015) fazer sentido
- **T021 depende de fator externo** (liberação do portal) e pode ficar pendente sem bloquear a entrega

### Parallel Opportunities

- T006, T008, T013 e T014 são seções distintas do mesmo arquivo de teste
- T024 é independente de tudo na Fase 6

---

## Implementation Strategy

### MVP

Fases 1 a 4. Entrega a descoberta resiliente **e** a distinção que torna o
problema visível. É o mínimo defensável: só a US1 correria o risco de "consertar"
algo que talvez não mude o resultado prático, sem que ninguém consiga perceber.

### Observação honesta sobre o valor

Se o diagnóstico da US3 concluir que os anexos foram removidos do portal, a US1
não mudará nada na prática. Ainda assim o trabalho vale, porque a US2 substitui
uma etapa que mente por uma que informa. Isso está registrado como risco de
produto no [plan.md](plan.md).

---

## Notes

- A biblioteca `agent_sigpesq` **não** é alterada em nenhuma tarefa
- Nenhuma tarefa faz commit ou push
- Docker, orquestrador e pipeline semanal estão fora de escopo
