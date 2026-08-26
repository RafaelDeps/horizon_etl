# Feature Specification: Preservar origem e necessidade de revisão das iniciativas criadas a partir de documentos

**Feature Branch**: `006-preserve-review-origin`

**Created**: 2026-08-25

**Status**: Draft

**Input**: User description: "Preservar a marca de origem e de necessidade de revisão das iniciativas criadas automaticamente a partir de documentos, separando 'de onde esta iniciativa veio' de 'como este documento casou nesta execução'."

## Contexto

O enriquecimento de projetos cria automaticamente iniciativas a partir de
documentos que não correspondem a nenhum projeto existente. Foram **47** desses.
Por virem de extração automática, sem conferência humana, cada um recebe uma
marca de que precisa de revisão.

Essa marca **se apaga**. Numa segunda execução sobre o mesmo banco, as iniciativas
recém-criadas já existem e passam a corresponder por título exato — uma forma
confiável — de modo que a marca é reescrita como se o registro fosse confiável. A
contagem cai de **96 para 49**: exatamente os 47 criados.

A causa é a mistura de dois conceitos num único registro. *"Como este documento
correspondeu nesta execução"* é uma informação da execução corrente e muda a cada
rodada, legitimamente. *"Esta iniciativa nasceu de um documento extraído
automaticamente"* é um fato histórico e não muda nunca. Hoje o segundo é derivado
do primeiro, então some.

### Severidade real

O defeito é **latente hoje**, e é importante não superdimensioná-lo. A execução
semanal reconstrói o banco do zero antes de rodar, e o enriquecimento acontece uma
única vez por rodada — nas três execuções semanais completas observadas, a
contagem foi 96 em todas. A erosão só apareceu ao executar a fase duas vezes
contra o mesmo banco, durante um teste de repetição.

Ele deixa de ser latente em dois cenários:

1. Alguém executa a fase isoladamente mais de uma vez — algo que acontece em
   diagnóstico e em correção pontual.
2. O pipeline deixa de reconstruir o banco a cada rodada.

Vale registrar que o ADR-002 promete idempotência, e reexecutar produzindo um
estado diferente contradiz essa promessa — o defeito é, portanto, também uma
divergência entre o comportamento e a documentação de arquitetura.

### Por que importa quando se manifesta

O ADR-002 justifica a criação automática dizendo que a extração automática é
ruidosa e que correspondências incertas **precisam ser auditáveis**. A marca de
revisão é o mecanismo dessa auditabilidade. Sem ela, projetos montados a partir de
um documento lido automaticamente, que ninguém conferiu, ficam indistinguíveis no
catálogo canônico dos projetos vindos da fonte oficial — e é esse catálogo que
alimenta o painel institucional.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A marca de revisão não desaparece sozinha (Priority: P1)

Como responsável pela qualidade do catálogo, quero que uma iniciativa criada
automaticamente continue marcada para revisão até que alguém a revise de fato,
para que a auditabilidade prometida não expire com o tempo.

**Why this priority**: É o defeito em si. Sem isso, a garantia de auditoria dura
apenas até a próxima execução.

**Independent Test**: Executar o enriquecimento duas vezes seguidas sobre o mesmo
conjunto de dados e verificar que a quantidade de iniciativas marcadas para
revisão não diminuiu.

**Acceptance Scenarios**:

1. **Given** uma iniciativa criada a partir de documento e marcada para revisão,
   **When** o enriquecimento é executado novamente e ela corresponde por título
   exato, **Then** ela continua marcada para revisão.
2. **Given** um conjunto com N iniciativas marcadas para revisão, **When** o
   enriquecimento é reexecutado sem mudança nos documentos, **Then** a quantidade
   marcada permanece N.
3. **Given** uma iniciativa que correspondeu por título aproximado, **When** o
   enriquecimento é reexecutado, **Then** ela permanece marcada para revisão.

---

### User Story 2 - A origem de uma iniciativa é permanente e legível (Priority: P1)

Como pessoa que consulta o catálogo ou o painel, quero saber se um projeto foi
criado automaticamente a partir de um documento, para poder pesar a confiança que
deposito naquele registro.

**Why this priority**: É o que dá sentido à US1. Preservar a marca sem dizer o
motivo resolveria o sintoma e manteria a confusão entre os dois conceitos.

**Independent Test**: Consultar uma iniciativa criada a partir de documento, após
várias execuções, e verificar que a origem continua registrada e distinguível da
forma de correspondência da execução corrente.

**Acceptance Scenarios**:

1. **Given** uma iniciativa criada a partir de documento, **When** ela é
   consultada após qualquer número de execuções, **Then** consta que sua origem é
   a criação a partir de documento.
2. **Given** a mesma iniciativa, **When** ela é consultada, **Then** também consta
   como o documento correspondeu na execução mais recente, sem que essa
   informação sobrescreva a origem.
3. **Given** o catálogo exportado, **When** ele é consumido, **Then** a origem é
   legível ali também, e não apenas no registro interno de auditoria.

---

### User Story 3 - Revisão humana é registrável e é o único jeito de limpar a marca (Priority: P2)

Como pessoa do laboratório encarregada de conferir esses registros, quero
registrar que revisei determinada iniciativa, para que ela deixe de aparecer como
pendente e a lista de pendências diminua conforme o trabalho avança.

**Why this priority**: Sem isso, a marca vira permanente e a lista de pendências
nunca diminui — o que, na prática, faria as pessoas ignorarem a marca.

**Independent Test**: Registrar a revisão de uma iniciativa, reexecutar o
enriquecimento e verificar que ela não volta a aparecer como pendente.

**Acceptance Scenarios**:

1. **Given** uma iniciativa marcada para revisão, **When** uma revisão humana é
   registrada, **Then** ela deixa de constar como pendente.
2. **Given** uma iniciativa já revisada, **When** o enriquecimento é reexecutado,
   **Then** ela **não** volta a ser marcada como pendente.
3. **Given** uma iniciativa revisada, **When** ela é consultada, **Then** sua
   origem continua registrada — revisar não apaga o histórico.

---

### Edge Cases

- **Iniciativas já afetadas**: registros que perderam a marca em execuções
  anteriores precisam ter a origem reconstruída a partir da trilha de auditoria,
  que a preservou.
- **Correspondência por título aproximado**: continua exigindo revisão, por ser
  incerta, independentemente da origem da iniciativa.
- **Correspondência ambígua** (mais de um projeto com o mesmo título): continua
  exigindo revisão.
- **Iniciativa de origem oficial** que passa a corresponder a um documento: recebe
  o enriquecimento, mas **não** é marcada como criada a partir de documento.
- **Banco reconstruído do zero**: o comportamento observável não muda, já que
  tudo é recriado na mesma execução.
- **Revisão registrada e documento depois alterado**: a revisão registrada
  permanece válida; reavaliar isso está fora do escopo.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A origem de uma iniciativa criada a partir de documento MUST ser
  registrada de forma permanente e independente da forma de correspondência da
  execução corrente.
- **FR-002**: A forma de correspondência da execução corrente MUST continuar sendo
  registrada, por ser informação útil de diagnóstico.
- **FR-003**: A necessidade de revisão MUST ser determinada pela origem e pela
  existência de revisão humana registrada, e **não** apenas pela forma de
  correspondência da execução corrente.
- **FR-004**: Reexecutar o enriquecimento sem alteração nos documentos MUST NOT
  reduzir a quantidade de iniciativas marcadas para revisão.
- **FR-005**: O sistema MUST permitir registrar que uma iniciativa foi revisada
  por uma pessoa.
- **FR-006**: Somente o registro de revisão humana MUST poder retirar a marca de
  pendência de uma iniciativa criada a partir de documento.
- **FR-007**: A origem MUST estar legível no catálogo exportado, e não apenas no
  registro interno de auditoria.
- **FR-008**: Correspondências incertas — título aproximado ou ambíguo — MUST
  continuar exigindo revisão.
- **FR-009**: O sistema MUST ser capaz de reconstruir a origem de iniciativas já
  afetadas, a partir da trilha de auditoria existente.
- **FR-010**: Registrar uma revisão MUST NOT apagar a origem da iniciativa.

### Key Entities

- **Iniciativa**: o projeto no catálogo canônico. Passa a carregar, de forma
  distinta: sua **origem**, a **forma de correspondência** da execução mais
  recente, e o **estado de revisão**.
- **Origem**: como a iniciativa passou a existir — criada a partir de documento,
  ou proveniente de fonte oficial. Fato histórico, imutável.
- **Forma de correspondência**: como o documento foi associado à iniciativa na
  execução corrente. Volátil por natureza.
- **Estado de revisão**: se uma pessoa já conferiu o registro, e quando.
- **Trilha de auditoria**: o histórico que já preserva quais iniciativas nasceram
  de documento, utilizável para reconstrução.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Executar o enriquecimento duas vezes seguidas sobre os mesmos dados
  mantém a quantidade de iniciativas marcadas para revisão **idêntica** — hoje
  ela cai de 96 para 49.
- **SC-002**: 100% das iniciativas criadas a partir de documento permanecem
  identificáveis como tal após qualquer número de execuções.
- **SC-003**: A origem de uma iniciativa é obtida diretamente do catálogo
  exportado, sem consultar registros internos de auditoria.
- **SC-004**: Após registrar a revisão de uma iniciativa, ela não reaparece como
  pendente em nenhuma execução seguinte.
- **SC-005**: As 47 iniciativas já afetadas têm a origem reconstruída, sem perda.
- **SC-006**: A quantidade de iniciativas pendentes de revisão diminui
  exclusivamente por revisão humana registrada.

## Assumptions

- A trilha de auditoria existente é confiável como fonte para reconstruir a
  origem de registros já afetados.
- O registro de revisão é feito por uma pessoa da equipe, por meio operacional
  simples; construir interface para isso está fora do escopo.
- A regra de negócio de correspondência — por código, título exato e título
  aproximado — permanece inalterada.
- O painel institucional consome o catálogo exportado; tornar a origem visível ali
  é responsabilidade de quem constrói o painel, e está fora do escopo.
- Mudanças no pipeline semanal e no orquestrador, a decisão sobre reconstruir ou
  não o banco a cada rodada, alterações em Docker e a biblioteca externa de coleta
  estão **fora do escopo**.
- As correções anteriores, de transação e de descoberta de anexos, permanecem
  inalteradas.
