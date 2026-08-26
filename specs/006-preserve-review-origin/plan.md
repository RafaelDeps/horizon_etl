# Implementation Plan: Preservar origem e necessidade de revisão

**Branch**: `006-preserve-review-origin` | **Date**: 2026-08-25 | **Spec**: [spec.md](spec.md)

## Summary

A marca de revisão se apaga porque é derivada da estratégia de correspondência da
execução corrente, e o payload é sempre reescrito. A correção separa os conceitos:
a **origem** vira campo próprio e permanente, a **estratégia** continua sendo
registrada como informação da execução, e a **marca** passa a ser derivada de
origem, incerteza e revisão humana. Acrescenta-se um meio de registrar revisão e
uma capacidade de reconstruir a origem de registros já afetados.

Mudança contida: um arquivo de produção, um comando novo, testes nos dois
arquivos de teste já existentes.

## Technical Context

**Language/Version**: Python 3.14.4 (`.venv`)

**Primary Dependencies**: SQLAlchemy 2.0.52, Pydantic 2.x, Prefect 3.6.23

**Storage**: coluna JSON `initiatives.enrichment_json`; trilha em `entity_matches`

**Testing**: pytest — lógica pura em `test_project_enrichment.py`, caminho de
gravação em `test_project_enrichment_db.py` (SQLite em memória)

**Target Platform**: Linux

**Project Type**: Pipeline ETL de projeto único

**Constraints**: o payload é validado com `extra="forbid"`, então campos novos
precisam entrar no modelo; payloads gravados antes desta mudança precisam
continuar legíveis

**Scale/Scope**: 306 iniciativas com enriquecimento, 47 criadas a partir de
documento

## Constitution Check

| Princípio | Situação | Justificativa |
|---|---|---|
| **I. Ports & Adapters** | ✅ Conforme | Mudança em `src/core/logic/`, sem importar adaptadores. |
| **II. Domain-First** | ✅ Conforme | Nenhuma entidade nova; campos dentro de um payload já existente. |
| **III. Prefect Flow** | ✅ Conforme | O flow existente não muda; o comando de revisão é utilitário operacional, não ingestão. |
| **IV. Audit-Driven** | ✅ **Reforça** | Restaura a auditabilidade que o ADR-002 promete e que hoje expira. |
| **V. LGPD** | ⚠️ **Atenção** | O registro de quem revisou é dado pessoal. Ver *Complexity Tracking*. |
| **Data Integrity** | ✅ Conforme | Banco continua recriável; a reconstrução é capacidade, não fonte de verdade. |
| **Quality Gates** | ✅ Conforme | black/isort/flake8 nos arquivos tocados e suíte pytest. |

**Gate pré-Fase 0**: PASSA. **Gate pós-Fase 1**: PASSA com a ressalva de LGPD
registrada abaixo.

## Project Structure

```text
src/core/logic/
└── project_enrichment.py          # ALTERADO — origem, derivação, revisão, reconstrução

app.py                             # ALTERADO — comando de registro de revisão

tests/
├── test_project_enrichment.py     # ALTERADO — testes da derivação (lógica pura)
└── test_project_enrichment_db.py  # ALTERADO — persistência, reexecução, reconstrução
```

**Structure Decision**: a mudança é de regra de negócio e permanece em
`src/core/logic/`, junto do restante do enriquecimento. O comando operacional
entra em `app.py`, como os demais.

## Complexity Tracking

| Ponto | Descrição | Mitigação |
|---|---|---|
| **Identificação de quem revisou é dado pessoal** | A FR-005 pede registrar que uma pessoa revisou. Um nome ou e-mail nesse campo viajaria para `initiatives_canonical.json`, que é artefato exportado — e o princípio V proíbe e-mail em claro em qualquer saída. | O campo aceita um identificador livre, e a documentação do comando orienta usar matrícula ou iniciais, **não** e-mail. O anonimizador já converte qualquer e-mail encontrado em texto, então um engano é contido, mas a orientação evita depender disso. |
