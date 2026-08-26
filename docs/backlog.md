# General Project Backlog

**Central Tracking for Releases and Work Items**

## 1. Releases Log
Tracks the delivery of versions to production (Main Branch).

| Version | Date | Status | Description | PR / Commit |
|---------|------|--------|-------------|-------------|
| **v0.12.11** | 2026-02-03 | Released | Researcher Resume Ingestion from Lattes | PR #65 / Commit [TBD] |
| **v0.12.10** | 2026-02-03 | Released | Research-Domain v0.12.8 Upgrade | PR #64 / Commit [TBD] |
| **v0.12.9** | 2026-02-03 | Released | Academic Education Ingestion & SigPesq Strategy Refactor | PR #62 / Commit ef944b6 |
| **v0.12.8** | 2026-02-03 | Released | Research-Domain v0.12.7 Upgrade, CNPq URL, Citation Names & Co-Advisor Match | PR #61 / Commit 773a8f3 |
| **v0.10.0** | 2026-01-28 | Released | Strict Sponsor Name Mapping & Enrichment Fixes | PR #58 |
| **v0.9.1** | 2026-01-27 | Released | ProjectLoader Modularity & Pipeline Fixes | PR #55 |
| **v0.9.0** | 2026-01-26 | Released | SIGPESQ Advisorships Ingestion | PR #52 |
| **v0.8.0** | 2026-01-25 | Released | Research Group Auto-population & Canonical Export Fixes | PR #51 |
| **v0.5.1** | 2026-01-15 | Released | Team Ingestion Refactoring & Synchronization Fix | PR #45 |
| **v0.5.0** | 2026-01-12 | Released | CNPq Sync Enhanced (Missing Researchers Fix) | PR #37 |
| **v0.4.0** | 2026-01-09 | Released | CNPq Sync Base (US-009) | PR #18 |
| **v0.3.0** | 2026-01-07 | Released | SigPesq Enhancements, ResearcherID & Granular Strategy Pattern | PR #13 |
| **v0.2.0** | 2026-01-06 | Released | Research Group Ingestion & Local Infrastructure | Main |
| **v0.0.0** | 2026-01-01 | Released | Project Initiation | - |

## 2. In Progress Items (Current Sprint)
Reflecting active work from `SI.3 Product Backlog`.

- **Epic 1: Extração SigPesq (Release 1)**
    - [x] US-001 [Extração Projetos SigPesq](https://github.com/ifesserra-lab/horizon_etl/issues/2) (Merged)
    - [x] US-007 [Ingestão Grupos de Pesquisa] (PR #4 - Merged)
    - [x] T-Leaders [Implementação de Líderes] (PR #7 - Merged)
    - [x] T-ResearcherID [E-mail como identification_id] (PR #10 - Merged)
    - [x] T-StrategyPattern [Refatoração Strategy Pattern] (PR #11 - Merged)
    - [x] T-GranularStrategy [Refatoração Granular Pattern] (PR #12 - Merged)
    - [x] US-005 Observabilidade e Idempotência (Implemented)
    - [x] US-015 [Gestão de Equipes SigPesq] (PR #41 - Review)
    - [x] US-008 [Exportação JSON Canônico e Grupos] (PR #15 - Merged)
    - [x] US-011 [Pipeline Unificado & Filtro de Campus] (PR #30 - Merged)
    - [x] US-012 [Research Area Mart & Filter] (PR #31 - Merged)
    - [x] US-032 [Ingestão Bolsistas SigPesq / Advisorships] (Implemented)
    
- **Epic 6: Atualização Base CNPq (Release v0.4.0)**
    - [x] US-009 [Sincronização de Grupos CNPq] (PR #18, #19 - Merged)
    - [x] US-010 [Sincronização de Egressos CNPq] (PR #21 - Merged)

- **Epic 3: Dados de Execução FAPES (Release 3)**
    - [ ] US-006 [Extração de Editais FAPES (PDF)](https://github.com/ifesserra-lab/horizon_etl/issues/1)

- **Epic 7: Orquestração e Exportação**
    - [x] US-014 [Exportação de Iniciativas e Tipos] (Enriched Canonical Data)
- **Epic 8: Enriquecimento de Projetos Lattes**
    - [x] US-034 [Enriquecimento de Projetos, Membros e Patrocinadores Lattes] (PR #67)
    - [x] US-035 [Ingestão de Artigos Lattes - Periodicals & Conferences] (PR #67)
    - [x] US-036 [Ingestão de Orientações Lattes - Advisorships] (PR #67)

## 3. Hierarchical Status
Mapping Epics -> User Stories -> Tasks status.

### R1 - SigPesq
- **US-001**: Done (Merged)
- **US-007**: Done (Merged)
- **US-005**: Done (Implemented)
- **US-015**: Done (Implemented)
- **US-032**: Done (Implemented)

### R2 - Lattes & CNPq
- **US-009**: Done
- **US-010**: Done
- **US-014**: Done
- **US-034**: Done (Implemented)
- **US-035**: Done (Implemented)
- **US-036**: Done (Implemented)

### R3 - SigFapes
- **US-006**: Ready
    - T-006 [Dev] Scraper: Pending
    - T-007 [Dev] Parser: Pending
    - T-008 [Dev] Matcher: Pending
    - T-009 [Ops] Flow: Pending
### R4 - Analytics
  - R4 - Analytics: [x] Mart de Analytics (US-016)

## Follow-ups técnicos — origem: `specs/004-fix-enrichment-transaction` (2026-08-24)

- **TD-001 — Atomicidade real das gravações de enriquecimento**: no SQLite atual
  o driver `pysqlite` confirma cada `SAVEPOINT` liberado quando ele é o primeiro
  comando da transação, então as gravações de linha são efetivamente confirmadas
  uma a uma e um `rollback()` posterior não as desfaz. A FR-004 daquela feature
  fica parcialmente atendida. Mitigação exige configurar o engine
  (`isolation_level=None` + listener de `BEGIN`), que hoje é criado dentro da
  dependência externa `eo_lib` e compartilhado por todos os flows. Status: Ready.
- **TD-002 — Fronteira transacional do `ensure_schema()`**: `run_migrations()` faz
  `commit()` próprio no meio de `run()`, o que torna confusa a fronteira de
  transação e foi o pano de fundo do defeito corrigido. Mover a execução de
  migrações para a subida do aplicativo, junto da eventual adoção de Alembic
  (o ADR-002 já registra a DDL em runtime como *stopgap*). Status: Ready.
- **TD-003 — `make ci-check` não é executável hoje**: o alvo roda black, isort e
  flake8 sobre todo o repositório e falha (58 arquivos seriam reformatados por
  black, além de apontamentos de isort e flake8), enquanto o CI real verifica
  apenas arquivos alterados e flake8 restrito a `E9,F63,F7,F82`. A constituição
  cita `make ci-check` como portão mínimo e também menciona verificação de tipos
  (mypy), que o alvo não executa. Alinhar constituição, Makefile e CI. Status:
  Ready.
- **TD-004 — Ferramentas de desenvolvimento não declaradas**: pytest, pytest-mock,
  flake8, black e isort não constam do `requirements.txt`; o CI as instala
  ad hoc. Um venv criado por `make setup` não consegue rodar `make test`.
  Considerar um `requirements-dev.txt`. Status: Ready.
- **TD-005 — `agent_sigpesq` não distingue "sem anexo" de "página ilegível"**: a
  `ProjectFilesDownloadStrategy` emite a mesma mensagem nos dois casos. Investigação
  em 25/08 confirmou que a leitura dela estava **correta** (os projetos realmente não
  têm anexo; o `Repeater` vazio simplesmente não renderiza), mas foram necessárias
  cinco sondagens manuais ao portal para provar isso. O ETL já resolveu do seu lado
  (ver `specs/005-resilient-pdf-download`); vale sugerir a mesma distinção à
  biblioteca. Status: Ready.
- **TD-006 — Anexos ausentes no SigPesq**: oito projetos com documento extraído de
  PDF real em 10/08/2026 não têm mais arquivo anexado no portal (PJ 9760, 9742,
  9720, 9702, 9674, 9642, 9628, 9608). Nenhuma correção de código recupera isso —
  é questão de dado, para quem administra o SigPesq. Status: Ready.
