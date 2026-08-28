# Quickstart: validar a proteção

**Feature**: 008-guard-participant-merge | **Data**: 2026-08-28

## 1. Rodar os testes

```bash
.venv/bin/python -m pytest tests/test_project_loader_matching.py -v
```

Esperado: todos passam, em menos de 5 segundos.

## 2. O experimento que dá sentido à feature

Um teste de regressão que nunca foi visto reprovando não prova nada. Antes de
considerar a feature pronta, **desfaça a proteção e confirme que a suíte grita**.

Em `src/core/logic/project_loader.py`, dentro de `_resolve_existing_initiative`,
comente a guarda que impede orientações de casarem por nome normalizado:

```python
        # if model_class is Advisorship:
        #     return None
```

Rode de novo:

```bash
.venv/bin/python -m pytest tests/test_project_loader_matching.py -v
```

**Esperado: reprovar.** Se passar, os testes são decorativos e precisam ser
refeitos — foi exatamente esse o estado dos 283 testes que deixaram o defeito
entrar em produção.

Restaure a guarda e confirme que volta a passar:

```bash
git diff src/core/logic/project_loader.py
```

Não deve haver diferença nenhuma ao final.

## 3. Suíte completa, para garantir que nada mais mudou

```bash
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration
```

Esperado: mesmo resultado de antes da feature — 277 passando e as 6 falhas
pré-existentes (Chrome/chromedriver, export canonical, loader mapping, adaptador
SigPesq), nenhuma delas relacionada a esta mudança.

## 4. Referência de por que isto existe

Numa execução completa de 75 minutos, a regra sem a guarda produziu:

- 100 orientações fundidas
- 200 vínculos de participante destruídos, um orientador por fusão

Nenhum teste reprovou. O defeito só apareceu comparando contagens de
`advisorship_members` antes e depois.
