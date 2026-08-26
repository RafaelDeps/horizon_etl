# Phase 1 — Data Model

**Feature**: `004-fix-enrichment-transaction`
**Date**: 2026-08-24

Esta correção **não introduz nem altera entidades**. O modelo abaixo documenta as
estruturas já existentes que o caminho corrigido percorre, com as regras de
validação que precisam continuar valendo depois da mudança.

---

## Documento de projeto (`PJ_*.json`)

Entrada em disco, um arquivo por projeto, lida de `pj_dir`
(padrão `data/exports/project_sigpesq_files_json`). Produzida por processo
externo; **não** é gerada por este repositório.

| Campo | Tipo | Uso no fluxo |
|---|---|---|
| `codigo` | texto (`"PJ 6020"`) | Correspondência por código; apenas os dígitos são extraídos |
| `titulo` | texto | Correspondência exata e aproximada; nome de iniciativa nova |
| `descricao` | texto | Vira `description` (recuo: `objetivos.geral`) |
| `objetivos` | `{geral, especificos[]}` | Persistido no payload de enriquecimento |
| `cronograma` | `[{atividade, inicio, fim}]` | Persistido no payload |
| `linha_pesquisa` | texto | Persistido no payload |
| `palavras_chave` | lista de texto | Persistido no payload |
| `area_conhecimento` | texto | Persistido no payload |
| `datas` | `{inicio, fim}` | Só no caminho de criação de iniciativa nova |
| `_meta` | `{arquivo, extraido_em, modelo}` | Proveniência da extração |

**Regras de validação**:

- Arquivo ilegível ou JSON inválido é registrado como aviso e ignorado, sem
  interromper a leitura dos demais.
- Documento sem `titulo` normalizável e sem código conhecido não corresponde a
  nada e é contabilizado em `skipped_no_match`.
- Documento é elegível a virar iniciativa nova apenas com `titulo`, `descricao` e
  (`objetivos.geral` ou `cronograma`) — regra de `is_ingestable`.

---

## Payload de enriquecimento (`initiatives.enrichment_json`)

Estrutura validada por `EnrichmentPayload` (Pydantic, `extra="forbid"`) e
persistida como texto JSON.

| Campo | Origem |
|---|---|
| `source` | Constante `sigpesq_project_files` |
| `project_code` | Dígitos de `codigo`, ou nulo |
| `match_strategy` | `sigpesq_project_code` \| `title_exact` \| `title_fuzzy` \| `new_from_document` |
| `needs_review` | Verdadeiro em correspondência aproximada, ambígua ou criação nova |
| `objetivos`, `cronograma`, `linha_pesquisa`, `palavras_chave`, `area_conhecimento` | Cópia validada do documento |
| `extracted_at`, `extraction_model`, `source_file` | Espelho de `_meta` |

**Regras de validação**:

- `extra="forbid"` significa que campo desconhecido no documento **não** vaza para
  o payload; campos do documento fora dessa lista (por exemplo dados de
  coordenador ou equipe) são deliberadamente descartados.
- Documento malformado levanta `ValidationError`, que é capturada pelo mecanismo
  de linha e contabilizada em `errors`, sem abortar a execução.

---

## Iniciativa (`initiatives`)

Entidade canônica alvo, definida no pacote externo `research-domain`.

**Campos tocados por esta fase**:

- `description` — preenchida **somente quando vazia**, salvo `overwrite=True`.
- `enrichment_json` — sempre (re)escrita para a iniciativa correspondida. Coluna
  criada pela migração `0001_initiatives_enrichment_json`, aplicada de forma
  idempotente por `ensure_schema()`.

**Transições de estado**: nenhuma. A fase não altera `status`, exceto no caminho
de criação de iniciativa nova (fora do escopo do teste desta branch), onde o
estado inicial é derivado das datas do documento.

---

## Registro de execução de ingestão (`ingestion_runs`)

Criado e finalizado por `tracking_recorder.run_context`, que envolve a chamada de
`loader.run()` no flow.

**Transições de estado**:

```
(criado) ──► success   quando run() retorna normalmente
         └─► failed    quando run() levanta; notes recebe str(exc)
```

Este é o registro que hoje contém a evidência do defeito: uma linha `failed` com
a mensagem da exceção. Após a correção, execuções bem-sucedidas devem produzir
linhas `success`.

---

## Rastro de proveniência

Escrito por `_record_tracking` **apenas quando há contexto de execução ativo**
(`tracking_recorder.has_active_run()`), em quatro registros por documento
aplicado: `source_records`, `entity_matches`, `attribute_assertions` e
`entity_change_logs`.

**Nota de conformidade (LGPD)**: `source_records.raw_payload_json` recebe o
documento **inteiro**, passando por `scrub_source_record_payload`. Os documentos
atuais não trazem dados pessoais nos campos consumidos, mas o esquema de origem
prevê `coordenador` e `equipe`. Isso é observação para trabalho futuro sobre a
origem dos documentos — nada nesta branch altera esse caminho.

---

## Estatísticas retornadas por `run()`

Contrato de saída observável, usado pelo log do flow e pelos testes:

`enriched`, `desc_filled`, `desc_kept_existing`, `needs_review`, `by_code`,
`by_title_exact`, `by_title_fuzzy`, `skipped_no_match`, `skipped_collision`,
`errors` — e, quando `ingest_new=True`, também `created`, `skipped_poor`,
`skipped_duplicate`.
