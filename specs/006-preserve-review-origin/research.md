# Phase 0 — Research

**Feature**: `006-preserve-review-origin`
**Date**: 2026-08-25

---

## D1 — Onde os dois conceitos se misturam

`build_enrichment(pj, *, code, strategy, needs_review)` recebe `needs_review`
pronto, e quem o calcula é o resultado da correspondência da execução corrente
(`Match.needs_review`). O payload é **sempre reescrito** por `_apply`, então a
marca da execução anterior é descartada.

Consequência: uma iniciativa criada na execução 1 (estratégia
`new_from_document`, marca verdadeira) passa a corresponder por título exato na
execução 2 — estratégia confiável — e a marca vira falsa.

**Verificado**: 96 → 49 marcadas, diferença de exatamente 47, os criados.

---

## D2 — Como recuperar a origem numa execução posterior

**Decisão**: ler o payload atual da iniciativa **antes** de sobrescrevê-lo, e
carregar dali a origem e o estado de revisão.

**Rationale**: `run()` já carrega as descrições atuais por um motivo análogo
(decidir se preenche). Carregar também o enriquecimento atual é simétrico, custa
uma consulta e não depende de tabela de auditoria no caminho quente.

**Compatibilidade com o que já existe**: payloads gravados antes desta mudança não
têm o campo de origem. Ao lê-los, a origem é inferida da estratégia registrada:
se era `new_from_document`, a iniciativa nasceu de documento. Isso cobre os
registros que ainda não foram sobrescritos.

Para os já sobrescritos, a inferência não funciona — daí a necessidade da
reconstrução a partir da trilha de auditoria (FR-009), onde `entity_matches`
preserva `new_from_document` de forma imutável.

**Alternatives considered**: consultar `entity_matches` a cada linha durante o
enriquecimento (rejeitado — acopla o caminho quente à auditoria e multiplica
consultas); manter uma tabela separada de origem (rejeitado — mais invasivo do
que o problema exige, e o payload já viaja para o export).

---

## D3 — A marca passa a ser derivada, não recebida

**Decisão**: `needs_review` deixa de ser parâmetro e passa a ser calculado:

```
revisado por humano        -> falso
origem = criada de documento -> verdadeiro
correspondência incerta      -> verdadeiro
caso contrário               -> falso
```

**Rationale**: é exatamente a separação que a especificação pede. A estratégia da
execução corrente continua registrada (FR-002), mas deixa de decidir sozinha.
"Incerta" é o que a correspondência já sinalizava: título aproximado ou título
exato ambíguo.

**Consequência desejável**: a função de derivação é pura e testável sem banco,
entrando na suíte que já existe para a lógica pura.

---

## D4 — O export não precisa de mudança

**Verificado**: `canonical_exporter.py:1660` lê `enrichment_json` inteiro e o
publica sob a chave `enrichment` (linha 1824). Qualquer campo novo no payload
chega ao catálogo automaticamente. **FR-007 é satisfeita por construção**, sem
tocar no exportador.

---

## D5 — Registro de revisão humana

**Decisão**: um método no carregador mais um comando de linha, sem interface.

**Rationale**: a especificação coloca interface fora do escopo e pede "meio
operacional simples". Um comando que recebe o identificador da iniciativa e quem
revisou cobre a FR-005 e mantém o caminho auditável.

**Alternatives considered**: coluna dedicada na tabela (rejeitado — o payload já
é o veículo e já chega ao export); planilha externa (rejeitado — sairia do
repositório e não seria reproduzível).

---

## D6 — A reconstrução não entra no pipeline

**Decisão**: expor a reconstrução como capacidade acionável, não como etapa
automática.

**Rationale**: no fluxo semanal atual o banco é reconstruído a cada execução,
então a reconstrução seria inócua e gastaria tempo. Ela importa no dia em que o
reset sair, e quando alguém precisar corrigir um banco já afetado.
