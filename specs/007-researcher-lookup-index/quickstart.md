# Quickstart: validar a feature 007

**Feature**: 007-researcher-lookup-index | **Data**: 2026-08-27

## Regra de ouro

Toda validação de desempenho roda contra **cópia** do banco, nunca contra
`db/horizon.db`. As fases gravam, e comparar "antes e depois" exige o mesmo ponto
de partida nos dois lados.

```bash
mkdir -p /tmp/horizon-bench && cp db/horizon.db /tmp/horizon-bench/antes.db
```

## 1. Testes

```bash
.venv/bin/python -m pytest tests/test_researcher_lookup_index.py tests/test_ingest_lattes_projects_flow.py tests/test_person_matcher.py tests/test_researcher_creation.py -q
```

## 2. Equivalência da correspondência (SC-002)

O critério é: para os 112 currículos, o pesquisador escolhido é o mesmo de antes.
A verificação compara a escolha feita sobre o índice com a escolha feita sobre as
entidades ORM, no mesmo banco, sem gravar nada.

```bash
DATABASE_URL=sqlite:////tmp/horizon-bench/antes.db .venv/bin/python -m pytest tests/test_researcher_lookup_index.py -q -k equivalencia
```

## 3. Desempenho das fases (SC-001)

```bash
cp db/horizon.db /tmp/horizon-bench/fase.db
DATABASE_URL=sqlite:////tmp/horizon-bench/fase.db .venv/bin/python app.py lattes_advisorships
```

Referências medidas em 27/08/2026, mesmo conjunto (112 currículos, 1060
pesquisadores):

| Fase | Antes | Alvo |
|---|---|---|
| `lattes_advisorships` | 1424,6 s | < 600 s |
| `lattes_projects` | 1165,2 s | < 400 s |
| **Soma** | **2589,8 s** | **< 900 s** (SC-001: < 15 min) |

## 4. Contagens inalteradas (SC-003, SC-004)

Rodar a fase nas duas versões, partindo de cópias idênticas do banco, e comparar:

```bash
.venv/bin/python - <<'PY'
import sqlite3, sys
def contagens(p):
    c = sqlite3.connect(p)
    tabelas = ("researchers", "persons", "advisorships", "advisorship_members",
               "articles", "article_authors", "academic_educations", "awards",
               "proficiencies", "professional_activities", "research_productions",
               "production_authors", "entity_matches", "source_records")
    return {t: c.execute(f"select count(*) from {t}").fetchone()[0] for t in tabelas}
a, b = contagens(sys.argv[1]), contagens(sys.argv[2])
for t in a:
    marca = "OK " if a[t] == b[t] else "DIFERE"
    print(f"{marca} {t:28s} antes={a[t]:7d} depois={b[t]:7d}")
PY
```

Qualquer linha `DIFERE` reprova SC-003/SC-004.

## 5. Qualidade

```bash
.venv/bin/python -m black --check src/core/logic/researcher_resolution.py src/flows/lattes/projects.py src/flows/lattes/advisorships.py
```
