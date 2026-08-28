# Implementation Plan: Proteger participantes contra fusão por nome

**Branch**: `008-guard-participant-merge` | **Date**: 2026-08-28 | **Spec**: [spec.md](spec.md)

## Summary

Uma correção recente ensinou a ingestão a reconhecer projetos escritos em grafias
diferentes, eliminando 57 duplicatas. Aplicada também a orientações, ela fundiu
100 delas e destruiu 200 vínculos de participante — porque em orientação o nome é
o título do trabalho, que se repete legitimamente entre orientador e coorientador.
A restrição já foi aplicada; falta a rede que impeça alguém de desfazê-la.

Esta feature acrescenta **apenas testes**, em duas camadas: o resolvedor de
correspondência e a consequência observável no processamento de uma linha. E
inclui um experimento obrigatório — desfazer a restrição e confirmar que a suíte
reprova —, porque um teste de regressão que nunca foi visto falhando não prova
proteção nenhuma. Foi assim que 283 testes deixaram o defeito passar.

## Technical Context

**Language/Version**: Python 3.14.4 (`.venv`)

**Primary Dependencies**: pytest, `unittest.mock`; nenhuma dependência nova

**Storage**: nenhum — os testes não abrem banco

**Testing**: pytest, no arquivo já existente `tests/test_project_loader_matching.py`

**Target Platform**: Linux

**Project Type**: Pipeline ETL de projeto único

**Performance Goals**: os novos testes concluem em menos de 5 s, para caberem em
toda execução da suíte

**Constraints**: `ProjectLoader.__init__` instancia sete controllers ligados a
uma sessão global, então os testes usam `__new__` e atribuem só os colaboradores
do caminho exercitado; **nenhuma alteração em código de produção**

**Scale/Scope**: um arquivo de teste, ~8 casos

## Constitution Check

| Princípio | Situação | Justificativa |
|---|---|---|
| **I. Ports & Adapters** | ✅ Neutro | Só testes; nenhum import novo em `src/core/logic/`. |
| **II. Domain-First** | ✅ Neutro | Nenhuma entidade criada. Os testes usam `Advisorship` do `research_domain` como marcador de tipo, que é o mecanismo real. |
| **III. Prefect Flow** | ✅ Neutro | Nenhum flow tocado. |
| **IV. Audit-Driven** | ✅ **Reforça** | A constituição pede que loaders venham com cobertura correspondente. Esta feature paga uma dívida: o loader ganhou regra de correspondência nova sem teste que a protegesse. |
| **V. LGPD** | ✅ Conforme | Os testes usam nomes fictícios. Nenhum dado real, nenhuma saída em arquivo. |
| **Data Integrity** | ✅ **Reforça** | O objeto protegido é exatamente integridade: participante que não pode desaparecer numa fusão. |
| **Quality Gates** | ✅ Conforme | black/isort/flake8 no arquivo tocado; a suíte precisa continuar com o mesmo resultado. |

**Gate pré-Fase 0**: PASSA. **Gate pós-Fase 1**: PASSA.

## Project Structure

### Documentation (this feature)

```text
specs/008-guard-participant-merge/
├── plan.md              # Este arquivo
├── spec.md              # O quê e por quê
├── research.md          # Decisões de nível de teste (Fase 0)
├── data-model.md        # Os cenários como dados (Fase 1)
├── quickstart.md        # Como rodar e como validar a proteção (Fase 1)
├── contracts/
│   └── regras_correspondencia.md   # As regras que os testes fixam
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
tests/
└── test_project_loader_matching.py   # ALTERADO — acrescenta os casos novos
                                      #   aos dois já existentes

src/                                  # INTOCADO
```

**Structure Decision**: os casos entram no arquivo que já testa
`_resolve_existing_initiative`, em vez de um arquivo novo. Quem for mexer na
correspondência abre esse arquivo; um `test_merge_guard.py` separado seria fácil
de não notar — e não ser notado é exatamente o modo de falha que a feature
combate.

## Complexity Tracking

| Ponto | Descrição | Mitigação |
|---|---|---|
| **Testes acoplados a método privado** | Os casos chamam `_resolve_existing_initiative` e `_process_row`, ambos privados. Uma refatoração que os renomeie quebra os testes mesmo sem quebrar o comportamento. | É o preço de fixar a regra onde ela mora, e o arquivo já faz isso nos dois testes existentes. A camada de consequência reduz o dano: ela afirma o efeito no handler, não o valor devolvido, então sobrevive a mudanças internas do resolvedor. |
| **Mock que passa pelo motivo errado** | Um mock mal montado faz o teste passar sem exercitar o caminho — foi assim que 283 testes não viram nada. | É o que a tarefa do experimento (SC-001) existe para pegar: se a suíte não reprovar com a restrição desfeita, o teste é decorativo e precisa ser refeito. **Sem esse experimento, a feature não está pronta.** |
| **`tracking_recorder` global no `_process_row`** | O método chama o gravador de linhagem, que retorna cedo sem contexto ativo. O teste passaria a depender desse detalhe sem dizer. | O teste declara a dependência explicitamente, com `patch` no `tracking_recorder` do módulo, em vez de se apoiar no retorno silencioso. |
