# Implementation Plan: Índice leve de correspondência de pesquisadores na ingestão do Lattes

**Branch**: `007-researcher-lookup-index` | **Date**: 2026-08-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/007-researcher-lookup-index/spec.md`

## Summary

As duas fases de ingestão do Lattes leem o cadastro inteiro de pesquisadores uma
vez por currículo — 224 leituras de 7,8 s cada, 29 dos 43 minutos que as duas
fases consomem. A leitura é cara porque a entidade `Researcher` carrega quatro
coleções de forma ansiosa, gerando 828.644 linhas para montar 1060 objetos.

A correção substitui essa leitura por um **índice de correspondência**: uma
estrutura de dados própria, construída **uma vez por fase** com uma consulta que
traz apenas os seis campos usados na identificação do dono do currículo (0,9 ms),
e que expõe os mesmos nomes de atributo da entidade ORM — de modo que o algoritmo
de pontuação, cuja equivalência precisa ser preservada, não muda. O pesquisador
vencedor é carregado como entidade completa sob demanda, apenas onde o restante
da ingestão precisa dele para atualizar e vincular.

Mudança contida: dois flows, um módulo de lógica, testes nos arquivos já
existentes.

## Technical Context

**Language/Version**: Python 3.14.4 (`.venv`)

**Primary Dependencies**: SQLAlchemy 2.0.x, Prefect 3.6.23, research-domain v0.14.4

**Storage**: SQLite (`db/horizon.db`), tabelas `persons` e `researchers`
(herança por junção)

**Testing**: pytest — `tests/test_ingest_lattes_projects_flow.py`,
`tests/integration/flows/test_ingest_lattes_advisorships.py`, mais um arquivo novo
para o índice e a equivalência de correspondência

**Target Platform**: Linux

**Project Type**: Pipeline ETL de projeto único

**Performance Goals**: as duas fases somadas abaixo de 15 min (hoje 43 min);
custo de correspondência por currículo independente do tamanho do cadastro

**Constraints**: todos os controllers compartilham **a mesma sessão**
SQLAlchemy; `ProjectLoader._rollback_session()` expira objetos ORM e torna a
varredura seguinte 12,4 s mais cara, o que exclui soluções presas à sessão; a
biblioteca `research_domain` não pode ser alterada

**Scale/Scope**: 112 currículos, 1060 pesquisadores, 4445 pessoas

## Constitution Check

| Princípio | Situação | Justificativa |
|---|---|---|
| **I. Ports & Adapters** | ✅ Conforme | Mudança em `src/core/logic/` e `src/flows/`, sem importar `src/adapters/`. A consulta direta usa a sessão já obtida pelos controllers, mesmo mecanismo que `_linked_data_score` usa hoje no mesmo arquivo. |
| **II. Domain-First** | ✅ Conforme com justificativa | O índice **não** é entidade de domínio nova: é estrutura transitória de ETL, viva apenas durante a fase, nunca persistida nem exportada — a exceção que o próprio princípio prevê. A entidade canônica continua sendo `Researcher`, do `research_domain`. |
| **III. Prefect Flow** | ✅ Conforme | Nenhum flow novo; os dois flows existentes mantêm estrutura e tarefas. O índice é construído no corpo do flow e passado às tarefas, como já acontece com `entity_manager` e `parser`. |
| **IV. Audit-Driven** | ✅ Conforme | Nenhuma mudança nos registros de rastreabilidade. SC-003 exige contagens idênticas, e a validação compara os dois lados. |
| **V. LGPD** | ✅ Conforme | O índice vive só em memória e carrega `name` e `identification_id` (este já anonimizado na escrita). Não é exportado, e **não deve ser registrado em log** — ver Complexity Tracking. |
| **Data Integrity** | ✅ Conforme | Sem mudança de esquema. Banco continua recriável por `make db-reset` + flows. |
| **Quality Gates** | ✅ Conforme | black/isort/flake8 nos arquivos tocados e pytest. `make ci-check` completo continua reprovando por motivo alheio (TD-003), então a verificação é dirigida aos arquivos alterados, como o CI já faz. |

**Gate pré-Fase 0**: PASSA. **Gate pós-Fase 1**: PASSA, com a ressalva de log
registrada abaixo.

## Project Structure

### Documentation (this feature)

```text
specs/007-researcher-lookup-index/
├── plan.md              # Este arquivo
├── spec.md              # O quê e por quê
├── research.md          # Medições e decisões (Fase 0)
├── data-model.md        # Estrutura do índice (Fase 1)
├── quickstart.md        # Como validar (Fase 1)
├── contracts/
│   └── researcher_resolution.md   # Contrato interno das funções compartilhadas
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/core/logic/
└── researcher_resolution.py    # ALTERADO — carregador do índice, estrutura do
                                #   registro, remoção do critério inaplicável,
                                #   acréscimo de recém-criados ao índice

src/flows/lattes/
├── projects.py                 # ALTERADO — índice construído no flow e passado
                                #   às funções; hidratação do vencedor
└── advisorships.py             # ALTERADO — índice construído no flow e passado
                                #   à tarefa

tests/
├── test_researcher_lookup_index.py          # NOVO — carregamento, acréscimo,
                                             #   equivalência de correspondência
├── test_ingest_lattes_projects_flow.py      # ALTERADO — nova assinatura
└── integration/flows/
    └── test_ingest_lattes_advisorships.py   # ALTERADO — nova assinatura
```

**Structure Decision**: a mudança é de acesso a dado dentro da lógica de
correspondência, então o carregador do índice fica em
`src/core/logic/researcher_resolution.py`, junto das funções que o consomem. Os
flows passam a construir o índice uma vez e repassá-lo, exatamente o padrão que
`projects.py` já usa para `entity_manager` e `parser`. Nenhum módulo novo é
criado em `src/core/`, e nenhum adaptador é tocado.

## Complexity Tracking

| Ponto | Descrição | Mitigação |
|---|---|---|
| **Consulta SQL escrita à mão dentro da lógica** | O carregador do índice emite SQL referenciando `persons` e `researchers` diretamente, em vez de passar pelo controller. Se a biblioteca mudar o esquema, isso quebra. | O mesmo arquivo já faz isso em `_linked_data_score`, com o mesmo risco e o mesmo tratamento; o carregador segue o padrão vizinho. A quebra é ruidosa (erro de coluna inexistente na primeira execução), não silenciosa. Um teste do carregador contra banco real cobre a regressão. |
| **Nome de pessoa em memória durante toda a fase** | O índice mantém 1060 nomes vivos do início ao fim. Nome não é dado sensível sob a política do projeto, mas o índice **não pode ser despejado em log** em nenhuma circunstância. | Nenhum log registra o índice inteiro; as mensagens existentes citam um pesquisador por vez, como hoje. Revisão do diff verifica isso explicitamente. |
| **Duas formas de representar um pesquisador** | Passa a existir o registro leve do índice e a entidade completa. Um caminho que espere a entidade e receba o registro leve falharia. | O registro leve expõe os mesmos nomes de atributo, então o algoritmo de correspondência é indiferente. Os pontos que precisam da entidade são conhecidos e poucos — `projects.py` atualiza e persiste o dono do currículo — e recebem a hidratação explícita. O contrato em `contracts/` documenta qual função devolve o quê. |
