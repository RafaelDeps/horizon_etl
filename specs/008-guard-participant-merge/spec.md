# Feature Specification: Proteger participantes contra fusão por nome

**Feature Branch**: `008-guard-participant-merge`

**Created**: 2026-08-28

**Status**: Draft

**Input**: User description: "Proteger, com testes de regressão, a regra de que casar iniciativas por nome normalizado não pode fundir entidades com participantes distintos."

## Contexto

A ingestão reconhece que dois registros descrevem a mesma coisa comparando nomes.
Uma melhoria recente ensinou essa comparação a ignorar diferenças de caixa e
acento — "PROJETO X" e "Projeto X" passaram a ser reconhecidos como o mesmo
projeto. O efeito foi o pretendido: **57 projetos duplicados no catálogo caíram
para zero**.

Aplicada sem distinção, porém, a mesma regra causou dano. Em orientações
acadêmicas o nome não identifica a orientação: é o **título do trabalho**, e o
mesmo trabalho aparece legitimamente em mais de um currículo — o do orientador e
o do coorientador —, cada registro trazendo participantes diferentes. Ao tratar
esses registros como duplicata, a ingestão manteve uma linha só, com os
participantes de quem foi gravado por último.

Medido numa execução completa: **100 orientações fundidas e 200 vínculos de
participante destruídos**, um orientador perdido por fusão.

### Como o defeito escapou

**Nenhum dos 283 testes existentes reprovou.** Todos verificavam o *mecanismo* de
correspondência — se a função devolve o candidato certo — e nenhum verificava a
*consequência*: se os participantes sobreviveram. O defeito só apareceu ao
comparar contagens de vínculos antes e depois de uma execução real do pipeline,
que leva mais de uma hora.

A correção já foi aplicada — a comparação por nome normalizado passou a valer
somente para projetos. O que falta é a rede que impeça alguém de desfazê-la sem
perceber, daqui a seis meses, ao mexer na correspondência por outro motivo.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reintroduzir a fusão passa a reprovar de imediato (Priority: P1)

Como quem mantém a ingestão, quero que uma alteração que volte a fundir
orientações pelo título reprove na suíte de testes em segundos, para que o dano
não precise ser descoberto por uma execução completa do pipeline nem, pior, por
alguém notando participantes ausentes no painel semanas depois.

**Why this priority**: É a feature inteira. Sem isso, a única defesa contra a
regressão é a memória de quem a viveu.

**Independent Test**: Desfazer a restrição no código de produção e confirmar que
a suíte reprova; refazer a restrição e confirmar que passa.

**Acceptance Scenarios**:

1. **Given** dois registros de orientação com o mesmo título e participantes
   diferentes, **When** ambos são ingeridos, **Then** o resultado tem **duas**
   orientações, e não uma.
2. **Given** o mesmo cenário, **When** a restrição é removida do código de
   produção, **Then** ao menos um teste reprova.
3. **Given** um registro de orientação cujo título coincide com o de outra
   orientação já existente, **When** a correspondência é resolvida, **Then** ela
   não devolve a orientação existente por semelhança de nome.

---

### User Story 2 - A deduplicação de projetos continua funcionando (Priority: P1)

Como responsável pela qualidade do catálogo, quero que a proteção acima não
reabra o problema que a melhoria resolveu, para que projetos escritos em grafias
diferentes continuem virando uma linha só.

**Why this priority**: Uma proteção que só saiba dizer "não funda nada"
devolveria os 57 projetos duplicados. As duas regras precisam coexistir, e o
teste precisa fixar **as duas**.

**Independent Test**: Verificar que um projeto com o mesmo nome em caixa
diferente é reconhecido como existente, na mesma suíte que garante que
orientações não são.

**Acceptance Scenarios**:

1. **Given** um projeto já registrado como "Projeto X", **When** chega "PROJETO
   X", **Then** a correspondência reconhece o projeto existente.
2. **Given** um projeto cujo nome coincide exatamente com um já registrado,
   **When** a correspondência é resolvida, **Then** a coincidência exata tem
   precedência sobre a aproximada.

---

### User Story 3 - O nome já registrado prevalece (Priority: P2)

Como responsável pelo catálogo, quero que reconhecer um projeto por grafia
diferente não renomeie o registro existente, para que a ingestão não tente dar a
um registro um nome que outro já ocupa — situação que, quando ocorreu, fez o
registro ser descartado.

**Why this priority**: É a segunda metade da mesma correção. Renomear ao casar
foi o que produziu perda de registro por violação de unicidade.

**Independent Test**: Reconhecer um projeto por grafia diferente e verificar que
o nome persistido não mudou.

**Acceptance Scenarios**:

1. **Given** "Projeto X" registrado e "PROJETO X" chegando, **When** os dois são
   reconhecidos como o mesmo, **Then** o nome registrado permanece "Projeto X".

### Edge Cases

- **Sem índice de nomes disponível**: a correspondência não pode falhar; deve
  apenas não encontrar por semelhança.
- **Coincidência entre tipos**: um projeto e uma orientação com o mesmo título
  não podem ser confundidos entre si.
- **Título ausente ou vazio**: não deve casar com nada nem levantar erro.
- **Mesmo trabalho, mesmo participante**: dois registros idênticos em título
  **e** participantes continuam sendo duas orientações distintas — a proteção
  não tenta decidir quando fundir seria correto, apenas nunca funde.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A suíte MUST reprovar se a correspondência por nome aproximado
  voltar a se aplicar a orientações.
- **FR-002**: A suíte MUST confirmar que a correspondência por nome aproximado
  continua se aplicando a projetos.
- **FR-003**: A suíte MUST verificar a **consequência** — que dois registros de
  orientação com o mesmo título e participantes distintos resultam em duas
  entidades — e não apenas o valor devolvido pela função de correspondência.
- **FR-004**: A suíte MUST confirmar que a coincidência exata de nome tem
  precedência sobre a aproximada.
- **FR-005**: A suíte MUST confirmar que reconhecer por grafia diferente preserva
  o nome já registrado.
- **FR-006**: Os testes MUST rodar sem banco de dados, serviço externo ou
  execução do pipeline, e concluir em segundos.
- **FR-007**: Nenhuma alteração em código de produção faz parte desta feature. Se
  algum teste reprovar contra o código atual, isso é achado a reportar, não
  autorização para alterar o comportamento.

### Key Entities

- **Registro de origem**: uma linha vinda de planilha ou currículo, com título e
  participantes. Dois registros com o mesmo título podem descrever o mesmo
  trabalho visto de ângulos diferentes.
- **Iniciativa**: o que o catálogo guarda. Projetos e orientações são espécies
  distintas, e a diferença entre elas é justamente o que a proteção precisa
  respeitar.
- **Participante**: pessoa vinculada a uma iniciativa, com papel. É o que se
  perde quando duas entidades são fundidas indevidamente, e o que os testes
  existem para proteger.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Removendo a restrição do código de produção, **pelo menos um teste
  reprova** — verificado experimentalmente, não presumido.
- **SC-002**: Com o código atual, **100% dos novos testes passam**.
- **SC-003**: Os novos testes concluem em **menos de 5 segundos**, sem banco nem
  rede, de modo que rodem em toda execução da suíte.
- **SC-004**: A suíte cobre as **duas** regras — orientações nunca casam por nome
  aproximado, projetos sempre casam —, de forma que nenhuma das duas possa ser
  quebrada sem reprovação.
- **SC-005**: Nenhum teste existente muda de resultado.

## Assumptions

- A correção que motivou esta proteção já está aplicada; a feature protege o
  comportamento atual, não o altera.
- Fixar o comportamento em nível de unidade é suficiente e preferível: o defeito
  original era determinístico e reproduzível sem banco, e a alternativa — depender
  de execução completa do pipeline — foi justamente o que permitiu o dano passar.
- A distinção entre projeto e orientação continuará expressa por tipo de entidade.
  Se um dia deixar de ser, estes testes reprovam, o que é o comportamento desejado.
- Os demais defeitos observados na mesma investigação — pessoas duplicadas,
  orientações com tipo trocado, grupos compartilhando endereço de origem — estão
  fora do escopo.
