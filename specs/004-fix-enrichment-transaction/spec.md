# Feature Specification: Correção da falha da fase de enriquecimento de projetos

**Feature Branch**: `004-fix-enrichment-transaction`

**Created**: 2026-08-24

**Status**: Draft

**Input**: User description: "Corrigir a falha da fase enrich_projects no pipeline semanal, que termina com exit 1 e a exceção InvalidRequestError: A transaction is already begun on this Session."

## Contexto

A fase de enriquecimento de projetos do pipeline semanal falha de forma
determinística: ela aborta antes de processar qualquer documento, sempre, tanto
com centenas de documentos disponíveis quanto com nenhum. Por ser uma fase
classificada como não-crítica, o pipeline segue adiante e termina reportando
sucesso, de modo que a falha não é visível em nenhum resumo de execução — apenas
numa linha de erro perdida no meio de um log de aproximadamente uma hora.

O efeito para o negócio é que **nenhum projeto de pesquisa jamais recebeu o
enriquecimento** previsto no ADR-002: descrições continuam vazias onde havia
documento disponível, e os campos ricos (objetivo geral, objetivos específicos,
cronograma, linha de pesquisa, palavras-chave, área de conhecimento) nunca foram
persistidos para nenhuma iniciativa. A auditoria do banco confirma zero
iniciativas com dados de enriquecimento e um registro de execução de ingestão com
situação "falhou".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A fase de enriquecimento deixa de abortar (Priority: P1)

Como responsável pela operação do pipeline semanal, quando eu executo a carga
semanal, a fase de enriquecimento de projetos precisa executar até o fim e
reportar sucesso, em vez de abortar imediatamente com erro.

**Why this priority**: É a falha que motiva este trabalho. Sem isso, nenhuma das
demais capacidades tem qualquer efeito, porque a fase termina antes de tocar em
um único documento.

**Independent Test**: Executar a fase de enriquecimento isoladamente, com o banco
acessível, e verificar que ela conclui com situação de sucesso e que o registro
de execução de ingestão correspondente fica marcado como bem-sucedido.

**Acceptance Scenarios**:

1. **Given** o banco canônico acessível e nenhum documento de projeto disponível,
   **When** a fase de enriquecimento é executada, **Then** ela conclui com
   sucesso, não grava nada e informa que processou zero documentos.
2. **Given** o banco canônico acessível e documentos de projeto disponíveis,
   **When** a fase de enriquecimento é executada, **Then** ela conclui com
   sucesso e informa quantos documentos foram processados.
3. **Given** a fase de enriquecimento concluída com sucesso, **When** o resumo do
   pipeline semanal é apresentado, **Then** a fase aparece como bem-sucedida.

---

### User Story 2 - Os projetos passam a ser efetivamente enriquecidos (Priority: P1)

Como pesquisador ou gestor que consulta o catálogo institucional de projetos,
quero que os projetos cujos documentos foram processados tenham descrição
preenchida e os campos ricos disponíveis, para que o catálogo deixe de exibir
projetos sem qualquer descrição.

**Why this priority**: É o valor de negócio que justifica a existência da fase. A
correção só é útil se produzir o enriquecimento; concluir com sucesso sem gravar
nada seria um falso positivo.

**Independent Test**: Com um conjunto conhecido de documentos que casam com
iniciativas existentes, executar a fase e verificar que as descrições vazias
foram preenchidas e que os campos ricos ficaram disponíveis para consulta.

**Acceptance Scenarios**:

1. **Given** uma iniciativa sem descrição e um documento correspondente que traz
   descrição, **When** a fase é executada, **Then** a descrição da iniciativa
   passa a ser a do documento e os campos ricos ficam persistidos.
2. **Given** uma iniciativa que já possui descrição vinda de fonte autoritativa e
   um documento correspondente, **When** a fase é executada, **Then** a descrição
   existente é preservada e apenas os campos ricos são persistidos.
3. **Given** um documento processado com sucesso, **When** a proveniência é
   consultada, **Then** constam a origem do dado, a estratégia de
   correspondência utilizada e a marcação de necessidade de revisão quando
   aplicável.

---

### User Story 3 - A falha não pode voltar despercebida (Priority: P2)

Como pessoa desenvolvedora que mexe nesse código no futuro, quero que a suíte de
testes acuse imediatamente se a fase voltar a abortar, para que o defeito não
retorne e permaneça meses invisível como aconteceu desta vez.

**Why this priority**: O defeito sobreviveu justamente porque nenhum teste
exercita a fase contra um banco real — a cobertura existente é declaradamente
livre de banco de dados. Sem essa proteção, a correção é frágil.

**Independent Test**: Reverter a correção localmente e confirmar que a suíte de
testes falha; reaplicá-la e confirmar que a suíte passa.

**Acceptance Scenarios**:

1. **Given** a suíte de testes do projeto, **When** ela é executada, **Then**
   existe ao menos um teste que exercita o caminho de gravação da fase de ponta a
   ponta contra um banco temporário e ele passa.
2. **Given** o defeito reintroduzido no código, **When** a suíte é executada,
   **Then** ela falha apontando a fase de enriquecimento.
3. **Given** um ambiente recém-clonado do repositório, **When** a suíte é
   executada, **Then** o teste roda sem depender de nenhum arquivo ou serviço
   externo ao repositório.

---

### Edge Cases

- **Nenhum documento disponível**: a fase precisa concluir com sucesso e relatar
  zero documentos processados, sem gravar nada e sem sinalizar erro.
- **Diretório de documentos inexistente**: tratado como o caso anterior — zero
  documentos, execução bem-sucedida.
- **Documento malformado ou incompleto**: o documento é descartado e contabilizado
  como erro, sem impedir o processamento dos demais documentos da mesma execução.
- **Falha irrecuperável no meio da execução**: nenhuma gravação parcial pode
  permanecer no banco; o estado precisa voltar ao que era antes da execução.
- **Execução em modo simulação**: nenhuma gravação ocorre, e o relatório indica o
  que teria sido feito.
- **Reexecução**: rodar a fase repetidamente sobre os mesmos documentos produz o
  mesmo resultado, sem duplicar iniciativas nem divergir dos dados já gravados.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A fase de enriquecimento de projetos MUST concluir sem erro sempre
  que o banco canônico estiver acessível, independentemente de haver ou não
  documentos de projeto disponíveis.
- **FR-002**: A fase MUST persistir os campos ricos de todo documento que
  corresponda a uma iniciativa existente.
- **FR-003**: A fase MUST preencher a descrição de uma iniciativa somente quando
  ela estiver vazia, preservando descrições provenientes de fontes mais
  autoritativas, salvo quando a sobrescrita for explicitamente solicitada.
- **FR-004**: Todas as gravações de uma mesma execução MUST ser confirmadas como
  uma única unidade; em caso de falha irrecuperável, nenhuma gravação da execução
  pode permanecer.
- **FR-005**: Uma falha ao gravar um documento específico MUST descartar apenas
  aquele documento, contabilizá-lo como erro e permitir que os demais sigam sendo
  processados na mesma execução.
- **FR-006**: O modo de simulação MUST relatar o que seria feito sem realizar
  nenhuma gravação.
- **FR-007**: A fase MUST registrar a proveniência de cada enriquecimento
  aplicado, incluindo a estratégia de correspondência e a marcação de necessidade
  de revisão.
- **FR-008**: O registro de execução de ingestão MUST refletir a situação real da
  execução — bem-sucedida quando a fase conclui, malsucedida quando aborta.
- **FR-009**: A suíte de testes MUST cobrir o caminho de gravação da fase de ponta
  a ponta, de modo que a reintrodução do defeito seja detectada automaticamente.
- **FR-010**: O teste de cobertura MUST ser autossuficiente, construindo seus
  próprios dados de entrada e seu próprio banco temporário, sem depender de
  arquivos, serviços ou diretórios externos ao repositório.

### Key Entities

- **Documento de projeto**: representação estruturada de um plano de projeto,
  contendo código do projeto, título, descrição, objetivos, cronograma, linha de
  pesquisa, palavras-chave, área de conhecimento, datas e metadados de
  proveniência da extração.
- **Iniciativa**: o projeto de pesquisa no modelo canônico, alvo do
  enriquecimento; recebe descrição e o conjunto de campos ricos.
- **Registro de execução de ingestão**: o histórico de cada execução da fase, com
  situação e observações, usado para auditoria e diagnóstico.
- **Rastro de proveniência**: o conjunto de registros que liga um documento à
  iniciativa enriquecida, com estratégia de correspondência, confiança e
  necessidade de revisão.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fase de enriquecimento conclui com sucesso em 100% das execuções
  do pipeline semanal em que o banco está acessível — hoje esse número é 0%.
- **SC-002**: Numa execução com documentos correspondentes disponíveis, 100% dos
  documentos que casam com uma iniciativa resultam em enriquecimento persistido e
  consultável.
- **SC-003**: Numa execução em que uma parcela dos documentos está malformada, os
  documentos íntegros restantes são processados integralmente, e a contagem de
  erros informada é igual ao número de documentos malformados.
- **SC-004**: Após uma execução interrompida por falha irrecuperável, o número de
  registros alterados no banco é zero.
- **SC-005**: A reintrodução do defeito é detectada pela suíte de testes em menos
  de um minuto de execução, sem necessidade de subir banco, container ou serviço
  externo.
- **SC-006**: Executar a fase duas vezes seguidas sobre o mesmo conjunto de
  documentos produz o mesmo estado final, sem duplicação de iniciativas.

## Assumptions

- O banco canônico está acessível e com o esquema atualizado no momento da
  execução; indisponibilidade de banco é uma falha legítima e continua sendo
  reportada como erro.
- A ausência dos documentos de projeto no ambiente atual é uma condição conhecida
  e **fora do escopo** deste trabalho: a fase deve concluir com sucesso relatando
  zero documentos, e a origem desses arquivos será tratada separadamente.
- As garantias já existentes de correspondência (por código do projeto, título
  exato e título aproximado), de deduplicação e de idempotência descritas no
  ADR-002 permanecem inalteradas; este trabalho não redefine regras de negócio.
- A classificação da fase como não-crítica no pipeline semanal permanece como
  está; revisá-la é assunto separado.
- Mudanças em Docker (imagem, composição, reconstrução) estão **fora do escopo** e
  serão tratadas ao final, mediante solicitação explícita.
- A atualização da biblioteca de coleta do SigPesq e a geração automatizada dos
  documentos de projeto estão **fora do escopo** deste trabalho.
- Melhorias de visibilidade no orquestrador semanal (captura de saída das fases,
  registro em arquivo de log) estão **fora do escopo** deste trabalho.
