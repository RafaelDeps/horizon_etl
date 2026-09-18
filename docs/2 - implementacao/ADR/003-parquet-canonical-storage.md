# ADR 003: Parquet como Formato de Armazenamento/Consumo dos Exports Canônicos

* Status: Accepted (amended 2026-09-18 — see Amendment below)
* Deciders: Claude, Paulo
* Date: 2026-07-20

> **Amendment (2026-09-18, feature 013-curate-export-zip)**: the weekly flow no
> longer emits the parquet mirror — `export_parquet_task` and its call were
> removed from `export_canonical_data_flow`, so `data/exports/parquet/` is not
> produced and does not ship inside `exports_canonical.zip` anymore. The
> decision itself (hybrid format, zstd, build-time consumption in the
> dashboard) remains in force: the dashboard keeps reading its own committed
> copies in `src/data`, not the ETL archive. The conversion capability remains
> available on demand via `python -m src.scripts.export_parquet`.

Technical Story: Os exports canônicos em JSON somam ~255 MB (44 arquivos), e o dashboard irmão (`horizon_dashboard`) versiona cópias desses JSON em `src/data` (~322 MB no git). O repositório e o build ficaram pesados. Avaliou-se migrar o armazenamento/consumo para Parquet.

## Context and Problem Statement

As tabelas grandes (provenance: `attribute_assertions` 45 MB, trackings, `source_records`) dominam o volume. O dashboard é **SSG** (Astro): os dados são embutidos no build, o browser **não** baixa os JSON. Logo, o custo do JSON é de **repositório e build**, não de página. Precisávamos reduzir esse peso sem mudar a saída do site nem quebrar consumidores.

## Decision Drivers

* Reduzir tamanho de repositório/zip/transferência.
* Não alterar o HTML gerado (SSG) nem o consumo por LLM/humano do que precisa ser legível.
* Baixo atrito de migração no dashboard (evitar reescrever dezenas de imports para async).
* Preservar fidelidade (round-trip exato).

## Considered Options

* **Formato**: (1) manter JSON; (2) tudo Parquet; (3) híbrido (Parquet nas tabelas, JSON nos aninhados pequenos/grafos).
* **Consumo no dashboard**: (A) leitura em build-time (plugin Vite decodifica Parquet → objeto, imports continuam síncronos); (B) leitura em runtime (browser + duckdb-wasm/hyparquet).
* **Compressão**: snappy (zero dep no leitor) vs zstd (menor, precisa de lib).

## Decision Outcome

* **Híbrido (Opção 3)**: tabelas array-de-objetos → `<name>.parquet`; grafos node-link → `<name>.nodes.parquet` + `<name>.edges.parquet` + `<name>.meta.json`; summaries/marts pequenos e `_meta` seguem JSON. Compressão **zstd**.
* **ETL**: `src/scripts/export_parquet.py` + etapa `export_parquet_task` no `export_canonical_data_flow` emitem `data/exports/parquet/` (dentro do zip).
* **Dashboard**: leitura **build-time** (Opção A) via `parquet-plugin.mjs` (Vite, `enforce: pre`) usando `hyparquet` + `hyparquet-compressors`. Imports seguem síncronos → churn mínimo. SSG inalterada.
* **Runtime (Opção B) rejeitada** para o caso geral: adicionaria wasm ao usuário final sem necessidade (o dado já é embutido no build).

### Consequences

* Good: `src/data` do dashboard **322 MB → 93 MB**; tabelas top-level **255 MB → 15 MB (~6%)**. Fidelidade verificada (0 divergências).
* Good: saída SSG idêntica; consumidores analíticos (pandas/DuckDB) ganham colunar/tipado.
* Bad: **subdir de grafos por-grupo (78 MB) segue JSON** — convertê-lo fez o build embutir 345 grafos via o plugin e **estourar a heap (OOM, 8 GB)**; o JSON tem carregamento lazy nativo mais leve. Só daria para converter migrando esse caso para leitura em runtime (não feito).
* Bad: 2 dependências novas no dashboard (`hyparquet`, `hyparquet-compressors`).
* Bad: revival de campos aninhados no plugin é heurístico (string começando com `[`/`{`) — robusto o suficiente para estes dados, não em geral.

## Pros and Cons of the Options

### Consumo A — build-time (escolhido)
* Good: imports síncronos, libs/páginas quase intocadas; SSG idêntica; sem peso ao usuário.
* Bad: o build carrega tudo em memória → não escala para milhares de arquivos grandes embutidos (vide OOM do subdir).

### Consumo B — runtime (browser)
* Good: build leve; permite query client-side sobre datasets grandes.
* Bad: adiciona wasm/fetch ao usuário; só compensa se houver feature de "explorar a base inteira ao vivo".

### Compressão zstd vs snappy
* zstd: ~2× menor; exige `hyparquet-compressors` (adotado).
* snappy: zero dep no leitor, porém maior no repo.
