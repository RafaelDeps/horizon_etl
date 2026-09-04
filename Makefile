# Horizon ETL automation

SHELL := /bin/sh
.DEFAULT_GOAL := help

PREFECT_HOST ?= 127.0.0.1
PREFECT_PORT ?= 4200
PREFECT_API_URL ?= http://$(PREFECT_HOST):$(PREFECT_PORT)/api
PREFECT_ENV := PREFECT_API_URL=$(PREFECT_API_URL) PREFECT_CLIENT_SERVER_VERSION_CHECK_ENABLED=false

PYTHON_BIN ?= .venv/bin/python
PYTHON_ENV := $(PREFECT_ENV) PYTHONPATH=.
PYTHON := $(PYTHON_ENV) $(PYTHON_BIN)
FLOW_ENV := HORIZON_QUIET_PREFECT=1 PREFECT_LOGGING_TO_API_ENABLED=false
FLOW_PYTHON := $(FLOW_ENV) $(PYTHON)
# Geradores de relatório: scripts puros (sem Prefect/Docker), só precisam do PYTHONPATH.
REPORT_PYTHON := PYTHONPATH=. $(PYTHON_BIN)

CAMPUS ?= Serra
WEEKLY_CAMPUS ?=
OUTPUT_DIR ?= data/exports

DOCKER_BIN ?= $(shell if command -v docker >/dev/null 2>&1; then echo docker; elif command -v flatpak-spawn >/dev/null 2>&1 && flatpak-spawn --host sh -lc 'command -v docker >/dev/null 2>&1'; then echo "flatpak-spawn --host docker"; else echo docker; fi)
DOCKER_COMPOSE_FILE ?= docker-compose.yml
DOCKER_COMPOSE := $(DOCKER_BIN) compose -f $(DOCKER_COMPOSE_FILE)
PREFECT_SERVER_SERVICE ?= server
PREFECT_DB_SERVICE ?= database

.PHONY: help setup logs-dir \
	db-clean db-init db-reset \
	prefect-server prefect-stop prefect-status \
	pipeline pipeline-log weekly-flows full-refresh \
	ingest-sigpesq extract-project-files \
	ingest-lattes-download ingest-lattes-projects ingest-lattes-full \
	sync-cnpq \
	export-canonical export-knowledge-areas-mart export-initiatives-analytics-mart export-people-graph export-collaboration-graph export-researchers-collaboration-graph export-outside-ifes-collaboration-graph export-null-researchers-collaboration-graph export-students-collaboration-graph export-rg-membership-manifest \
	anonymize-backfill anonymize-check \
	test test-coverage lint format format-check ci-check \
	audit-duplicates consolidate-duplicates \
	status clean \
	docker-up docker-stop docker-build \
	docker-pipeline docker-weekly-flows docker-full-refresh \
	docker-ingest-sigpesq docker-sync-cnpq \
	docker-export-canonical \
	docker-db-reset

help: ## Show available commands
	@echo "Horizon ETL commands"
	@echo "===================="
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-34s %s\n", $$1, $$2}'

# --- Setup ---

setup: ## Create venv, install dependencies, and create local folders
	@python3 -m venv .venv
	@$(PYTHON_BIN) -m pip install --upgrade pip
	@$(PYTHON_BIN) -m pip install -r requirements.txt
	@mkdir -p logs data/exports data/reports

logs-dir:
	@mkdir -p logs

# --- Database ---

db-clean: ## Delete the local SQLite database
	@rm -f db/horizon.db

db-init: ## Initialize database schema and base data
	@$(PYTHON) db/create_db.py

db-reset: db-clean db-init ## Recreate the local database from scratch

# --- Prefect Server ---

prefect-server: logs-dir ## Start local Prefect server with Docker Compose
	@if $(DOCKER_COMPOSE) ps --services --status running | grep -qx "$(PREFECT_SERVER_SERVICE)"; then \
		echo "Prefect server already running at $(PREFECT_API_URL)"; \
	else \
		echo "Starting Prefect server at $(PREFECT_API_URL)"; \
		$(DOCKER_COMPOSE) up -d $(PREFECT_DB_SERVICE) $(PREFECT_SERVER_SERVICE); \
		for i in `seq 1 30`; do \
			if curl -fsS "$(PREFECT_API_URL)/health" >/dev/null 2>&1; then \
				echo "Prefect server is ready at $(PREFECT_API_URL)"; \
				exit 0; \
			fi; \
			sleep 1; \
		done; \
		echo "Prefect server did not become ready. Recent logs:"; \
		$(DOCKER_COMPOSE) logs --tail=50 $(PREFECT_SERVER_SERVICE); \
		exit 1; \
	fi

prefect-stop: ## Stop local Prefect server containers
	@if $(DOCKER_COMPOSE) ps --services --status running | grep -Eq "^($(PREFECT_SERVER_SERVICE)|$(PREFECT_DB_SERVICE))$$"; then \
		$(DOCKER_COMPOSE) stop $(PREFECT_SERVER_SERVICE) $(PREFECT_DB_SERVICE); \
	else \
		echo "No Prefect server containers are running"; \
	fi

prefect-status: ## Show local Prefect server status
	@if $(DOCKER_COMPOSE) ps --services --status running | grep -qx "$(PREFECT_SERVER_SERVICE)"; then \
		echo "Prefect server running at $(PREFECT_API_URL)"; \
		$(DOCKER_COMPOSE) ps $(PREFECT_DB_SERVICE) $(PREFECT_SERVER_SERVICE); \
	else \
		echo "Prefect server is not running"; \
	fi

# --- Pipelines ---

pipeline: prefect-server ## Run the unified ingestion pipeline (CAMPUS=Serra)
	@$(FLOW_PYTHON) app.py full_pipeline "$(CAMPUS)" "$(OUTPUT_DIR)"

pipeline-log: prefect-server logs-dir ## Run the unified pipeline and tee output to logs/
	@$(FLOW_PYTHON) app.py full_pipeline "$(CAMPUS)" "$(OUTPUT_DIR)" 2>&1 | tee logs/pipeline_$(CAMPUS)_$$(date +%Y%m%d_%H%M%S).log

full-refresh: db-reset prefect-server ## Reset DB and run full pipeline for all campuses
	@$(FLOW_PYTHON) app.py full_pipeline "" "$(OUTPUT_DIR)"

weekly-flows: db-reset prefect-server ## Reset DB and run weekly source flows plus exports (incl. SigPesq document extraction)
	@HORIZON_PROJECT_FILES_LIMIT="$(PROJECT_FILES_LIMIT)" $(FLOW_PYTHON) app.py weekly "$(WEEKLY_CAMPUS)" "$(OUTPUT_DIR)"

# --- Ingestion ---

ingest-sigpesq: prefect-server ## Ingest all SigPesq reports (groups, projects, advisorships)
	@$(FLOW_PYTHON) app.py sigpesq

# Produz os PJ_*.json que o enrich_projects consome. Também roda dentro do
# weekly-flows (fase extract_project_files, imediatamente antes do
# enrich_projects); este alvo permite rodá-lo sob demanda, quando entrar um
# lote novo de projetos, sem esperar a próxima execução semanal. As duas etapas
# pulam o que já existe, então uma nova execução só paga pelo que falta.
# Exige MISTRAL_KEY no .env.
# Use PROJECT_FILES_LIMIT=5 para um teste barato.
extract-project-files: prefect-server ## Baixa os PDFs dos projetos e extrai PJ_*.json via Mistral (sob demanda)
	@$(FLOW_PYTHON) app.py extract_project_files "$(PROJECT_FILES_LIMIT)"

ingest-lattes-download: prefect-server ## Download Lattes curricula via scriptLattes
	@$(FLOW_PYTHON) -m src.flows.lattes.download

ingest-lattes-projects: prefect-server ## Ingest Lattes projects, articles, and education
	@$(FLOW_PYTHON) -m src.flows.lattes.projects

ingest-lattes-full: prefect-server ## Run complete Lattes ingestion (download + projects + advisorships)
	@$(FLOW_PYTHON) -m src.flows.lattes.complete

sync-cnpq: prefect-server ## Sync CNPq research groups (CAMPUS=Serra)
	@$(FLOW_PYTHON) app.py cnpq_sync "$(CAMPUS)"

# --- Exports ---

export-canonical: prefect-server ## Export all canonical data to OUTPUT_DIR
	@$(FLOW_PYTHON) app.py export_canonical "$(OUTPUT_DIR)" "$(CAMPUS)"

export-knowledge-areas-mart: prefect-server ## Export knowledge areas mart JSON
	@$(FLOW_PYTHON) app.py ka_mart "$(OUTPUT_DIR)/knowledge_areas_mart.json" "$(CAMPUS)"

export-initiatives-analytics-mart: prefect-server ## Export initiatives analytics mart JSON
	@$(FLOW_PYTHON) app.py analytics_mart "$(OUTPUT_DIR)/initiatives_analytics_mart.json"

export-people-graph: prefect-server ## Export people relationship graph JSON
	@$(FLOW_PYTHON) app.py people_graph "$(OUTPUT_DIR)"

export-collaboration-graph: prefect-server ## Export people collaboration graph JSON
	@$(FLOW_PYTHON) app.py collaboration_graph "$(OUTPUT_DIR)"

export-researchers-collaboration-graph: prefect-server ## Export researchers-only collaboration graph JSON
	@$(FLOW_PYTHON) app.py researchers_collaboration_graph "$(OUTPUT_DIR)"

export-outside-ifes-collaboration-graph: prefect-server ## Export outside-IFES collaboration graph JSON
	@$(FLOW_PYTHON) app.py outside_ifes_collaboration_graph "$(OUTPUT_DIR)"

export-null-researchers-collaboration-graph: prefect-server ## Export null-classification collaboration graph JSON
	@$(FLOW_PYTHON) app.py null_researchers_collaboration_graph "$(OUTPUT_DIR)"

export-students-collaboration-graph: prefect-server ## Export students collaboration graph JSON
	@$(FLOW_PYTHON) app.py students_collaboration_graph "$(OUTPUT_DIR)"

export-rg-membership-manifest: prefect-server ## Export research group membership graphs manifest JSON
	@$(FLOW_PYTHON) app.py rg_membership_manifest "$(OUTPUT_DIR)"

# --- Reports ---
# Relatórios HTML/JSON gerados a partir de data/exports (canonical), data/lattes_json
# e das fontes FACTO/FAPES/bolsistas. Não precisam de Prefect nem Docker.

.PHONY: reports report-captacao report-ppcomp-base report-ppcomp-egressos \
	report-formandos report-formandos-exec report-docentes-exec report-institucional

report-captacao: ## Relatório de captação de projetos (FAPES + FACTO)
	@$(REPORT_PYTHON) -m src.scripts.generate_captacao_report

report-ppcomp-base: ## Relatório base analítico do mestrado PPCOMP
	@$(REPORT_PYTHON) -m src.scripts.generate_ppcomp_base_report

report-ppcomp-egressos: ## Relatório de egressos do mestrado PPCOMP
	@$(REPORT_PYTHON) -m src.scripts.generate_ppcomp_egressos_report

report-formandos: ## Relatório consolidado Formandos × Pesquisa (todos os semestres)
	@$(REPORT_PYTHON) -m src.scripts.generate_formandos_report --all

report-formandos-exec: report-formandos ## Relatório executivo de formandos (depende de report-formandos)
	@$(REPORT_PYTHON) -m src.scripts.generate_formandos_executive

report-docentes-exec: ## Relatório executivo de docentes
	@$(REPORT_PYTHON) -m src.scripts.generate_docentes_executive

report-institucional: report-ppcomp-base report-ppcomp-egressos report-formandos ## Relatório institucional (depende de ppcomp + formandos)
	@$(REPORT_PYTHON) -m src.scripts.generate_relatorio_institucional

reports: report-captacao report-ppcomp-base report-ppcomp-egressos report-formandos report-formandos-exec report-docentes-exec report-institucional ## Gera TODOS os relatórios (FACTO/Lattes) na ordem correta
	@echo "Relatórios gerados em $(OUTPUT_DIR) (formandos/, mestrado/, docentes/)."

# --- LGPD ---

anonymize-backfill: ## Anonymize PII (CPF/email) in existing DB records (LGPD — irreversible)
	@$(FLOW_PYTHON) app.py anonymize_backfill

anonymize-check: ## Audit DB for unmasked PII fields
	@$(PYTHON) -c 'from src.flows.maintenance.anonymize_backfill import audit_pii; audit_pii()'

# --- Quality ---

test: prefect-server ## Run all tests
	@$(PYTHON) -m pytest -q

test-coverage: prefect-server ## Run tests with HTML coverage report
	@$(PYTHON) -m pytest --cov=src --cov-report=html --cov-report=term

lint: ## Run flake8
	@$(PYTHON) -m flake8 src tests

format: ## Format code with black and isort
	@$(PYTHON) -m black src tests
	@$(PYTHON) -m isort src tests

format-check: ## Check formatting without modifying files
	@$(PYTHON) -m black --check src tests
	@$(PYTHON) -m isort --check src tests

ci-check: format-check lint test ## Run all CI checks

# --- Data Quality ---

audit-duplicates: ## Audit duplicate candidates in the database
	@$(PYTHON) src/scripts/audit_duplicates.py

consolidate-duplicates: ## Consolidate duplicate persons, teams, and knowledge areas
	@$(PYTHON) src/scripts/consolidate_duplicates.py --entity all

# --- Docker ---

docker-up: ## Start Prefect DB + server in Docker (required before docker-* pipeline targets)
	@mkdir -p db data/exports data/lattes_json data/raw/sigpesq cache logs
	@if $(DOCKER_COMPOSE) ps --services --status running | grep -qx "$(PREFECT_SERVER_SERVICE)"; then \
		echo "Prefect server already running at $(PREFECT_API_URL)"; \
	else \
		echo "Starting Prefect server via Docker..."; \
		$(DOCKER_COMPOSE) up -d $(PREFECT_DB_SERVICE) $(PREFECT_SERVER_SERVICE); \
		for i in `seq 1 30`; do \
			if curl -fsS "http://127.0.0.1:$(PREFECT_PORT)/api/health" >/dev/null 2>&1; then \
				echo "Prefect server ready at http://127.0.0.1:$(PREFECT_PORT)"; \
				exit 0; \
			fi; \
			sleep 2; \
		done; \
		echo "Prefect server did not become ready."; \
		$(DOCKER_COMPOSE) logs --tail=30 $(PREFECT_SERVER_SERVICE); \
		exit 1; \
	fi

docker-stop: ## Stop all Docker services
	@$(DOCKER_COMPOSE) stop

docker-build: ## Build the ETL app Docker image
	@$(DOCKER_COMPOSE) build app

docker-pipeline: docker-up ## Run full pipeline in Docker (CAMPUS=Serra)
	@$(DOCKER_COMPOSE) run --rm --no-deps app app.py full_pipeline "$(CAMPUS)" "$(OUTPUT_DIR)"

docker-weekly-flows: docker-up ## Run weekly flows in Docker
	@$(DOCKER_COMPOSE) run --rm --no-deps app app.py weekly "$(WEEKLY_CAMPUS)" "$(OUTPUT_DIR)"

docker-db-reset: ## Reset the ETL database inside Docker
	@$(DOCKER_COMPOSE) run --rm --no-deps app db/create_db.py

docker-full-refresh: docker-db-reset docker-up ## Reset DB and run all sources in Docker
	@$(DOCKER_COMPOSE) run --rm --no-deps app

docker-ingest-sigpesq: docker-up ## Ingest SigPesq in Docker
	@$(DOCKER_COMPOSE) run --rm --no-deps app app.py sigpesq

docker-sync-cnpq: docker-up ## Sync CNPq groups in Docker (CAMPUS=Serra)
	@$(DOCKER_COMPOSE) run --rm --no-deps app app.py cnpq_sync "$(CAMPUS)"

docker-export-canonical: docker-up ## Export canonical data in Docker
	@$(DOCKER_COMPOSE) run --rm --no-deps app app.py export_canonical "$(OUTPUT_DIR)" "$(CAMPUS)"

# --- Utilities ---

status: ## Show database and export status
	@echo "Database:"
	@ls -lh db/horizon.db 2>/dev/null || echo "  not initialized"
	@echo "Exports:"
	@ls -lh $(OUTPUT_DIR)/*.json 2>/dev/null | wc -l | xargs -I {} echo "  {} files exported"
	@echo "Last pipeline log:"
	@ls -lt logs/pipeline_*.log 2>/dev/null | head -1 || echo "  no logs found"

clean: db-clean ## Remove database, caches, and compiled files
	@rm -rf .pytest_cache .coverage htmlcov
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
