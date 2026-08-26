# ADR 002: Enrichment de Projetos a partir dos Documentos SigPesq (PJ)

* Status: Accepted
* Deciders: Claude, Paulo
* Date: 2026-07-20

Technical Story: O relatório Excel do SigPesq só traz um resumo raso dos projetos (e apenas os aprovados/recentes — ~101 linhas). Os planos de projeto em PDF/DOC contêm descrição completa, objetivos, cronograma e linha de pesquisa. Um processo externo extraiu esses documentos por LLM para `data/exports/project_sigpesq_files_json/PJ_*.json` (355 arquivos). Faltava incorporá-los ao modelo canônico.

## Context and Problem Statement

70,6% das iniciativas tinham `description` nula. Os campos ricos dos documentos (objetivos, cronograma datado, linha de pesquisa, palavras-chave) **não têm coluna** na tabela `initiatives`. Além disso, ~260 projetos dos documentos não existiam no banco (fora do snapshot do Excel). Precisávamos: (a) enriquecer o que existe sem sobrescrever dados de fontes mais autoritativas, (b) decidir onde persistir os campos sem coluna, (c) decidir o que fazer com os projetos ausentes.

## Decision Drivers

* Não sobrescrever dados de fontes autoritativas (Excel `Resumo`, Lattes/CNPq) — coerente com o [ADR 001](001-strict-idempotency-sigpesq.md).
* Extração por LLM é ruidosa → matches incertos precisam ser auditáveis.
* Idempotência: rodar no pipeline semanal não pode duplicar nem divergir.
* Rastreabilidade (fonte, modelo de extração, estratégia de match).

## Considered Options

* **Match**: (1) só por código SigPesq; (2) código + título exato; (3) código + título exato + fuzzy.
* **Persistência dos campos ricos**: (A) coluna JSON `enrichment_json`; (B) só `attribute_assertions` (audit, não exportado); (C) tabela normalizada `initiative_enrichment`.
* **Projetos ausentes**: (i) ignorar; (ii) ingerir os "ricos" como novas iniciativas.

## Decision Outcome

* **Match em cascata por confiança**: `sigpesq_project_code` (via tracking tables; são aprovados) → `title_exact` → `title_fuzzy` (rapidfuzz ≥ 90). Dedupe por prioridade: cada iniciativa é reivindicada uma vez pelo match mais confiável (código vence título), evitando que um match fraco sobrescreva um forte.
* **Persistência = coluna JSON `enrichment_json`** (Opção A). `metadata` era inviável (nome reservado do SQLAlchemy — nunca persistia). `description` (único campo canônico com coluna) é preenchido **só quando vazio** (salvo `overwrite=True`).
* **`needs_review`** no payload marca matches por título/fuzzy e projetos novos.
* **Ingestão de ausentes ricos** (título + descrição + objetivos/cronograma) como novas iniciativas (Opção ii), com dedupe de título e `needs_review`. Idempotente: em runs seguintes casam por título e não são recriados.
* Roda no pipeline **após** SigPesq + Lattes (o title-match usa iniciativas Lattes) e **antes** do export.

### Consequences

* Good: 70,6% → ~68% de descrições nulas preenchidas onde há documento; objetivos/cronograma/linha/keywords passam a existir (antes em nenhuma iniciativa).
* Good: proveniência completa (source_records + entity_matches + attribute_assertions + change_logs) com `match_strategy`/`needs_review`.
* Good: idempotente e reprodutível pelo pipeline (sem passo manual).
* Bad: `enrichment_json` é blob → não filtrável por SQL (ver [ADR 003](003-parquet-canonical-storage.md) e follow-up de normalização).
* Bad: `title_fuzzy` pode gerar falso-positivo — mitigado por `needs_review`, não eliminado.
* Bad: coluna criada via DDL em runtime (`ensure_schema`) — stopgap até adotar ferramenta de migração.

## Pros and Cons of the Options

### Persistência A — coluna JSON `enrichment_json`
* Good: simples, export direto no `initiatives_canonical.json`, sem migração pesada.
* Bad: não normalizado; sem validação de schema; não querytável em SQL.

### Persistência B — só attribute_assertions
* Good: zero mudança de schema; audit nativo.
* Bad: dado fica "enterrado" no log de auditoria; não aparece no export nem para o dashboard.

### Persistência C — tabela normalizada
* Good: querytável, tipado.
* Bad: mais invasivo (modelo/migração/ORM); adiado como follow-up.

## Nota de correção (2026-08-24)

A fase **nunca chegou a executar** desde a implementação original. O
`ProjectEnrichmentLoader.run()` abria uma transação explícita depois que os
carregamentos de índice já haviam aberto uma (autobegin do SQLAlchemy 2.0),
levantando `InvalidRequestError: A transaction is already begun on this Session`
antes de ler qualquer documento. Como a fase é não-crítica no orquestrador
semanal, o pipeline seguia e reportava sucesso, e a falha ficava apenas numa linha
de erro perdida no log.

Consequência: os ganhos declarados acima ("70,6% → ~68% de descrições nulas
preenchidas", objetivos/cronograma/linha/keywords passando a existir) **não se
materializaram** — a auditoria do banco mostrava zero iniciativas com
`enrichment_json`. Da mesma forma, a consequência "idempotente e reprodutível pelo
pipeline (sem passo manual)" vale para o *consumo* dos documentos, mas não para a
*produção* deles: os `PJ_*.json` continuam vindo de um processo externo executado
manualmente, e não estão versionados neste repositório.

Corrigido em `specs/004-fix-enrichment-transaction`, com teste de regressão em
`tests/test_project_enrichment_db.py`. Ver `research.md` daquela feature para o
diagnóstico completo, incluindo o achado de que a atomicidade por execução não é
garantida no SQLite atual (o driver `pysqlite` confirma cada `SAVEPOINT`
liberado) — registrado como follow-up.

## Nota de correção (2026-08-25) — marca de revisão persistente

A consequência declarada acima de que "matches incertos precisam ser auditáveis"
via `needs_review` não se sustentava ao longo do tempo. O campo era derivado da
estratégia de correspondência da execução corrente e o payload é sempre
reescrito, de modo que uma iniciativa criada por documento (marca verdadeira)
passava a casar por título exato na execução seguinte e tinha a marca apagada.
Observado: 96 → 49, diferença de exatamente os 47 criados.

O defeito era **latente** no fluxo semanal, porque o `weekly-flows` reconstrói o
banco a cada execução e o enriquecimento roda uma única vez. Manifestava-se ao
executar a fase isoladamente mais de uma vez — e contradizia a promessa de
idempotência registrada neste ADR.

Corrigido em `specs/006-preserve-review-origin`, separando os conceitos:

* `origin` — como a iniciativa passou a existir. Fato histórico, permanente.
* `match_strategy` — como o documento casou nesta execução. Volátil, continua
  registrado por ser útil ao diagnóstico.
* `needs_review` — **derivado** de origem, incerteza da correspondência e
  revisão humana registrada. Só uma revisão registrada retira a marca.
* `reviewed_at` / `reviewed_by` — preenchidos exclusivamente por
  `python app.py mark_reviewed <id> <revisor>`. Use identificador não-pessoal
  (matrícula ou iniciais): o campo viaja para o export canônico.

Para bancos já afetados, `python app.py backfill_enrichment_origin` reconstrói a
origem a partir de `entity_matches`, que a preservou. Não faz parte do pipeline.
