# Feature Specification: Descoberta resiliente dos anexos de projeto do SigPesq

**Feature Branch**: `005-resilient-pdf-download`

**Created**: 2026-08-25

**Status**: Draft

**Input**: User description: "Tornar o download dos documentos de projeto do SigPesq resiliente à marcação do portal, corrigindo de dentro do horizon_etl, sem alterar a biblioteca agent_sigpesq."

## Contexto

A etapa que baixa os documentos de projeto conclui informando sucesso e não traz
**nenhum** arquivo. Para cada projeto examinado, ela registra que não há anexo e
segue adiante. O portal lista 371 projetos; o acervo de documentos está parado em
342 e não cresce.

O efeito é que projetos novos entram no catálogo sem descrição, objetivos ou
cronograma, e ninguém percebe — a etapa termina "bem". É o mesmo padrão do
defeito corrigido na branch anterior: **uma etapa que reporta sucesso sem fazer
nada**.

Investigação somente-leitura contra o portal estabeleceu:

- A área de anexos que a biblioteca procura **não existe** na página, em busca
  feita no documento inteiro, com a janela do projeto aberta, em cinco projetos.
- **Não é questão de espera**: medir imediatamente e medir após quase dez
  segundos dá o mesmo resultado.
- A janela do projeto **abre** normalmente.
- A biblioteca é byte a byte a mesma que, em 10/08/2026, produziu com sucesso os
  342 documentos existentes, com os mesmos parâmetros. Não é diferença de versão
  nem de uso.
- **Oito** dos projetos hoje reportados como sem anexo têm documento extraído de
  PDF real naquela data.

Duas leituras seguem em aberto, e o diagnóstico definitivo depende de examinar
dezenas de projetos — bloqueado porque o portal limita tentativas de acesso:

1. A marcação do portal mudou e a área de anexos existe com outro nome.
2. A área só aparece quando há anexo, e esses projetos realmente não têm arquivo
   hoje, tendo sido removidos do portal depois de agosto.

Esta especificação **não escolhe entre as duas**. Ela exige uma solução que
funcione corretamente em ambos os casos e que, principalmente, **passe a
distinguir os dois no relato** — porque hoje eles são indistinguíveis, e foi
exatamente isso que escondeu o problema.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Os documentos voltam a ser baixados (Priority: P1)

Como responsável pela operação do pipeline, quero que a etapa de download traga
os documentos dos projetos que possuem anexo no portal, para que o acervo volte a
crescer e projetos novos sejam enriquecidos.

**Why this priority**: É o objetivo do trabalho. Sem isso, o acervo permanece
congelado e o enriquecimento envelhece indefinidamente.

**Independent Test**: Apontar a rotina de descoberta para uma página que contenha
anexo e verificar que o anexo é localizado e trazido.

**Acceptance Scenarios**:

1. **Given** uma página de projeto cuja área de anexos usa a marcação conhecida,
   **When** a descoberta é executada, **Then** o anexo é localizado.
2. **Given** uma página de projeto cuja área de anexos usa marcação diferente da
   conhecida, **When** a descoberta é executada, **Then** o anexo é localizado
   mesmo assim.
3. **Given** um projeto com mais de um anexo, **When** a descoberta é executada,
   **Then** o documento escolhido é o do rótulo desejado, e não simplesmente o
   primeiro da lista.

---

### User Story 2 - Ausência de anexo deixa de se confundir com falha de leitura (Priority: P1)

Como pessoa que acompanha a execução, quero distinguir "este projeto não tem
anexo" de "não consegui reconhecer a área de anexos nesta página", para que uma
quebra de compatibilidade com o portal apareça imediatamente em vez de se
disfarçar de resultado normal.

**Why this priority**: Tão crítico quanto a US1. Sem essa distinção, a próxima
mudança do portal volta a passar despercebida por semanas — e é o que aconteceu
desta vez. Além disso, é o que permitirá encerrar o diagnóstico em aberto.

**Independent Test**: Executar a descoberta contra uma página sem anexo algum e
contra uma página cuja área de anexos não é reconhecível, verificando que os dois
casos produzem relatos distintos.

**Acceptance Scenarios**:

1. **Given** um projeto sem nenhum anexo, **When** a descoberta é executada,
   **Then** o relato diz que o projeto não possui anexo, e isso não é tratado
   como erro.
2. **Given** uma página em que a área de anexos não pôde ser reconhecida,
   **When** a descoberta é executada, **Then** o relato diz explicitamente que a
   estrutura não foi reconhecida, de forma distinguível do caso anterior.
3. **Given** uma execução completa, **When** ela termina, **Then** é apresentado
   um resumo com quantos projetos foram examinados, quantos tinham anexo, quantos
   não tinham e quantos não puderam ser interpretados.

---

### User Story 3 - O diagnóstico em aberto pode ser encerrado (Priority: P2)

Como responsável técnico, quero que uma execução contra o portal real responda
qual das duas leituras é a verdadeira, para decidir se o problema é de
compatibilidade ou se os anexos foram removidos.

**Why this priority**: Depende da US2 para existir e do portal liberar acesso.
Não bloqueia a entrega, mas é o que fecha a investigação.

**Independent Test**: Executar contra o portal varrendo dezenas de projetos,
incluindo os mais antigos, e ler o resumo.

**Acceptance Scenarios**:

1. **Given** uma varredura ampla, **When** ao menos um projeto tem anexo
   localizado, **Then** conclui-se que os anexos continuam existindo.
2. **Given** uma varredura ampla, **When** nenhum projeto tem anexo mas vários
   aparecem como não interpretáveis, **Then** conclui-se que houve quebra de
   compatibilidade.
3. **Given** uma varredura ampla, **When** todos aparecem como sem anexo e nenhum
   como não interpretável, **Then** conclui-se que os anexos foram removidos do
   portal.

---

### Edge Cases

- **Projeto sem anexo**: comportamento atual preservado — registra, pula e segue.
- **Área de anexos irreconhecível**: registrado de forma distinta, sem
  interromper o processamento dos demais projetos.
- **Vários anexos**: prevalece o rótulo desejado; havendo empate ou ausência do
  rótulo, o critério de escolha precisa ser explícito e registrado.
- **Anexo que não é PDF**: a extensão real do arquivo é preservada.
- **Documento já presente no disco**: continua sendo pulado, mantendo a
  retomabilidade.
- **Janela do projeto não abre**: continua sendo tratado como falha daquele
  projeto apenas.
- **Acesso ao portal recusado por excesso de tentativas**: a execução relata a
  condição de forma inequívoca, sem se confundir com ausência de anexos.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A localização do anexo MUST NOT depender de um identificador fixo
  específico da estrutura atual do portal.
- **FR-002**: A localização MUST reconhecer controles de download por
  características estáveis, de modo a funcionar tanto com a marcação conhecida
  quanto com variações dela.
- **FR-003**: Havendo mais de um anexo, o sistema MUST selecionar o do rótulo
  desejado, e o critério de desempate MUST ser explícito.
- **FR-004**: O sistema MUST relatar de forma distinguível os casos "sem anexo" e
  "área de anexos não reconhecida".
- **FR-005**: Ao final de uma execução, o sistema MUST apresentar um resumo com as
  contagens de projetos examinados, com anexo, sem anexo e não interpretáveis.
- **FR-006**: Um projeto que não pôde ser interpretado MUST NOT interromper o
  processamento dos demais.
- **FR-007**: A retomabilidade MUST ser preservada: documentos já obtidos não são
  buscados novamente.
- **FR-008**: A extensão original do arquivo obtido MUST ser preservada.
- **FR-009**: Toda a adaptação MUST residir no código deste repositório; a
  biblioteca externa NÃO PODE ser alterada.
- **FR-010**: A verificação MUST ser possível sem acesso ao portal, exercitando os
  três cenários — marcação conhecida, marcação alternativa e ausência de anexo.

### Key Entities

- **Projeto listado no portal**: item da relação de projetos, identificado por um
  código; pode ou não ter documento anexado.
- **Anexo**: arquivo disponibilizado na janela do projeto, com rótulo (por
  exemplo, "Projeto") e nome de arquivo próprio.
- **Resultado da inspeção de um projeto**: classificação em uma de quatro
  situações — anexo obtido, sem anexo, área não reconhecida, ou falha ao abrir.
- **Resumo da execução**: as contagens agregadas por situação.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Numa página que contenha anexo, a taxa de localização é de 100%,
  tanto na marcação conhecida quanto na alternativa — hoje é 0% em ambas.
- **SC-002**: Os três cenários de verificação são exercitáveis sem qualquer
  acesso ao portal, em menos de um minuto.
- **SC-003**: Numa execução, todo projeto examinado é classificado em exatamente
  uma das quatro situações, e a soma das contagens é igual ao número de projetos
  examinados.
- **SC-004**: Diante de uma quebra de compatibilidade, o relato identifica a
  condição já na primeira execução, sem exigir inspeção manual da página.
- **SC-005**: Uma varredura ampla contra o portal permite concluir qual das duas
  leituras é a verdadeira, sem ambiguidade.
- **SC-006**: Reexecutar sobre um acervo já obtido não busca nenhum documento
  novamente.

## Assumptions

- O acesso ao portal é limitado por tentativas, então a verificação principal é
  feita contra páginas locais que reproduzem os cenários; a validação contra o
  portal real é o passo final, condicionado à liberação do acesso.
- A biblioteca externa continuará a cuidar do acesso autenticado, da navegação e
  da paginação; apenas a localização do anexo dentro da janela do projeto é
  substituída.
- O rótulo de interesse permanece "Projeto", como hoje.
- Os 342 documentos já existentes permanecem válidos e não são reprocessados.
- A correção da transação concluída na branch anterior permanece inalterada.
- Mudanças no pipeline semanal, no orquestrador e a decisão de promover a
  extração para a execução semanal estão **fora do escopo**.
- Alterações em Docker estão **fora do escopo**.
