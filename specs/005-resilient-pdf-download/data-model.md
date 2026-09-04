# Phase 1 — Data Model

**Feature**: `005-resilient-pdf-download`
**Date**: 2026-08-25

Nenhuma entidade de domínio é criada. O que este trabalho introduz são
**classificações de resultado** e suas contagens.

## Situação da inspeção de um projeto

Cada projeto examinado termina em exatamente uma destas quatro situações:

| Situação | Significado | É erro? |
|---|---|---|
| `downloaded` | Anexo localizado e obtido | Não |
| `no_attachment` | Área de anexos reconhecida, sem nenhum anexo | Não — é legítimo (rascunho) |
| `unrecognized` | Área de anexos não reconhecida na página | **Sim** — indica quebra de compatibilidade |
| `modal_failed` | A janela do projeto não abriu | Sim — falha pontual daquele projeto |

A distinção entre `no_attachment` e `unrecognized` é o coração desta feature.
Hoje as duas produzem a mesma mensagem, e foi isso que manteve o defeito
invisível por semanas.

Além delas, `skipped_existing` conta os projetos cujo arquivo já estava em disco
— preservando a retomabilidade e mantendo a soma coerente.

## Critério de classificação

```
candidatos = controles cujo id contém download|baixar|arquiv
           ∪ controles cujo texto termina em .pdf|.doc|.docx|.odt

se candidatos ≠ ∅            -> downloaded (ou falha de download)
senão, se existe área de anexos -> no_attachment
senão                          -> unrecognized
```

"Área de anexos" é qualquer cabeçalho, tabela ou bloco cujo texto inicial
mencione "arquivo(s)".

## Escolha entre múltiplos anexos

1. Candidato cujo texto seja **exatamente** o rótulo desejado (`"Projeto"`).
2. Não havendo, o primeiro candidato — e o registro assinala que foi por recurso,
   não por correspondência.

O item 2 merece atenção: na marcação alternativa testada, o *Parecer* aparece
antes do *Projeto*. Escolher cegamente o primeiro traria o documento errado — um
erro silencioso pior que a falha atual.

## Resumo da execução

Contagens agregadas por situação, emitidas ao fim do download:

`examined`, `downloaded`, `skipped_existing`, `no_attachment`, `unrecognized`,
`modal_failed`

**Invariante**: `examined` = soma das demais.

## Leitura do resumo (encerra o diagnóstico em aberto)

| Resumo | Conclusão |
|---|---|
| `downloaded > 0` | Os anexos continuam no portal; a correção resolveu |
| `unrecognized > 0` e `downloaded = 0` | Quebra de compatibilidade ainda não coberta |
| `no_attachment` = tudo e `unrecognized = 0` | Os anexos foram removidos do portal |
