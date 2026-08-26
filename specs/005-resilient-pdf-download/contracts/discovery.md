# Contract — Descoberta do anexo na página do projeto

**Feature**: `005-resilient-pdf-download`

## Contrato da estratégia

A estratégia substitui **apenas** a inspeção de um projeto. Continuam sendo
responsabilidade da biblioteca externa: acesso autenticado, navegação, paginação
da relação de projetos e a decisão de pular arquivos já presentes.

### Entrada
Uma página com a janela do projeto aberta, e o rótulo desejado (padrão `"Projeto"`).

### Saída
Uma das quatro situações de `data-model.md`, e — quando `downloaded` — o arquivo
gravado com a **extensão original** preservada.

### Invariantes

1. Um projeto não interpretável **não** interrompe os demais.
2. Documento já em disco não é buscado de novo.
3. Nenhum dado pessoal é registrado; os logs trazem código de projeto e nome de
   arquivo.
4. A biblioteca externa não é modificada.

## Contrato de observabilidade

Por projeto, uma linha distinguindo as situações. `unrecognized` **precisa** ser
visivelmente diferente de `no_attachment`.

Ao fim, um resumo com todas as contagens, cuja soma é igual a `examined`.

## Contrato de verificação

Quatro cenários, todos offline:

| Cenário | Esperado |
|---|---|
| Marcação conhecida, com anexo rotulado | `downloaded`, escolhido pelo rótulo |
| Marcação alternativa, com anexo rotulado | `downloaded`, escolhido pelo rótulo |
| Área de anexos presente e vazia | `no_attachment` |
| Sem área de anexos | `unrecognized` |
