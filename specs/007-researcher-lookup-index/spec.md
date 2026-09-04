# Feature Specification: Índice leve de correspondência de pesquisadores na ingestão do Lattes

**Feature Branch**: `007-researcher-lookup-index`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Eliminar a leitura repetida da tabela inteira de pesquisadores nas fases de ingestão do Lattes, substituindo-a por um índice leve construído uma vez por fase, e hidratando como objeto completo apenas o pesquisador escolhido pela correspondência."

## Contexto

As duas fases mais pesadas da execução semanal — `ingest_lattes_projects` e
`ingest_lattes_advisorships` — percorrem 112 currículos Lattes, um a um. Antes de
processar cada currículo, cada uma pede ao cadastro **a lista completa de
pesquisadores**, com o único objetivo de descobrir de quem é aquele currículo.

A mesma pergunta é feita 112 vezes por fase, e a resposta é sempre igual.

### O que a medição mostrou

Medições feitas em 27/08/2026, contra cópia isolada do banco de produção
(1060 pesquisadores, 112 currículos):

| Fase | Tempo total | Tempo nessa leitura | Fração |
|---|---|---|---|
| `lattes_advisorships` | 1424,6 s | 867,1 s | 60,9% |
| `lattes_projects` | 1165,2 s | 874,9 s | 75,1% |
| **Soma** | **2589,8 s (43 min)** | **1742,0 s (29 min)** | **67,3%** |

Cada leitura custa 7,8 s. O custo **não está no banco**: a instrumentação
registrou **uma única consulta, executada em 0,01 s**. O custo está na montagem
dos objetos em memória, porque o cadastro traz, junto de cada pesquisador, todas
as suas áreas de conhecimento, artigos, produções e e-mails de uma só vez. O
resultado é um produto cartesiano: **828.644 linhas trafegadas para montar 1060
registros**.

Que o problema é específico desse cadastro fica claro na comparação: ler as
**4122** iniciativas leva 0,18 s, e as **4445** pessoas, 0,02 s.

### Por que isso não é um problema de paralelismo

A investigação começou como uma busca por pontos de paralelização. A medição
descartou essa hipótese: as demais fases custam muito menos do que se supunha
(o bloco de relatórios de docentes inteiro leva 61 s, contra 8700 s de teto
configurado), e o trabalho útil dentro do laço é irrisório — a leitura e
interpretação de cada currículo custa **0,1 ms**. O pipeline não está lento por
fazer uma coisa de cada vez; está lento por repetir 224 vezes um trabalho que
precisa acontecer duas.

### Consequência operacional

O tempo dessas fases cresce com o **produto** entre o número de currículos e o
tamanho do cadastro. O backlog já registra o sintoma em TD-007: durações medidas
de 1346 a 1741 s contra um teto que era de 1800 s, elevado para 3600 s em
26/08/2026 como paliativo. A margem volta a encolher conforme o instituto cresce.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A ingestão do Lattes deixa de repetir a leitura do cadastro (Priority: P1)

Como responsável pela execução semanal, quero que cada fase consulte o cadastro de
pesquisadores uma única vez, e traga apenas os dados de que precisa para
identificar o dono de cada currículo, para que a janela da execução semanal pare
de ser consumida por trabalho repetido.

**Why this priority**: É o defeito em si, e responde por 67% do tempo das duas
fases. Sem isso, o teto de tempo continua sendo empurrado para frente a cada
crescimento do cadastro.

**Independent Test**: Executar cada fase sobre o conjunto atual (112 currículos,
1060 pesquisadores) e comparar a duração e os registros gravados com os da
execução anterior.

**Acceptance Scenarios**:

1. **Given** um cadastro com 1060 pesquisadores e 112 currículos em disco,
   **When** a fase de orientações é executada, **Then** a duração total fica
   abaixo de 10 minutos e os registros gravados são os mesmos da execução atual.
2. **Given** o mesmo conjunto, **When** a fase de projetos é executada, **Then** a
   duração total fica abaixo de 10 minutos e os registros gravados são os mesmos.
3. **Given** qualquer um dos 112 currículos, **When** a identificação do dono é
   feita, **Then** o pesquisador escolhido é o mesmo que a implementação atual
   escolheria.

---

### User Story 2 - Pesquisador criado durante a execução continua sendo encontrado (Priority: P1)

Como responsável pela qualidade do cadastro, quero que um pesquisador criado no
meio da execução — por ser orientador citado num currículo, por exemplo — seja
encontrado pelos currículos processados em seguida, para que a mudança não
produza registros duplicados.

**Why this priority**: É a única forma de a otimização introduzir corrupção de
dado. Uma consulta feita uma vez só, se não acompanhar as criações, faria o
currículo seguinte concluir que a pessoa não existe e criá-la de novo.

**Independent Test**: Processar dois currículos em sequência, o primeiro citando
um orientador inexistente no cadastro e o segundo pertencendo a essa mesma pessoa,
e verificar que apenas um registro foi criado.

**Acceptance Scenarios**:

1. **Given** um cadastro que não contém determinada pessoa, **When** um currículo
   provoca a criação dela e um currículo posterior se refere à mesma pessoa,
   **Then** nenhum registro duplicado é criado.
2. **Given** uma execução completa da fase, **When** ela termina, **Then** o número
   de pesquisadores no cadastro é o mesmo que a implementação atual produziria.

---

### User Story 3 - O critério de correspondência passa a ser verdadeiro (Priority: P2)

Como quem mantém o pipeline, quero que o critério usado para identificar o dono de
um currículo não dependa de informação que não existe no cadastro, para que o
comportamento real e o documentado coincidam.

**Why this priority**: Não altera o resultado hoje — é código que nunca dispara —
mas reescrever a consulta obriga a decidir o que fazer com ele, e mantê-lo
sugeriria uma robustez de correspondência que não existe.

**Independent Test**: Inspecionar o critério de correspondência e confirmar que
todo campo consultado existe no cadastro.

**Acceptance Scenarios**:

1. **Given** o critério de correspondência, **When** ele é revisado, **Then**
   nenhum dos campos avaliados é inexistente no cadastro.
2. **Given** a remoção do critério inaplicável, **When** as duas fases são
   executadas, **Then** as atribuições de currículo a pesquisador não mudam.

### Edge Cases

- **Currículo cujo dono não está no cadastro**: a fase de projetos cria a pessoa;
  a fase de orientações registra que não encontrou e segue. Os dois
  comportamentos devem permanecer como são hoje.
- **Cadastro vazio**: a primeira execução sobre um banco recém-criado não pode
  falhar por ausência de registros.
- **Homônimos e variações de acento/caixa**: a escolha entre candidatos empatados
  deve continuar produzindo o mesmo vencedor de hoje, inclusive o critério de
  desempate que prefere o registro com mais dados já vinculados.
- **Falha no meio do laço**: hoje, uma linha com erro provoca o descarte da
  transação corrente. A solução não pode ficar mais lenta nem produzir dados
  inconsistentes quando isso acontecer. (Medido em 27/08: zero ocorrências em 20
  currículos, mas o caminho existe e é silencioso.)
- **Pesquisador alterado durante a execução**: a fase de projetos atualiza dados
  do dono do currículo. Currículos posteriores não podem enxergar informação
  desatualizada a ponto de mudar a correspondência.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Cada fase de ingestão do Lattes MUST consultar o cadastro de
  pesquisadores para fins de correspondência **uma única vez por execução da
  fase**, e não uma vez por currículo.
- **FR-002**: A consulta de correspondência MUST trazer somente os dados usados
  para identificar o dono do currículo, sem arrastar as coleções associadas de
  cada pesquisador.
- **FR-003**: O sistema MUST carregar o registro completo do pesquisador apenas
  para aquele efetivamente escolhido pela correspondência.
- **FR-004**: Um pesquisador criado durante a execução da fase MUST passar a
  constar do conjunto de correspondência, de modo que currículos processados em
  seguida o encontrem em vez de criá-lo novamente.
- **FR-005**: A escolha do pesquisador para cada currículo MUST ser idêntica à
  produzida pela implementação atual, incluindo os critérios de desempate.
- **FR-006**: Os critérios de correspondência que consultam campo inexistente no
  cadastro MUST ser removidos, e a remoção MUST ser registrada na documentação da
  feature.
- **FR-007**: A solução MUST permanecer contida no repositório `horizon_etl`, sem
  alterar a biblioteca de domínio de onde vem o cadastro.
- **FR-008**: O restante do comportamento observável das duas fases MUST
  permanecer inalterado — mesmas entidades gravadas, mesmas quantidades, mesmos
  registros de rastreabilidade.

### Key Entities

- **Índice de correspondência**: conjunto, construído uma vez por fase, com os
  dados mínimos de cada pesquisador necessários para identificar o dono de um
  currículo — identificador, nome, identificação, endereço do currículo na
  plataforma, presença de resumo e nomes de citação. Aceita acréscimos durante a
  execução.
- **Pesquisador**: registro completo do cadastro, carregado sob demanda apenas
  para o vencedor da correspondência, por ser ele que o restante da ingestão
  atualiza e vincula.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: As duas fases de ingestão do Lattes, somadas, concluem em menos de
  **15 minutos** sobre o conjunto atual (112 currículos, 1060 pesquisadores),
  contra os 43 minutos medidos em 27/08/2026.
- **SC-002**: A identificação do dono do currículo é a mesma em **100%** dos 112
  currículos, comparada com a execução atual.
- **SC-003**: As quantidades de registros gravados por cada fase (orientações,
  artigos, formações, prêmios, idiomas, atividades profissionais, produções e
  vínculos) são **idênticas** às da execução atual.
- **SC-004**: Nenhum pesquisador duplicado é criado: a contagem do cadastro ao fim
  de cada fase é idêntica à da execução atual.
- **SC-005**: O tempo gasto na identificação do dono deixa de crescer em proporção
  ao tamanho do cadastro — dobrar o número de pesquisadores não dobra o tempo
  total da fase.

## Assumptions

- O conjunto de 112 currículos em `data/lattes_json` e o cadastro de 1060
  pesquisadores são representativos do que a execução semanal encontra; as
  comparações de "antes e depois" usam esse mesmo conjunto.
- A comparação de equivalência é feita contra o comportamento atual observado, não
  contra uma especificação de correspondência — ou seja, a regra atual é tomada
  como correta, defeitos de correspondência preexistentes ficam fora de escopo.
- O ganho de desempenho é o objetivo; nenhuma mudança de regra de negócio,
  de esquema de dados ou de contrato de exportação faz parte desta feature.
- A causa raiz está na modelagem da biblioteca de domínio (quatro coleções
  carregadas junto de cada pesquisador). Corrigir a biblioteca está fora de
  escopo; esta feature contorna o problema deixando de pedir o que não usa. Um
  apontamento para a biblioteca pode ser aberto em separado.
- Paralelismo está explicitamente fora de escopo: a medição mostrou que o trabalho
  útil por currículo é de 0,1 ms e que o restante é escrita serializada no banco.
