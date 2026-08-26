---

description: "Task list for 006-preserve-review-origin"
---

# Tasks: Preservar origem e necessidade de revisão

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md)

**Tests**: incluídos — a especificação exige verificação de reexecução (SC-001).

## Phase 1: Setup

- [X] T001 Registrar a linha de base da suíte com `PYTHONPATH=. .venv/bin/python -m pytest -q`

## Phase 2: Foundational

- [X] T002 Acrescentar ao payload em `src/core/logic/project_enrichment.py` os campos de **origem** e de **estado de revisão** (quando e por quem), com valores padrão que mantenham legíveis os payloads gravados antes desta mudança
- [X] T003 Implementar em `src/core/logic/project_enrichment.py` a função pura que **deriva** a necessidade de revisão a partir de origem, incerteza da correspondência e revisão registrada

## Phase 3: US1 + US2 — a marca não some e a origem é permanente (P1) 🎯 MVP

### Tests

- [X] T004 [US1] Adicionar em `tests/test_project_enrichment.py` testes da derivação: criada de documento sem revisão exige revisão; correspondência incerta exige revisão; revisada não exige; correspondência confiável e origem comum não exige
- [X] T005 [P] [US2] Adicionar em `tests/test_project_enrichment.py` testes de que a origem é preservada quando há payload anterior, e inferida da estratégia registrada quando o payload anterior é de formato antigo
- [X] T006 [US1] Adicionar em `tests/test_project_enrichment_db.py` o teste central da feature: executar o enriquecimento **duas vezes** sobre os mesmos dados e afirmar que a quantidade marcada para revisão **não diminuiu** (cobre SC-001, FR-004)

### Implementação

- [X] T007 [US2] Implementar em `src/core/logic/project_enrichment.py` a leitura do enriquecimento atual das iniciativas antes da sobrescrita
- [X] T008 [US1] Alterar a montagem do payload para receber o payload anterior, carregar dali origem e estado de revisão, e derivar a marca em vez de recebê-la pronta
- [X] T009 [US2] Garantir que a criação de iniciativa a partir de documento grave a origem correspondente

## Phase 4: US3 — revisão humana registrável (P2)

- [X] T010 [US3] Implementar em `src/core/logic/project_enrichment.py` o registro de revisão de uma iniciativa, que limpa a marca sem apagar a origem (FR-006, FR-010)
- [X] T011 [US3] Adicionar em `tests/test_project_enrichment_db.py` teste de que uma iniciativa revisada **não** volta a ser marcada numa reexecução (FR-006)
- [X] T012 [US3] Expor o registro de revisão como comando em `app.py`, orientando na documentação a usar identificador não-pessoal (matrícula ou iniciais), nunca e-mail

## Phase 5: FR-009 — reconstrução da origem

- [X] T013 Implementar em `src/core/logic/project_enrichment.py` a reconstrução da origem a partir da trilha de auditoria, como capacidade acionável e **não** como etapa automática do pipeline
- [X] T014 [P] Adicionar em `tests/test_project_enrichment_db.py` teste da reconstrução: iniciativa com origem perdida volta a ser identificável e remarcada

## Phase 6: Polish

- [X] T015 Rodar black, isort e flake8 nos arquivos tocados
- [X] T016 Rodar a suíte completa e comparar com a linha de base de T001
- [X] T017 [P] Registrar no ADR-002 que a marca de revisão passou a ser derivada e persistente

## Dependencies

F1 → F2 → F3 → F4 → F5 → F6. T006 é o teste que caracteriza a feature e só passa depois de T007–T009.

## Notes

- Docker, orquestrador e pipeline semanal fora de escopo
- Nenhuma tarefa faz commit ou push
