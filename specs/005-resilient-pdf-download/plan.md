# Implementation Plan: Descoberta resiliente dos anexos de projeto do SigPesq

**Branch**: `005-resilient-pdf-download` | **Date**: 2026-08-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-resilient-pdf-download/spec.md`

## Summary

A etapa de download não traz nenhum documento porque a biblioteca localiza o
anexo por um fragmento fixo de identificador que não existe mais na página. A
correção substitui essa localização por uma descoberta baseada em duas
características independentes (verbo no identificador; extensão no texto visível)
e passa a classificar cada projeto em quatro situações, distinguindo "sem anexo"
de "estrutura não reconhecida" — distinção que hoje não existe e que foi o que
manteve o defeito invisível.

Tudo fica numa subclasse dentro do ETL; a biblioteca externa não é tocada. A
verificação roda offline, com páginas locais.

## Technical Context

**Language/Version**: Python 3.14.4 (`.venv`); imagem Docker usa 3.12.13

**Primary Dependencies**: `agent_sigpesq` (fixado no SHA `8f41f7a9`), Playwright,
Prefect 3.6.23, loguru

**Storage**: PDFs em `data/raw/sigpesq_project_files/project_files/`; JSON em
`data/exports/project_sigpesq_files_json/` (este último fora do versionamento)

**Testing**: pytest com Playwright carregando HTML local via `set_content` — sem
rede, sem portal

**Target Platform**: Linux

**Project Type**: Pipeline ETL de projeto único

**Performance Goals**: irrelevante para a descoberta em si; o custo dominante é a
navegação, inalterada. Os testes offline devem rodar em segundos.

**Constraints**: a biblioteca `agent_sigpesq` **não pode** ser alterada (restrição
explícita do usuário); o portal limita tentativas de acesso, então a validação
principal é offline; login, navegação, paginação e retomabilidade continuam sendo
responsabilidade da biblioteca

**Scale/Scope**: 371 projetos no portal; 342 documentos já obtidos; 1 arquivo novo
de produção, 1 de teste, e ajuste pontual no adapter existente

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Avaliado contra `.specify/memory/constitution.md` v1.0.0.

| Princípio | Situação | Justificativa |
|---|---|---|
| **I. Ports & Adapters** | ✅ Conforme | A subclasse fica em `src/adapters/sources/sigpesq/`, que é exatamente a camada de mediação com sistema externo. Nada de lógica de negócio em `src/core/logic/`. |
| **II. Domain-First** | ✅ Conforme | Nenhuma entidade de domínio é criada ou redefinida; o trabalho é de aquisição de arquivo. |
| **III. Prefect Flow Orchestration** | ✅ Conforme | O flow `Extract SigPesq Project Files` já existe e não muda; apenas a estratégia que ele usa é substituída. |
| **IV. Audit-Driven Data Quality** | ✅ **Reforça** | O resumo por situação é, em essência, a verificação de qualidade que faltava nesta etapa. Hoje ela não produz nenhuma contagem auditável. |
| **V. LGPD** | ✅ Conforme | Nenhum dado pessoal é lido, gravado ou registrado. Os logs contêm código de projeto e nome de arquivo. |
| **Data Integrity & Clean-State** | ✅ Conforme | Retomabilidade preservada; nada passa a ser fonte de verdade. |
| **Quality Gates** | ✅ Conforme | black/isort/flake8 nos arquivos tocados e suíte pytest, como na branch anterior. |

**Gate pré-Fase 0**: PASSA. **Gate pós-Fase 1**: PASSA, sem violações a justificar.

## Project Structure

### Documentation (this feature)

```text
specs/005-resilient-pdf-download/
├── plan.md              # Este arquivo
├── spec.md              # Especificação aprovada
├── research.md          # Fase 0 — diagnóstico e prova de conceito
├── data-model.md        # Fase 1 — situações e contagens
├── quickstart.md        # Fase 1 — como verificar
├── contracts/
│   └── discovery.md     # Contrato da descoberta e da classificação
├── checklists/
│   └── requirements.md  # 16/16
└── tasks.md             # Fase 2
```

### Source Code (repository root)

```text
src/adapters/sources/sigpesq/
├── adapter.py                     # inalterado
├── project_files.py               # ALTERADO — passa a usar a estratégia resiliente
└── project_files_strategy.py      # NOVO — subclasse com descoberta e contagens

src/flows/sigpesq/
└── project_files.py               # ALTERADO — só para logar o resumo por situação

tests/
└── test_project_files_strategy.py # NOVO — 4 cenários offline com HTML local
```

**Structure Decision**: A subclasse vive junto do adapter que a consome, em
`src/adapters/sources/sigpesq/`, seguindo a divisão já estabelecida entre
adaptadores (integração externa), flows (orquestração) e lógica de núcleo. O
arquivo é separado do `project_files.py` porque são responsabilidades distintas:
um conduz as duas etapas do processo, o outro sabe ler uma página do portal.

## Complexity Tracking

> Sem violações constitucionais a justificar.

Um risco de produto, porém, precisa ficar registrado — não é violação, mas
condiciona o valor entregue:

| Risco | Descrição | Mitigação |
|---|---|---|
| A correção pode não mudar o resultado prático | Se a leitura correta do diagnóstico for "os anexos foram removidos do portal", a descoberta resiliente estará certa e ainda assim nenhum documento será baixado. | A US2 entrega valor de qualquer forma: o resumo por situação torna essa conclusão explícita já na primeira execução, em vez de disfarçada de sucesso. A US3 encerra a dúvida quando o portal liberar acesso. |
