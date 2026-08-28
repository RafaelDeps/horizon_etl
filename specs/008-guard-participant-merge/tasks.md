---

description: "Task list for feature 008-guard-participant-merge"
---

# Tasks: Proteger participantes contra fusão por nome

**Input**: Design documents from `/specs/008-guard-participant-merge/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/regras_correspondencia.md

**Tests**: a feature **é** testes. Nenhum código de produção é alterado.

**Organization**: agrupadas por história. US1 (orientação não funde) e US2 (projeto
funde) são ambas P1 e precisam ser entregues juntas — uma proteção que só saiba
dizer "não funda nada" devolveria as 57 duplicatas de projeto.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

**Purpose**: registrar o ponto de partida, para que qualquer mudança de resultado
na suíte seja atribuível.

- [X] T001 Registrar o resultado atual da suíte em `/tmp/horizon-008/baseline.txt` executando `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration`, para comparação posterior (esperado: 277 passando, 6 falhas pré-existentes)

---

## Phase 2: Foundational

**Purpose**: os utilitários de montagem de cenário que as duas histórias usam.
Bloqueia US1 e US2.

- [X] T002 Em `tests/test_project_loader_matching.py`, adicionar helper que constrói um `ProjectLoader` sem `__init__` (`ProjectLoader.__new__`) com `adv_controller` e `controller` mockados, seguindo o padrão dos dois testes já existentes no arquivo
- [X] T003 Em `tests/test_project_loader_matching.py`, adicionar helpers que produzem um candidato-orientação (`MagicMock(spec=Advisorship)`) e um candidato-projeto (`MagicMock()` com `adv_controller.get_by_id` devolvendo `None`), conforme a decisão R3 de `research.md`

**Checkpoint**: cenários montáveis sem banco.

---

## Phase 3: User Story 1 — Orientação nunca funde por nome aproximado (P1)

**Goal**: reintroduzir a fusão passa a reprovar em segundos.

**Independent Test**: desfazer a guarda no código de produção e confirmar que a
suíte reprova (T009).

- [X] T004 [US1] Em `tests/test_project_loader_matching.py`, teste do Cenário A de `data-model.md`: `_resolve_existing_initiative` com `model_class=Advisorship` e um índice normalizado contendo outra orientação de mesmo título normalizado devolve `None` — a regra R1 do contrato
- [X] T005 [US1] Em `tests/test_project_loader_matching.py`, teste da **consequência**: processadas duas linhas de orientação com o mesmo título e participantes distintos, a segunda chega ao handler com `existing_initiative=None`. Exercitar `_process_row` com `mapping_strategy`, `handlers`, `entity_manager`, `initiative_type`, `org_id` e `linker` mockados, e `patch` explícito no `tracking_recorder` do módulo — a dependência não pode ficar implícita no retorno silencioso (ver *Complexity Tracking* do plano)

**Checkpoint**: a regra que custou 200 vínculos está fixada nas duas camadas.

---

## Phase 4: User Story 2 — Projeto continua fundindo (P1)

**Goal**: a proteção não reabre o problema que a melhoria resolveu.

**Independent Test**: verificar que um projeto em caixa diferente é reconhecido,
na mesma suíte que garante que orientações não são.

- [X] T006 [US2] Em `tests/test_project_loader_matching.py`, teste do Cenário B: `_resolve_existing_initiative` com `model_class` de projeto e índice normalizado contendo o mesmo nome em grafia diferente devolve o projeto existente — regra R2
- [X] T007 [P] [US2] Em `tests/test_project_loader_matching.py`, teste do Cenário C: havendo coincidência exata **e** aproximada, a exata prevalece — regra R3
- [X] T008 [P] [US2] Em `tests/test_project_loader_matching.py`, teste da regra R5: índice ausente, vazio ou título vazio produzem "não encontrado" e não levantam erro

**Checkpoint**: as duas regras coexistem e estão fixadas.

---

## Phase 5: User Story 3 — O nome persistido prevalece (P2)

**Goal**: reconhecer por grafia diferente não renomeia o registro existente.

- [X] T010 [US3] Em `tests/test_project_loader_matching.py`, teste do Cenário D: reconhecido o projeto por nome normalizado, o `project_data["title"]` passado ao handler é o **nome já persistido**, não o do registro que chegou — regra R4

---

## Phase 6: Validação

**Purpose**: provar que a rede funciona. **Nenhuma tarefa aqui é opcional.**

- [X] T009 **Experimento obrigatório (SC-001)**: comentar a guarda `if model_class is Advisorship: return None` em `src/core/logic/project_loader.py`, executar `pytest tests/test_project_loader_matching.py` e **confirmar que reprova**; restaurar a guarda e confirmar `git diff src/` vazio. Se a suíte passar com a guarda desfeita, os testes de T004 e T005 são decorativos e devem ser refeitos antes de seguir
  - **Resultado**: o experimento **pegou um teste decorativo**. Com a guarda desfeita, o teste do resolvedor (T004) reprovou corretamente, mas o de consequência (T005) **passou** — o mock da iniciativa criada não tinha `.name` real, então a chave do índice normalizado saía sem sentido e a segunda linha nunca encontrava a primeira. Corrigido; com a guarda desfeita os **dois** reprovam, e com ela restaurada os oito passam. Sem T009 a feature teria entregue metade da proteção que anunciava.
- [X] T011 Verificar SC-002 e SC-003: todos os testes novos passam, em menos de 5 s, sem banco nem rede
- [X] T012 Verificar SC-005: rodar a suíte completa e comparar com `/tmp/horizon-008/baseline.txt`; nenhum teste existente pode mudar de resultado
- [X] T013 [P] Rodar `black`, `isort` e `flake8` em `tests/test_project_loader_matching.py`
- [X] T014 Confirmar FR-007: `git diff src/` vazio ao final. Se algum teste tiver reprovado contra o código atual, **reportar** em vez de alterar produção

---

## Dependencies

```text
Setup (T001) ──► Foundational (T002-T003) ──┬──► US1 (T004-T005) ──┐
                                             ├──► US2 (T006-T008)  ├──► Validação (T009-T014)
                                             └──► US3 (T010) ──────┘
```

- **T009 depende de T004 e T005** — é o experimento que valida justamente esses dois.
- **T001 antes de tudo**: a linha de base tem de ser capturada antes de qualquer teste novo entrar, senão SC-005 não é verificável.

## Parallel Opportunities

Todas as tarefas de teste tocam **o mesmo arquivo**, então os marcadores `[P]`
valem apenas para indicar independência lógica — na prática são escritas em
sequência. T013 é paralela ao restante da validação.

## Implementation Strategy

**US1 e US2 juntas são a entrega mínima.** US1 sozinha protegeria contra a fusão
de orientações mas deixaria alguém livre para "resolver" o problema desligando a
correspondência aproximada por inteiro, devolvendo as 57 duplicatas de projeto.
As duas regras se defendem mutuamente.

**T009 é o que separa esta feature de teatro de testes.** Os 283 testes que
existiam antes passavam — e não protegiam nada. A única evidência de que uma rede
funciona é vê-la falhar quando deve.
