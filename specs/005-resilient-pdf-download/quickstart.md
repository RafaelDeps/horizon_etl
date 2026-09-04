# Quickstart — Verificando a descoberta resiliente

**Feature**: `005-resilient-pdf-download`

## 1. Testes offline (não tocam o portal)

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_project_files_strategy.py -v
```

Cobre os quatro cenários com páginas locais. Sem rede, sem login, sem consumir
tentativas de acesso ao SigPesq.

## 2. Suíte completa

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

Referência da branch anterior: **235 passando, 6 falhando** (as 6 são
preexistentes e alheias a este trabalho).

## 3. Formatação e lint dos arquivos tocados

```bash
.venv/bin/python -m black --check src/adapters/sources/sigpesq/project_files_strategy.py src/adapters/sources/sigpesq/project_files.py src/flows/sigpesq/project_files.py tests/test_project_files_strategy.py
```

## 4. Execução real (quando o portal liberar)

```bash
make extract-project-files PROJECT_FILES_LIMIT=30
```

**Como ler o resumo** — é ele que encerra o diagnóstico em aberto:

- `downloaded > 0` → os anexos continuam no portal e a correção resolveu
- `unrecognized > 0` e `downloaded = 0` → ainda há incompatibilidade a cobrir
- tudo em `no_attachment`, `unrecognized = 0` → os anexos foram removidos do portal

Use um limite generoso (30+) para alcançar projetos antigos: os do topo da
relação são os mais recentes e concentram rascunhos.

**Atenção ao limite de acesso**: o portal recusa login após poucas tentativas
seguidas. Espaçe as execuções.
