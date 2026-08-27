# Contrato interno: `src/core/logic/researcher_resolution.py`

**Feature**: 007-researcher-lookup-index | **Data**: 2026-08-27

O módulo não é interface pública do projeto, mas é consumido por quatro pontos
fora dele. Este contrato existe para que a mudança de tipo de retorno seja
explícita, já que passa a haver duas representações de um pesquisador.

## Consumidores atuais

| Chamador | Função | Do que precisa do retorno |
|---|---|---|
| `flows/lattes/advisorships.py:54` | `resolve_researcher_from_lattes` | Apenas `name` |
| `flows/lattes/projects.py:106` | `resolve_researcher_from_lattes` | Entidade completa: lê e grava atributos, persiste, vincula |
| `flows/lattes/projects.py:117` | `resolve_or_create_researcher` | Entidade completa (mesmo caminho acima) |
| `flows/lattes/projects.py:474,489` | `resolve_or_create_researcher` | Apenas `id` |
| `strategies/cnpq_sync.py:268` | `resolve_or_create_researcher` | **Fora do escopo** — não pode quebrar |
| `strategies/sigpesq_excel.py:103` | `resolve_or_create_researcher` | **Fora do escopo** — não pode quebrar |

## Contrato após a mudança

**`load_researcher_index(session) -> list[registro]`** *(novo)*

- Emite **uma** consulta e devolve um registro por pesquisador.
- Os registros não pertencem à sessão: não expiram em `rollback()`.
- Custo alvo: sub-milissegundo por milhar de pesquisadores.

**`resolve_researcher_from_lattes(candidatos, ...)`** *(assinatura preservada)*

- Aceita registros do índice **ou** entidades ORM, indistintamente: lê tudo por
  `getattr`.
- Devolve o candidato vencedor, do mesmo tipo que recebeu, ou `None`.
- A escolha MUST ser idêntica à atual para os mesmos dados (FR-005).

**`resolve_or_create_researcher(researcher_ctrl, candidatos, ...)`** *(assinatura preservada)*

- Se encontrar, devolve o candidato do tipo recebido.
- Se criar, MUST acrescentar o recém-criado a `candidatos` **e** devolvê-lo.
- Chamadores fora do escopo continuam passando listas de entidades ORM e
  continuam recebendo entidades ORM. **Compatibilidade retroativa obrigatória**:
  nenhuma alteração de comportamento para `cnpq_sync` e `sigpesq_excel`.

**Hidratação** — responsabilidade do chamador

- Quem precisa da entidade completa a obtém pelo `id` do vencedor.
- `advisorships.py` **não** precisa hidratar: usa apenas o nome.

## Invariantes verificáveis

1. Passar entidades ORM produz exatamente o resultado de hoje (compatibilidade).
2. Passar registros do índice produz o mesmo vencedor que passar entidades ORM,
   para o mesmo conjunto de dados (equivalência — FR-005).
3. Criar um pesquisador durante o laço torna-o encontrável na chamada seguinte
   (FR-004).
