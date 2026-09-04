# Contract — Execução da fase de enriquecimento

**Feature**: `004-fix-enrichment-transaction`

O projeto não expõe API de rede. A interface relevante desta fase é a de linha de
comando (o orquestrador semanal invoca subprocessos) e o contrato de
comportamento do carregador. Ambos são contratos **existentes**: esta correção
restaura o cumprimento deles, não os redefine.

---

## Contrato de linha de comando

```bash
python app.py enrich_projects
```

| Aspecto | Contrato |
|---|---|
| Argumentos | Nenhum. O flow usa os padrões (`pj_dir` padrão, `ingest_new=True`, sem sobrescrita, sem simulação). |
| Código de saída 0 | Fase concluída. Inclui o caso legítimo de zero documentos. |
| Código de saída 1 | Falha real (banco inacessível, erro irrecuperável). Tratada por `app.py`, que registra e encerra. |
| Efeito colateral | Grava em `initiatives` e nas tabelas de rastreamento; registra a execução em `ingestion_runs`. |

**Invocação pelo orquestrador semanal** — declarada em
`src/flows/pipelines/weekly_orchestrator.py`:

```python
("enrich_projects", ["enrich_projects"], 900, False, "app")
```

Modo `app` (obrigatório: garante o hook de anonimização LGPD instalado no import
de `app.py`), tempo limite de 900 s, fase não-crítica. **Nada disso muda.**

---

## Contrato de comportamento de `ProjectEnrichmentLoader.run()`

```python
run(pj_dir: str, *, ingest_new: bool = False) -> Dict[str, int]
```

### Pré-condições

- Sessão de banco utilizável. A sessão **pode** já ter transação aberta — e na
  prática sempre terá, por conta do *autobegin* nas leituras de índice. Esta é
  precisamente a pré-condição que a implementação atual viola.

### Pós-condições

| Situação | Contrato |
|---|---|
| Sucesso | Retorna o dicionário de estatísticas; as gravações estão confirmadas. |
| Sucesso com zero documentos | Retorna estatísticas zeradas; nenhuma gravação; **não** levanta. |
| Documento individual defeituoso | Aquele documento é descartado, `errors` é incrementado, os demais seguem. |
| Exceção irrecuperável | Propaga a exceção após tentar desfazer a transação. |
| `dry_run=True` | Nenhuma gravação, nenhuma confirmação; estatísticas refletem o que seria feito. |

### Invariantes que a correção deve preservar

1. Descrição existente nunca é sobrescrita sem `overwrite=True`.
2. Cada iniciativa é reivindicada por no máximo um documento, pelo match mais
   confiável (código > título exato > título aproximado).
3. Reexecução sobre a mesma entrada produz o mesmo estado final.
4. Correspondência aproximada, ambígua ou criação nova sempre marca
   `needs_review`.

### Limitação conhecida (ver `research.md`, D3)

A invariante "nada persiste quando a execução falha no meio" **não** é cumprida
pelo banco SQLite atual, porque o driver `pysqlite` confirma cada `SAVEPOINT`
liberado quando ele é o primeiro comando da transação. Isso antecede esta
correção e está registrado como follow-up, fora do escopo desta branch.

---

## Contrato do teste de regressão

O teste a ser criado é, ele próprio, um contrato executável:

| Requisito | Verificação |
|---|---|
| FR-001 | `run()` com `dry_run=False` conclui sem levantar |
| FR-002 | `enrichment_json` fica preenchido para a iniciativa correspondida |
| FR-003 | Descrição preexistente é preservada; descrição vazia é preenchida |
| FR-009 | O teste falha se o defeito for reintroduzido |
| FR-010 | Entrada criada em `tmp_path`; banco em memória; zero dependência externa |
