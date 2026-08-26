# Quickstart — Verificando a correção

**Feature**: `004-fix-enrichment-transaction`

Roteiro curto para reproduzir o defeito, validar a correção e conferir os portões
de qualidade. Tudo roda no `.venv` do projeto, sem Docker e sem insumos externos
ao repositório.

---

## 1. Reproduzir o defeito (antes da correção)

O defeito é determinístico e não precisa de dados. Reprodução mínima do
comportamento do SQLAlchemy que o causa:

```bash
PYTHONPATH=. .venv/bin/python -c "from sqlalchemy import create_engine, text; from sqlalchemy.orm import Session; s = Session(create_engine('sqlite:///:memory:')); s.execute(text('SELECT 1')); print('em transação:', s.in_transaction()); s.begin()"
```

Esperado: `em transação: True` seguido de
`InvalidRequestError: A transaction is already begun on this Session.`

Evidência do defeito na execução real registrada no banco atual:

```bash
PYTHONPATH=. .venv/bin/python -c "from sqlalchemy import create_engine, text; e = create_engine('sqlite:///db/horizon.db'); c = e.connect(); print(c.execute(text(\"SELECT status, notes FROM ingestion_runs WHERE source_system='sigpesq_project_files'\")).fetchall()); print('enriquecidas:', c.execute(text('SELECT COUNT(*) FROM initiatives WHERE enrichment_json IS NOT NULL')).scalar())"
```

Esperado hoje: uma linha `failed` com a mensagem da exceção, e `enriquecidas: 0`.

---

## 2. Rodar o teste de regressão

As ferramentas de desenvolvimento **não** estão no `requirements.txt` — o CI as
instala à parte. Num venv recém-criado, instale primeiro, com as mesmas versões
fixadas em `.github/workflows/ci.yml`:

```bash
.venv/bin/pip install pytest pytest-mock flake8 black==24.10.0 isort==5.13.2
```

```bash
.venv/bin/python -m pytest tests/test_project_enrichment_db.py -v
```

O teste monta um SQLite em memória e cria os documentos de entrada em `tmp_path`.
Não requer banco do projeto, servidor Prefect, rede ou Docker.

Para confirmar que ele realmente protege contra a regressão: reverta a correção em
`src/core/logic/project_enrichment.py`, rode o teste (deve falhar apontando
`InvalidRequestError`), e reaplique.

---

## 3. Rodar a suíte completa

```bash
.venv/bin/python -m pytest -q
```

---

## 4. Portão de qualidade

O alvo `make ci-check` expande para `format-check lint test`, mas roda black,
isort e flake8 sobre **todo** o repositório — e o repositório está longe disso
hoje (58 arquivos seriam reformatados por black, muitos apontamentos de isort e
flake8, todos preexistentes). O alvo, portanto, não passa e não é o portão real.

O portão real é o do CI (`.github/workflows/ci.yml`), que verifica formatação
apenas nos **arquivos alterados** e roda flake8 restrito a erros graves. Para
reproduzi-lo sobre esta mudança:

```bash
.venv/bin/python -m black --check src/core/logic/project_enrichment.py tests/test_project_enrichment_db.py tests/test_project_enrichment.py
```

```bash
.venv/bin/python -m isort --check src/core/logic/project_enrichment.py tests/test_project_enrichment_db.py tests/test_project_enrichment.py
```

```bash
.venv/bin/python -m flake8 . --count --select=E9,F63,F7,F82
```

E a suíte completa:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

Referência medida nesta branch: **235 passando, 6 falhando**. As 6 falhas são
preexistentes e alheias a esta correção (`test_download_lattes_flow` ×3,
`test_export_canonical_data_flow`, `test_loader_mapping`, `test_sigpesq_adapter`).

---

## 5. Executar a fase de verdade (opcional)

Requer o servidor Prefect no ar (`make prefect-server`). **As variáveis de
ambiente são obrigatórias**: o `app.py` chama `load_dotenv()` depois dos imports,
então o Prefect já foi importado sem enxergar `PREFECT_API_URL` do `.env` e tenta
subir um servidor temporário, que falha. O Makefile injeta as variáveis antes do
Python subir — por isso o comando abaixo as replica:

```bash
HORIZON_QUIET_PREFECT=1 PREFECT_LOGGING_TO_API_ENABLED=false PREFECT_API_URL=http://127.0.0.1:4200/api PREFECT_CLIENT_SERVER_VERSION_CHECK_ENABLED=false PYTHONPATH=. .venv/bin/python app.py enrich_projects
```

**Resultado esperado no ambiente atual**: conclusão com sucesso relatando **zero
documentos processados**, porque o diretório `data/exports/project_sigpesq_files_json`
não existe neste repositório. Isso é o comportamento correto para esta branch — a
origem dos documentos é assunto separado, registrado nas premissas da
especificação. Enquanto os documentos não existirem, a validação de ponta a ponta
do enriquecimento é feita pelo teste do passo 2.

---

## Fora deste roteiro

Reconstrução da imagem Docker, atualização da biblioteca de coleta do SigPesq e
geração dos documentos de projeto não fazem parte desta branch.
