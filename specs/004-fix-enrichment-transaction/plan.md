# Implementation Plan: Correção da falha da fase de enriquecimento de projetos

**Branch**: `004-fix-enrichment-transaction` | **Date**: 2026-08-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-fix-enrichment-transaction/spec.md`

## Summary

A fase de enriquecimento de projetos aborta de forma determinística porque
`ProjectEnrichmentLoader.run()` abre uma transação explícita depois que as
leituras de índice já abriram uma (autobegin do SQLAlchemy 2.0). A correção
remove o `begin()` explícito e passa a confirmar ou desfazer a transação ambiente,
preservando os `SAVEPOINT` por linha. Acompanha um teste de regressão que
exercita o caminho de gravação contra um SQLite em memória, cobrindo a lacuna que
permitiu o defeito passar — a suíte atual é declaradamente livre de banco.

Escopo deliberadamente estreito: um arquivo de produção alterado, um arquivo de
teste criado.

## Technical Context

**Language/Version**: Python 3.14.4 no `.venv` do projeto (a imagem Docker usa
3.12.13; ambas reproduzem o defeito de forma idêntica)

**Primary Dependencies**: SQLAlchemy 2.0.52 (2.0.51 na imagem), Prefect 3.6.23,
Pydantic 2.x, `research-domain`/`eo_lib` (entidades canônicas e sessão), rapidfuzz

**Storage**: SQLite em `db/horizon.db` via `DATABASE_URL`; a sessão é criada por
`eo_lib` com `scoped_session(sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False))`

**Testing**: pytest; teste novo usa SQLite em memória com sessão injetada, sem
banco do projeto, sem rede e sem servidor Prefect

**Target Platform**: Linux; execução local via Makefile e, futuramente, container

**Project Type**: Pipeline ETL de projeto único, orquestrado por Prefect

**Performance Goals**: Não aplicável — a fase tem tempo limite de 900 s no
orquestrador e opera sobre centenas de documentos; a correção não altera o
volume de trabalho nem o número de consultas

**Constraints**: A correção não pode alterar regra de negócio (correspondência,
deduplicação, idempotência, preservação de descrição autoritativa) nem a
classificação da fase no orquestrador; o teste precisa ser autossuficiente dentro
do repositório

**Scale/Scope**: 1 arquivo de produção alterado (~6 linhas), 1 arquivo de teste
novo; 342–355 documentos por execução quando os insumos existirem

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Avaliado contra `.specify/memory/constitution.md` v1.0.0.

| Princípio | Situação | Justificativa |
|---|---|---|
| **I. Ports & Adapters** | ✅ Conforme | A mudança fica em `src/core/logic/`, que não passa a importar nada de `src/adapters/`. Nenhum contrato de porta é tocado. |
| **II. Domain-First Data Modeling** | ✅ Conforme | Nenhuma entidade nova. `Initiative` continua vindo de `research-domain`; a correção não redefine conceito de domínio. |
| **III. Prefect Flow Orchestration** | ✅ Conforme | O flow `Enrich SigPesq Projects` já existe, com os hooks de estado do Telegram. A fase continua sendo invocada via `app.py` (modo `app`), preservando o hook LGPD instalado no import. |
| **IV. Audit-Driven Data Quality** | ✅ Conforme | O rastro de proveniência existente é preservado integralmente. A correção **restaura** a trilha de auditoria: hoje `ingestion_runs` só consegue registrar falha. |
| **V. LGPD Compliance by Default** | ✅ Conforme | Nenhum campo pessoal novo é lido, gravado ou exportado. O caminho de gravação continua passando pelo hook de anonimização. |
| **Data Integrity & Clean-State** | ✅ Conforme | Banco continua recriável do zero; nenhum artefato passa a ser fonte de verdade. |
| **Development Workflow & Quality Gates** | ✅ Conforme | `make ci-check` é o portão. A constituição exige teste para novo flow; aqui não há flow novo, mas o trabalho **adiciona** cobertura onde não havia. |

**Resultado do gate (pré-Fase 0)**: PASSA.

**Resultado do gate (pós-Fase 1)**: PASSA, com uma ressalva registrada em
*Complexity Tracking* — a **FR-004** da especificação não será integralmente
satisfeita, por limitação preexistente do driver de banco documentada em
[research.md](research.md) D3. Não é violação de princípio constitucional, mas
requer decisão explícita antes da implementação.

## Project Structure

### Documentation (this feature)

```text
specs/004-fix-enrichment-transaction/
├── plan.md              # Este arquivo
├── spec.md              # Especificação aprovada
├── research.md          # Fase 0 — causa raiz, forma da correção, achado D3
├── data-model.md        # Fase 1 — entidades percorridas (nenhuma nova)
├── quickstart.md        # Fase 1 — roteiro de reprodução e validação
├── contracts/
│   └── enrichment-run.md    # Contrato de CLI e de comportamento de run()
├── checklists/
│   └── requirements.md      # Checklist de qualidade da spec (16/16)
└── tasks.md             # Fase 2 — gerado por /speckit-tasks
```

### Source Code (repository root)

```text
src/
├── core/logic/
│   └── project_enrichment.py      # ALTERADO — fronteira transacional em run()
├── flows/
│   ├── sigpesq/enrich_projects.py # inalterado — flow Prefect da fase
│   └── pipelines/
│       └── weekly_orchestrator.py # inalterado — declaração da fase
└── db/migrations.py               # inalterado — migração 0001

tests/
├── test_project_enrichment.py     # inalterado — lógica pura, sem banco
└── test_project_enrichment_db.py  # NOVO — regressão do caminho de gravação

app.py                             # inalterado — despacho da fase
```

**Structure Decision**: Projeto único de pipeline ETL, com separação já
estabelecida entre `src/core/logic` (regra de negócio), `src/flows` (orquestração)
e `src/adapters` (integrações externas). A correção é cirúrgica e permanece
inteiramente dentro da camada de lógica; o teste novo acompanha a convenção plana
de `tests/`, com nome distinto para não contradizer o contrato declarado do
arquivo de testes existente (ver [research.md](research.md) D5).

## Complexity Tracking

> Preenchido porque o gate pós-Fase 1 tem uma ressalva que precisa de decisão.

| Violação | Por que existe | Alternativa mais simples rejeitada porque |
|---|---|---|
| **FR-004 (atomicidade) não será integralmente satisfeita** | O driver `pysqlite` confirma cada `SAVEPOINT` liberado quando ele é o primeiro comando da transação, então as gravações de linha do loader são efetivamente confirmadas uma a uma. Verificado empiricamente e documentado em [research.md](research.md) D3. Precede esta correção. | Configurar o engine (`isolation_level=None` + listener de `BEGIN`) resolveria, mas o engine é criado dentro da dependência externa `eo_lib` e é compartilhado por todos os flows — SigPesq, Lattes, CNPq e o hook LGPD. Alterar o comportamento transacional do aplicativo inteiro como efeito colateral de uma correção pontual é desproporcional e arriscado, além de extrapolar o escopo definido para esta branch. |

**Decisão pendente do responsável**: seguir com o escopo estreito e registrar a
limitação como follow-up (recomendado), ou ampliar esta branch para tratar a
configuração transacional do engine. A implementação não deve começar antes dessa
definição, porque ela altera o que a Fase 2 precisa produzir.
