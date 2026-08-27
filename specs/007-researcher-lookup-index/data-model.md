# Data Model: Índice de correspondência de pesquisadores

**Feature**: 007-researcher-lookup-index | **Data**: 2026-08-27

Nenhuma tabela é criada, alterada ou removida. A única estrutura nova vive em
memória durante a execução de uma fase.

## Entidade transitória: registro de correspondência

Representa o mínimo necessário para decidir **de quem é um currículo**. Existe
apenas durante a fase; nunca é persistida, serializada ou exportada.

| Campo | Origem | Uso na correspondência |
|---|---|---|
| `id` | `researchers.id` | Identifica o vencedor para hidratação e para o desempate por dados vinculados |
| `name` | `persons.name` | Comparação exata (casefold) e normalizada com o nome do currículo |
| `identification_id` | `persons.identification_id` | Comparação com o Lattes ID; na prática não casa, por ser anonimizado na escrita |
| `cnpq_url` | `researchers.cnpq_url` | Contém o Lattes ID; é o critério estável que efetivamente casa hoje |
| `resume` | `researchers.resume` | Desempate: registro com currículo textual pontua mais |
| `citation_names` | `researchers.citation_names` | Desempate: registro com nomes de citação pontua mais |

**Regra de nomeação**: os campos MUST usar exatamente os mesmos nomes de atributo
da entidade `Researcher`. O algoritmo de pontuação lê candidatos por
`getattr(candidato, "campo", padrão)`, então essa igualdade é o que permite
preservar a equivalência exigida pela FR-005 sem reescrever o algoritmo.

**Mutabilidade**: o registro MUST ser mutável. `projects.py` atualiza
`citation_names`, `cnpq_url` e `resume` do dono do currículo durante a ingestão, e
o índice precisa refletir isso para que currículos seguintes pontuem sobre o
estado corrente.

## Ciclo de vida do índice

```text
início da fase
   │
   ├─ consulta única ao cadastro  ──►  índice com N registros (0,9 ms para N=1060)
   │
   ├─ para cada currículo:
   │     ├─ pontuar candidatos do índice     (leitura pura, sem banco)
   │     ├─ desempate por dados vinculados   (consulta só para quem já casou)
   │     ├─ hidratar o vencedor              (só onde a entidade é necessária)
   │     └─ se ninguém casou e a fase cria:
   │           criar pesquisador  ──►  ACRESCENTAR ao índice
   │
   └─ fim da fase: índice descartado
```

**Invariante**: todo pesquisador criado durante a fase MUST ser acrescentado ao
índice antes que o próximo currículo seja processado. É o que impede duplicatas
(FR-004, SC-004) e é o contrato que `resolve_or_create_researcher` já honra hoje
via acréscimo à lista recebida.

## Tabelas de origem (inalteradas)

```text
persons(id, name, identification_id, birthday)
researchers(id → persons.id, cnpq_url, google_scholar_url, resume, citation_names)
```

Não existe `brand_id` em nenhuma das duas, nem como atributo mapeado — motivo da
FR-006.
