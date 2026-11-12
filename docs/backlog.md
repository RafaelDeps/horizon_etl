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
  row): each completes the phase with identical results. Status: **Fixed**
  (2026-10-24) by spec 019, with both fixes. On the CI database the phase now
  ends with exit 0: 251 enriched, 17 created, 0 errors, 1 duplicate skipped. On
  a local database without collisions the output is identical to the old code.
  See `docs/reports/2026-10-24-enrich-lock-validation.md`.
- **TD-021 — `assign_team` loads whole object graphs to write one link row**:
  `eo_lib`'s `InitiativeService.assign_team` calls `get_by_id` on the initiative
  and the team, whose `lazy="joined"` relations pull teams, members, persons and
  roles. 416 s, 24% of `lattes_advisorships` in the 2026-10-23 profile (~43 ms
  per call). Same root cause as TD-016. An ETL-side fix would write the
  `initiative_teams` row directly, which needs the maintainer's decision under
  the "do not replace third-party behaviour" rule. Status: Ready (decision).

## Follow-ups — origin: `specs/020-horizon-id-idempotent-hash` (2026-10-27)

- **TD-022 — 27 Lattes CVs collapse into one "[Nome-nao-identificado]"
  person**: for 27 of the 435 CVs in `data/lattes_json/`, scriptLattes could not
  read the name and writes `[Nome-nao-identificado]` (files
  `NNN_Nome-nao-identificado_<lattes_id>.json`). The Lattes phases resolved all
  27 to the same person (id 7185 in the 2026-10-24 database). Every one of the
  27 `lattes_id` values is in `data/lattes_run/lattes.list` with the real name
  (for example 0418477486525610 Felipe Sellin, 3943417292642301 Anderson
  Mathias Holtz).
  **Corrected on 2026-11-03**: the content was not real. The 27 files in
  `cache/` (18–24 KB, dated 2026-10-21) were the portal's reCAPTCHA access
  check page, saved before spec 023 started rejecting it, and the JSON built
  from them had 0 items in every section. Taking the name from `lattes.list`
  would only have named an empty CV. The case is already handled:
  - spec 021 fails an unidentified CV (`read_cv`) instead of ingesting it;
  - spec 023 rejects the access check page (`is_curriculum_page`) and
    downloads an unidentified CV again on the next run (`retry_unidentified`);
  - spec 025 asks for a rejected curriculum again in the same run.

  A local run from scratch on 2026-11-03 got the real curriculum for 24 of the
  27; the other 3 got the access check page again, and no
  `Nome-nao-identificado` person is left in the database. Status: Done (no
  fix needed beyond specs 021, 023 and 025).
- **TD-023 — 149 groups of duplicate rows found by the horizon_id rules**: when
  two rows of the same type derive the same `horizon_id`, the assigner adds a
  collision suffix (`~<hex6>` of the source file name, then `~2`, `~3`). On the
  2026-10-24 database this happens in 149 groups: articles 73, professional
  activities 53, productions 8, knowledge areas 7, fellowships 4, research
  groups 2, academic educations 2. All are the same item stored twice in the
  database, differing only by case or accent of a name or title (examples in
  `specs/020-horizon-id-idempotent-hash/research.md`, R2). The ids are stable,
  but each pair is one real item with two ids. Candidate for a deduplication
  spec, which would turn the extra id of each pair into a `merge` alias.
  Status: Ready.
- **TD-024 — Person resolution in a fresh run depends on the order persons are
  created**: `PersonMatcher` compares a name only with the persons that exist
  at that point of the run. Example (spec 020, research R9.3): one CV resolved
  "Ciro Alexandre Torres Alves" to person 7710 because the researcher "Ciro
  Alexandre Alves Torres" (11030) was created later in the run; on a populated
  database the same CV resolves to 11030. Spec 020 made the order fixed (CVs
  sorted, deterministic fuzzy tie-break), so two rebuilds agree and reruns reach
  a fixpoint, but a rebuild and an incremental database can still attach a few
  rows to a different person, and the name spelling kept for a person can change
  (695 → 714 rows in `null_researchers_canonical.json` between the old and new
  code). A fix would resolve names against the full set of known names before
  writing (two passes). Status: Ready (design).
- **TD-025 — `PersonConsolidator` talks to the database directly from the core**:
  `src/core/logic/person_consolidator.py` opens `sqlite3` connections and, since
  spec 020, imports `record_merge` from `src/adapters/database/horizon_id_store.py`.
  Constitution principle I asks that `src/core/logic/` reach the database only
  through ports and never import adapters. Found by `/speckit-analyze` of spec
  021 (2026-10-28), which avoids widening it: its merge re-pointing is injected
  as a hook by the flow. A fix would move the consolidator's SQL behind a port
  (a `IPersonMergeStore` with a SQLite adapter) and inject the spec 020 merge
  log the same way. Status: Ready.
- **TD-026 — Some phases ignore `DATABASE_URL` and always open `db/horizon.db`**:
  `src/scripts/consolidate_duplicates.py` (`DEFAULT_DB_PATH`), `PersonConsolidator`,
  `ReferenceConsolidator`, `DuplicateAuditor`, `anonymize_backfill` and
  `etl_flow_reporter` default to the relative path `db/horizon.db`, and `app.py`
  calls them without a path. Run from another folder they open an empty file
  there; run from the repository root with `DATABASE_URL` pointing at a copy,
  `consolidate_duplicates` and `anonymize_backfill` write the real database.
  Found in the spec 021 replay (2026-10-28). Not fixed there: the maintainer
  allowed the local validation to write `db/horizon.db` after a backup
  (`data/_backup_2026-10-28_pre021/`). A fix would resolve the path from
  `DATABASE_URL` as `sqlite_path_from_url` already does. Status: Ready.
- **TD-027 — Two SigPesq workplans of one project collapse into one advisorship**:
  rows with different workplan codes of the same project (e.g.
  `sigpesq workplan|5475|2144` and `sigpesq workplan|5475|2320`, different
  students) are resolved by `AdvisorshipHandler` to the same advisorship, so one
  student is lost and the advisorship keeps whichever row was written last.
  Found by the spec 021 replay (2026-10-28): 67 advisorships. With spec 021 a
  row repeated with identical content in a later yearly file is skipped, so the
  winner became the last distinct version (deterministic, the same in a rebuild
  and an incremental run, but different from the previous last-writer for those
  67). A fix would key the advisorship by its workplan code so both rows become
  two advisorships. Status: Ready.

- **TD-028 — Rows shared by several documents keep the last writer's values**:
  an initiative listed in several Lattes CVs or SigPesq rows, and a fellowship
  shared by several workplans, take the description, status, dates (and the
  fellowship value) of whichever document wrote them last. A rebuild writes in
  a fixed order, so it is deterministic; an incremental run reprocesses only
  some documents, so the last writer can differ. Found by the spec 021 replay
  (2026-10-29): after a rebuild plus two unchanged passes, about 130
  initiatives (description 50, status 27, start date 26, end date 18,
  `enrichment_json` 38) and 5 advisorships differ from the rebuild, while
  every other table is identical. It stays stable afterwards (passes 3+ write
  nothing). A fix would merge these values by a rule that does not depend on
  order, as spec 020 did for article fields (`_fill_missing_article_fields`):
  for example the most recent source date, or the value of the highest-priority
  source. Status: Done (branch 030). Every document records a claim for each
  shared field in `source_field_claims`, and the winner is picked from all the
  claims by a fixed rule: most recent CV date first, then Lattes > SigPesq >
  CNPq, then the lowest Lattes id / highest SigPesq Id
  (`src/core/logic/field_merge.py`).

- **TD-029 — A Lattes project whose title collides with another initiative's
  name fails its whole CV**: on the 2026-10-29 CI run 40952053776, CV
  `1703547133505721` failed as `partial` with `UNIQUE constraint failed:
  initiatives.name`. One of its projects resolved to no existing initiative,
  but its title equals the stored name of another one. Before spec 021 the
  row was lost silently (`PERDIDO por erro`). Now the whole CV is rolled
  back, keeps its previous data, and is tried again every run. A fix would
  resolve such a project to the existing initiative of that name (the loader
  already does it for names that differ only in spelling,
  `_process_row`). Status: Done (branch 030). The reproduction on the run's
  database showed 6 project titles held by advisorships of the same
  researcher. The project now keeps the title and the advisorship gets the
  disambiguated title a rebuild gives it ("<title> | Orientacao <student> |
  <year>").

## Follow-ups — origin: `specs/024-portal-early-stop` (2026-10-30)

- **TD-030 — A CNPq navigation that hangs past the library's timeout still
  holds the phase**: spec 024 stops new requests once the portal is given up,
  but it lets the attempts already in flight end on their own. In every log
  so far, an attempt on a hung portal ended in about 95 s: the library's 3
  navigations of 30 s. A navigation that ignored that timeout would keep the
  phase until the orchestrator's 10,800 s limit, and the phase would write
  nothing, as in run 40966298828. Closing the browser of an attempt in flight
  would need a change in `dgp_cnpq_lib`, which stays unchanged. Status:
  Watch (no occurrence).

## Follow-ups — origin: branch `030-deterministic-field-merge` (2026-11-05)

- **TD-031 — Six tests are out of date with the code**: they failed before
  branch 028 (spec 025). The program was right in each case; the tests
  expected an old behaviour. Fixed on branch `fix-stale-tests`:
  - `test_download_lattes_flow.py`: the two runtime tests checked the
    chromedriver and Chrome versions, but scriptLattes now runs on Playwright.
    They now check the Playwright Chromium check, and the unused version
    helpers were removed from `src/flows/lattes/download.py`. The flow test
    now fakes the spec 023 rotation and the one-argument scriptLattes call;
  - `test_loader_mapping.py::test_research_group_loader_mapping`: SigPesq
    leader e-mails are pseudonymized (LGPD), so it expects the pseudonym and
    no `identification_id`;
  - `test_sigpesq_adapter.py::test_sigpesq_adapter_logs_http_429_during_login`:
    compares the 429 message without case;
  - `test_weekly_etl_workflow.py`: expects the current cron `"0 2 * * 6"`.

  Status: Done (2026-11-09; full suite 1027 passed).

- **TD-032 — `lattes_projects` slows down CV after CV on a database without
  SigPesq data**: on 2026-11-06 the SigPesq login failed (Infisical 401), so
  the rebuild had no SigPesq groups or researchers, and CNPq had no groups to
  sync. `lattes_projects` then took 3.9 s for CV 1 and 35.6 s for CV 206, and
  hit its 3,600 s limit at CV 258 of 435. The rebuild of 2026-11-03, with
  SigPesq first, took 416 s for 397 CVs. The same 150 CVs on an empty database
  behave the same with the code of 2026-11-03 (`eeeda3c`), with branch 029
  alone and with branch 030 (762 s, 786 s and 509 s), so no recent change
  causes it. It comes from resolving each CV's people against every
  researcher created so far (`researcher_resolution`, `_score_candidate`).
  A weekly with the SigPesq data does not show it. Status: Watch.

The replay of branch 030 (2026-11-06) compared the incremental database with
a rebuild from the same inputs. The four merged fields and `cancelled` agree;
these differences remain, none of them in a field the merge decides:

- **TD-033 — The enrichment records how a PDF matched, and that changes after
  the first run**: 37 initiatives created from a project PDF keep
  `match_strategy = new_from_document` in a rebuild, but `title_exact` in the
  incremental database, because the next run finds the initiative it created
  by title. The values of the initiative are the same; only the
  `enrichment_json` note differs. Keep the first strategy, or leave the note
  out of the comparison. The second run also rewrote those notes and logged a
  change for each over unchanged inputs. Fixed by spec 032
  (`032-stable-enrichment-strategy`): when the document that created an
  initiative (same code, or same file without a code) matches it again by
  title, the note keeps `new_from_document`; a code match or another document
  records its own strategy, and `entity_matches` keeps the real match of each
  run. Notes that already drifted are repaired by the next run. An unchanged
  note is no longer rewritten. Validated on the fork on 2026-11-10 (rebuild,
  then restored run: 34 notes kept `new_from_document`, 0 of 267 notes
  changed). Status: Done (2026-11-09).
- **TD-034 — A duplicate fellowship in the incremental database**: two
  fellowships "JTC" with value 0 exist in the incremental database
  (`fellowship:jtc:0~e3b0c4` and `~2`), one in the rebuild, and one
  advisorship points to the copy. Find which run created the second one.
  Status: Investigate.
- **TD-035 — `recalculate_parent_projects` only extends a parent's dates**:
  it moves the start earlier and the end later, never back. A parent keeps a
  date from an earlier state once a child changes or leaves (parent 288: end
  2022 incremental, 2021 rebuild). A document that claims the parent's dates
  also sets them before the recalculation runs again, so the row is written
  twice in that weekly. Decide with the maintainer which rule sets a parent's
  dates and status: its sources (the merge) or its children. Status:
  Decision needed.
- **TD-036 — Two isolated identity differences**: initiative 289 points to
  another parent (`initiative:sigpesq-pj:5991` incremental,
  `initiative:lattes:h:94a88523e758` rebuild), and the advisorship "A dimensão
  Ambiental na Educação: perspectiva e desafios da sustentabilidade" (2016)
  has another horizon id (`advisorship:h:fb16cfe336dd` incremental,
  `advisorship:lattes:h:b2d5d5635c9f` rebuild). Not investigated yet.
  Status: Investigate.
- **TD-037 — A replaced student shares the advisorship of the cancelled one**:
  when a SigPesq workplan changes student, the cancelled row and the new row
  (e.g. workplan PT 8732, Ids 3961 and 4145) write the same advisorship.
  Branch 030 makes the result fixed (the highest Id decides `cancelled`), but
  the two students may deserve two advisorships. Decided on 2026-11-11: each
  student has an advisorship. Fixed by branch 035 (see TD-043).
  Status: Implemented (2026-11-11); validation pending.
- **TD-038 — A project PDF is matched to an advisorship with the same title**:
  the enrichment looks for a research project by title and finds an
  advisorship (a student's workplan) whose title is the same as the project's
  (PJ 2449 -> advisorship 140, PJ 3879 -> advisorship 170). The project's note
  and description are written on the advisorship; 4 advisorships carry a
  project note on the local database of 2026-11-10. The description is then
  written twice in every run: the advisorship flow sets "Programa: ..." and
  the enrichment sets the PDF text back, because the two claims are stored
  under different entity types (`advisorship` and `initiative`) for the same
  row and the merge of branch 030 never compares them. The final value is the
  same in every run, but 2 changes are logged over unchanged inputs (found in
  the spec 032 fork runs, reproduced locally). A project PDF should only match
  a research project, and the claims of one row should be merged together.
  Not checked on main. Status: Investigate.
- **TD-039 — A value that is not a DOI merges different articles**: the DOI
  field of a Lattes article sometimes holds a Scopus link without a DOI
  (`...citedby.url?...&doi=null&md5=...`) or an ISSN, and any text was taken
  for a DOI, so every work with the same text became one article. On the
  from-scratch run of 2026-11-10 (435 curricula): 110 curriculum items
  attached to an article with another title, 69 works hidden inside 2
  articles, 45 articles storing a value that is not a DOI; also on main (97
  items) and branch 022 (85). Fixed by spec 033 (`033-valid-doi-matching`):
  `normalize_doi` is the single rule and returns a DOI only for a value in DOI
  form, after taking the DOI out of a `doi=` link parameter and removing the
  doi.org address, spaces and trailing punctuation; anything else is no DOI
  and the item is matched by title and year. The article stores the bare DOI
  (`10.xxxx/...`); the raw value stays in the source record. The identity rule
  version is 3, so a database written before is rebuilt once. Journal and
  conference items with the same title and year becoming one article (47
  cases) is a separate defect, still open. Status: Implemented (2026-11-10);
  local rebuild validated the same day (0 stored values that are not DOIs,
  articles 7,979 to 8,053, the two old ids kept as retired aliases); second
  local run wrote no article change; validated on the fork on 2026-11-11
  (two runs, the second over the restored database, no article change). Done.
- **TD-040 — Different professional activities stored as one, and institution
  fields swapped**: two defects in the professional activities of a Lattes
  curriculum. (1) An activity was taken for a repeat when the researcher, the
  institution and the start year were the same, so the first item was kept and
  the others dropped. (2) The curriculum data arrives with the institution
  text cut at every comma, so a name with commas gave a wrong name, acronym
  and country ("Instituto Federal de Educação" / "Ciência e Tecnologia do
  Espírito Santo" / "IFES"). Measured on 2026-11-11 over 435 curricula: 13,420
  items with an institution, 7,855 rows, 2,923 different activities dropped,
  2,260 rows with "IFES" as the country. Fixed by spec 034
  (`034-keep-professional-activities`): an item is a repeat only when it
  equals a stored activity of the researcher in every stored field; name,
  acronym and country are read from the full institution text, from the end
  (`src/core/logic/professional_activity_rules.py`). An item that carries only
  the institution is stored only when the curriculum has no filled activity at
  that institution (clarification of 2026-11-11). The permanent id hashes the
  full institution text and the fields that tell two activities apart, and
  keeps the old id as a candidate, so an old id that one activity owns becomes
  its alias and the others are recorded as retired. The identity rule version
  is 4, so a database written before is rebuilt once. Expected after the
  rebuild: about 9,555 rows. Status: Implemented (2026-11-11); local rebuild
  validated the same day (9,555 rows, 0 curriculum items missing, 0 rows with
  an acronym as the country, 5,871 old ids kept as aliases and 1,984 retired);
  the second local run changed no activity of an unchanged curriculum. Fork
  validation deferred to the end of the batch (with the next branch).
- **TD-041 — Tasks and courses of a professional activity are not stored**:
  3,580 activity items of the curricula carry a list of tasks (`atividades`,
  for example "Direção e administração, IFES, Campus Colati, Regime:
  Dedicação exclusiva.") and 54 carry a list of courses taught (`disciplinas`).
  The parser ignores both and the `professional_activities` table of the
  domain library has no column for them. Needs a field in `research-domain`
  first. Status: Ready.
- **TD-042 — Institution texts that arrive already cut**: 480 activity items
  arrive with the institution text cut by the third-party curriculum library
  ("Universidade Federal de", "Prefeitura Municipal de"), and some acronyms
  arrive cut too ("MULTI", "E"). The missing part is not in the
  curriculum JSON, so it cannot be recovered in the ETL; the text is stored as
  it arrives. Status: Open, depends on the library.
- **TD-043 — Advisorships of different students with the same title stored as
  one**: an advisorship item whose title equals a stored advisorship's title
  was written over it whatever the student, and the student was replaced.
  Two causes: the loader kept, per title, the last advisorship written, and
  the source identity of an advisorship lives only in memory, so in a later
  run a changed curriculum or SigPesq report is matched by title alone.
  Measured on the local database of 2026-11-11: 10,260 advisorships for
  11,532 Lattes items and 705 SigPesq rows; "Estágio Supervisionado
  Obrigatório" was one advisorship fed by 49 items of different students.
  Fixed by branch 035 (`035-one-advisorship-per-student`): an item is a stored
  advisorship of the same title only for the same student (same person or
  same name) and when their years share a year or one side has none
  (`src/core/logic/advisorship_matching.py`); otherwise it is a new
  advisorship under the existing distinct name. A matched advisorship keeps
  its stored name. The identity rule version is 5, so a database written
  before is rebuilt once; the id rules are unchanged. Expected after the
  rebuild: about 11,890 advisorships. Status: Implemented (2026-11-11);
  local and fork validation pending.
- **TD-044 — Advisorship names carry a "| Orientacao ..." suffix**: two
  initiatives cannot share a name (unique index of the domain library), so
  every advisorship after the first of a title is stored as
  `<title> | Orientacao <student> | <year> | sigpesq <Id>` and the exports
  show that name (652 advisorships before branch 035, more after it).
  Removing the suffix needs the unique-name rule of the library to change or
  a separate display title. Status: Open, depends on the library.
- **TD-045 — The source identity of an initiative is not stored**: the loader
  sets `metadata["source_identity"]` on the object, but the `initiatives`
  table has no column for it, so an initiative read from the database is
  identified by its name. Branch 035 works around it for advisorships
  (student and years). Projects are still matched by name across runs.
  Status: Open, depends on the library.
- **TD-046 — Limits of the advisorship rule of branch 035**: (a) for 7
  (title, student) pairs present in SigPesq and in Lattes with more than one
  Lattes year, the result can depend on which source was stored first (the
  weekly always loads SigPesq first, so a rebuild and an incremental run
  agree unless the SigPesq row first appears in a later report); (b) 11
  (title, student) pairs listed by the advisor and by the co-advisor with
  different years become two advisorships; (c) a student spelled differently
  in two curricula gives two advisorships; (d) 6 items are attached to an
  advisorship whose title is written with other case or punctuation, and 2 to
  an advisorship with a twin created before two persons were merged; when
  their curriculum is processed again the advisorship can be removed and
  created again. Status: Open, accepted.
- **TD-047 — An advisorship keeps one supervisor, the last curriculum read**:
  the same work listed by the advisor and by the co-advisor is one
  advisorship with one Supervisor member, and each curriculum writes its
  owner there. When one of the curricula is processed again the supervisor
  changes: 44 advisorships between the two local runs of branch 035, 61
  between the two runs of branch 034; 132 advisorships are fed by more than
  one curriculum. The co-advisor is not stored as such. Status: Open.
- **TD-048 — A fellowship with value 0 and no sponsor is stored again by a
  second run**: seen on 2026-11-11/12 in the local runs of branches 034
  and 035 and in the fork runs of branch 035: the fellowship "JTC" (value 0, no sponsor) gets a
  second row in the second run (ids 15 and 21), one advisorship moves to the
  new row, and the collision suffix of that fellowship id changes. One
  fellowship of 21; no advisorship is lost. Cause not investigated. Status:
  Open.
