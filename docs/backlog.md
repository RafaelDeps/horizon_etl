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
- **TD-007 — `lattes_advisorships` roda perto do teto de tempo**: a fase percorre
  112 currículos Lattes em laço sequencial, um a um, cada um instanciando
  controladores e consultando o banco. Durações medidas no Prefect: 1346, 1350,
  1360, 1398, 1409 e **1741 s** — esta última a 59 segundos do limite de 1800 s
  então vigente, e já houve estouro em máquina mais lenta. O limite foi elevado
  para 3600 s em 26/08 como paliativo. A correção real é paralelizar o laço, como
  o `lattes_download` já faz com `ThreadPoolExecutor`; a margem volta a encolher
  conforme o instituto cresce. Status: **Resolvido em 27/08 — mas não como este
  item previa.** A medição mostrou que paralelizar não resolveria: o parse de
  cada currículo custa **0,1 ms** (0,0% da fase) e o restante é escrita em
  SQLite, serializada por natureza. O tempo estava em `ResearcherController()
  .get_all()`, chamado **uma vez por currículo**: 7,8 s por chamada, 867,1 s dos
  1424,6 s da fase (60,9%). A causa é produto cartesiano — a entidade
  `Researcher` declara quatro coleções `lazy="joined"`, então 1060 pesquisadores
  viram 828.644 linhas; a consulta em si roda em 0,01 s. A correção substituiu a
  leitura por um índice de correspondência carregado uma vez por fase
  (`load_researcher_index`, 9,3 ms), ver `specs/007-researcher-lookup-index/`.

## Follow-ups técnicos — origem: `specs/007-researcher-lookup-index` (2026-08-27)

- **TD-008 — Mesma leitura repetida fora das fases do Lattes**: o padrão
  corrigido no TD-007 existe em outros dois pontos, não medidos e não corrigidos:
  `src/core/logic/strategies/sigpesq_excel.py:100` chama `get_all()` dentro de
  `SigPesqResearcherStrategy.ensure()`, invocada por `research_group_loader.py:105`
  uma vez por pesquisador de grupo (há cache por nome em `_researcher_cache`, então
  o custo é por nome distinto); e `src/core/logic/strategies/cnpq_sync.py:250`
  chama `get_all()` dentro de `sync_members()`, invocada **uma vez por grupo** em
  `flows/cnpq/groups.py:139` — e o banco tem 347 grupos. O carregador
  `load_researcher_index` já é compartilhado, então adotá-lo nesses pontos é
  mudança de poucas linhas. Falta medir as fases `sigpesq` e `cnpq_sync` antes de
  decidir a prioridade. Status: Ready.
- **TD-009 — Coleções `lazy="joined"` em `Researcher` (biblioteca)**: a causa raiz
  do TD-007 está na modelagem do `research_domain`: `knowledge_areas`, `articles`,
  `productions` e `emails` são carregadas ansiosamente no mesmo SELECT, o que
  torna qualquer leitura de muitos pesquisadores quadrática. O ETL contornou
  deixando de pedir o que não usa, mas qualquer consumidor da biblioteca paga o
  mesmo preço. Vale propor `lazy="selectin"` à biblioteca. Status: Ready.
- **TD-010 — Correspondência de pesquisador apoia-se em menos critérios do que
  aparenta**: `_score_candidate` pontuava `brand_id` com 500, o maior peso da
  função, mas essa coluna não existe em `persons` nem em `researchers`, nem como
  atributo mapeado — o ramo nunca disparou. Foi removido em 27/08. Como
  `identification_id` é anonimizado na escrita, um Lattes ID cru também nunca casa
  com ele. Na prática a correspondência se apoia em `cnpq_url` e no nome. Um teste
  (`test_ingest_academic_education`) passava justamente por construir um mock com
  `brand_id`, algo impossível contra o banco real. Avaliar se o critério de
  correspondência precisa de um identificador estável adicional. Status: Ready.

## Follow-ups — origin: `specs/008-guard-participant-merge` (2026-08-28)

- **TD-011 — Lattes project sync wiped SigPesq students from project teams**:
  observed while validating dedup on the real run — the fresh
  `researchers_canonical.json` showed "Israel Magalhães do Carmo" (person 579)
  with **5** initiatives vs. the previously deployed run (person 567) with **9**.
  The four missing memberships were "*Research Project*" team links (BPM
  Pós-Gestão + 3× Air Writing). Root cause, confirmed from DB artifacts only (no
  replay needed):
  1. `sigpesq` loads the project team correctly — raw row
     `research_projects/Relatorio_28_08_2026.xlsx` (SR 367) lists "Israel
     Magalhães do Carmo" under `Estudantes` of PJ 8438.
  2. `ingest_lattes_projects` runs **after** SigPesq and upserts the *same*
     initiative (`entity_matches` SR 2563 → initiative 18, `identity_key`) with
     `raw_members` taken from the Lattes CV only — which lists just the
     coordinator and one researcher ("Francisco de Assis Bold", a typo) and no
     students.
  3. `TeamSynchronizer.synchronize_members` is a full sync:
     `_remove_obsolete_members` deleted every (person, role) not in the Lattes
     list, dropping the SigPesq students (and leaving a typo person
     `Francisco de Assis Bold`) on the project team. The dedup feature was NOT
     involved: the merge transfers `team_members`/`advisorship_members` (unit
     tested) and no orphaned rows referencing merged person 1209 exist.
  **Fix applied**: removal in `TeamSynchronizer` is now scoped to the roles the
  source actually provides (a Lattes sync claiming only coordinator/researcher
  roles no longer removes `Student` members from SigPesq; an empty member list
  removes nothing). Tests covering the invariant were added to
  `tests/test_team_synchronizer.py`. Note: a re-run of the weekly pipeline is
  required to restore Israel's BPM/Air Writing project memberships. Status: Fixed
  (needs re-run).

## Follow-ups — origin: `specs/015-team-lookup-index` (2026-10-22)

- **TD-012 — Team matching re-read the whole team register per record**:
  `TeamSynchronizer.ensure_team` called `TeamController.get_all()` for every
  project/advisorship record (eager joins of members, persons and roles: ~3.7M
  objects, 1.5–1.9 s per call at ~10.6k teams) and re-normalised every name. It
  made `lattes_projects` + `lattes_advisorships` take 333 of the 484 minutes of
  the 2026-10-22 weekly run. Status: **Fixed** by spec 015 (lookup built once per
  loader + one `ProjectLoader` per advisorships phase). Controlled replays were
  identical. Full run 8 h 04 → 3 h 01; see
  `docs/reports/2026-10-22-team-lookup-validation.md`.
- **TD-013 — Person and researcher name matching re-normalise every name per
  lookup**: on a miss, `PersonMatcher.match_or_create` re-normalises all ~17k
  cached person names (and again for the fuzzy pass), and
  `resolve_researcher_by_name` re-normalises all ~7.6k researcher names on every
  lookup. Together they are ~88% of what remains in the Lattes phases (33 and
  48 min). Same fix pattern as TD-012: pre-compute normalised keys once. Fold in
  the Prefect `quote()` change for large task parameters (spec 015 task T023,
  ~5%). Status: **Fixed** by spec 016 (name index in `PersonMatcher`,
  memoised name key, `quote()`). Replays were identical. Full run 3 h 01 → 2 h 09;
  Lattes phases 33.1 → 22.8 and 48.5 → 27.9 min on disk (9.9 and 13.8 on tmpfs).
  See `docs/reports/2026-10-22-name-matching-validation.md`. The 20-minute
  targets were not reached on disk; see TD-018.
- **TD-014 — CNPq phase**: fix TD-008 (researcher `get_all()` per group) and
  fetch groups concurrently: 4 workers, previously tested by the maintainer; a
  single SQLite writer; `dgp_cnpq_lib` called as-is. Add retry and back-off on
  `net::ERR_CONNECTION_RESET`: 85/350 groups failed that way in the 2026-10-22
  validation run, after two back-to-back full crawls. Status: Ready.
- **TD-015 — Phase ceilings still ×10**: `src/flows/pipelines/weekly_orchestrator.py`
  carries temporary ×10 timeouts (up to 30 h for a phase). Bring them back to
  ~3× the measured durations once TD-013/TD-014 land. Status: **Fixed** (2026-10-23):
  the ceilings are back to their original values (lattes phases 3600 s, cnpq
  10800 s, …). With specs 015–017 the measured phases are well inside them
  (spec 017 run: cnpq 28 min, lattes_projects 21 min, lattes_advisorships 25 min).
- **TD-016 — `lazy="joined"` on `Team.members` / `TeamMember.person` (`eo_lib`)**:
  the root cause of TD-012 on the library side, in the style of TD-009. Worth
  reporting upstream; the ETL no longer depends on it. Status: Ready (upstream).

## Follow-ups — origin: `specs/016-name-matching-index` (2026-10-22)

- **TD-017 — `RAPIDFUZZ_IMPLEMENTATION=fallback` is not a valid rapidfuzz value**:
  rapidfuzz 3.14.5 recognises only `cpp` and `python`; any other value takes the
  default branch, which loads the AVX2 build. The workaround added to
  `.github/workflows/weekly-etl.yml` by commit `e0d137e` ("disable rapidfuzz
  AVX2 SIMD to prevent segfault in CI") therefore probably has no effect. Fix
  options: `cpp` (which tries AVX2 first, so it would not avoid AVX2 either),
  `python` (pure Python, much slower fuzzy), or another way to force SSE2. Needs
  the maintainer's decision given the segfault history. Status: Ready (decision).
- **TD-018 — SQLite commit latency dominates the remaining Lattes time**: the same
  CVs took ~2.1× longer in the full run (`db/horizon.db` on NVMe ext4) than in
  the replay (tmpfs). A commit costs 3.3 ms vs 0.056 ms, and ingestion commits per
  record. Candidate ETL-side fix: `PRAGMA journal_mode=WAL` +
  `synchronous=NORMAL` via a SQLAlchemy `connect` event. Check that the final
  database is complete for the CI artifact upload (WAL checkpoint on close) and
  that no other process reads the file mid-run. Status: **Fixed** (2026-10-24) by
  spec 018; see the follow-ups below.

## Follow-ups — origin: `specs/017-cnpq-concurrent-sync` (2026-10-22)

- **TD-008 (CNPq part) and TD-014 — Fixed** by spec 017. The CNPq phase fetches
  group pages with 4 concurrent workers (`HORIZON_CNPQ_WORKERS`) through the
  unchanged `dgp_cnpq_lib`, and writes them from a single writer in group order.
  The researcher register is read once per phase. ETL-level retries (3 attempts,
  30 s and 90 s) and a failure-burst rule protect the portal. Replays (N = 4 and
  N = 1) were identical. Full run: CNPq 54.4 → 28.3 min; total 2 h 09 → 1 h 37.
  See `docs/reports/2026-10-22-cnpq-concurrent-validation.md`.
  `sigpesq_excel.py` still calls `get_all()` per researcher name (the other half
  of TD-008); it was not measured as significant.
- **TD-019 — Members without a start date get the run's timestamp**:
  `CnpqSyncLogic.sync_members` stamps "now" when the DGP page has no start date
  (913 memberships in the 2026-10-22 replay). Exports therefore differ between
  runs, even with identical inputs. Decide whether `NULL`, or a stable value,
  would be more correct. Status: Ready (decision).

## Follow-ups — origin: `specs/018-sqlite-wal-journaling` (2026-10-24)

- **TD-018 — Fixed** by spec 018. Every SQLite connection opened through
  `app.py` uses `journal_mode=WAL` and `synchronous=NORMAL`
  (`src/adapters/database/sqlite_settings.py`), and `run_weekly` checkpoints the
  log and returns `db/horizon.db` to the rollback journal after the last phase,
  so the CI artifact is complete on its own. `make db-clean` also removes the
  `-wal`/`-shm` files. Controlled replay of both Lattes phases: identical
  databases, 46.1 → 25.1 min. Full local run: `lattes_projects` 21.1 → 7.4 min,
  `lattes_advisorships` 24.7 → 12.4 min, total 1 h 37 → 1 h 04. See
  `docs/reports/2026-10-24-sqlite-wal-validation.md`.
- **TD-020 — `enrich_projects` fails with `database is locked` in the CI
  weekly**: `ProjectEnrichmentLoader._ingest_new` checks new titles against
  Research Project initiatives only, but `UNIQUE(initiatives.name)` spans every
  type. In the CI inputs a new project has the title of an Advisorship
  (initiative 435), the insert fails inside `_write_row`'s SAVEPOINT, and
  `ROLLBACK TO SAVEPOINT` leaves the SQLite transaction and its write lock open.
  The next `tracking_recorder` write runs on another session and fails after the
  5 s busy timeout. Rows written before the collision are kept (pysqlite commits
  each SAVEPOINT); the new initiatives after it are lost (17 in run
  40002646510). Not fixed by WAL. Two fixes were tested on the CI database
  (compare against all initiative names; end the open transaction after a failed
  row): each completes the phase with identical results. Status: Ready (next
  spec).
- **TD-021 — `assign_team` loads whole object graphs to write one link row**:
  `eo_lib`'s `InitiativeService.assign_team` calls `get_by_id` on the initiative
  and the team, whose `lazy="joined"` relations pull teams, members, persons and
  roles. 416 s, 24% of `lattes_advisorships` in the 2026-10-23 profile (~43 ms
  per call). Same root cause as TD-016. An ETL-side fix would write the
  `initiative_teams` row directly, which needs the maintainer's decision under
  the "do not replace third-party behaviour" rule. Status: Ready (decision).
