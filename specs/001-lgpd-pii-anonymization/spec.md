# Feature Specification: Anonimização de Dados Pessoais (LGPD)

**Feature Branch**: `001-lgpd-pii-anonymization`

**Created**: 2026-05-16

**Status**: Draft

**Input**: User description: "aplique anomizacao do cpf, telefone e email das pessoas nos arquvos exportados e no banco de dados, obedecendo a lgpd"

**Revisions**:
- 2026-09-21 — **Security review**: substitui SHA-256 com salt público/fixo por **HMAC-SHA256 com chave secreta** (padrão private-key/public-key; a chave privada é uma variável secreta de ambiente `HORIZON_PII_HMAC_KEY`). FR-005/FR-007 e Assumptions revisados; adicionados requisitos de gestão de chave (FR-008 a FR-010).

## Clarifications

### Session 2026-05-16

- Q: Como a operação de anonimização no banco de dados (US2) é acionada? → A: Anonimização ocorre na camada de persistência, ao salvar os dados — CPF, telefone e e-mail são anonimizados antes de serem gravados. US2 (backfill) cobre dados já existentes no banco.
- Q: Telefone deve ser anonimizado também? → A: Sim — CPF, e-mail e telefone (escopo original completo).
- Q: Consistência da anonimização no backfill — mesmo CPF → mesmo valor mascarado ou independente por linha? → A: Consistente — mesmo CPF produz sempre o mesmo valor mascarado (hash determinístico). Garante rastreabilidade interna sem revelar valor original.
- Q: Escopo de tabelas — apenas `persons` ou todas as tabelas com campos pessoais? → A: Todas as tabelas que contenham CPF, telefone ou e-mail, com descoberta automática dos campos no schema.
- Q: CPF inválido (formato incorreto) ao salvar — anonimizar, rejeitar ou logar? → A: Anonimizar mesmo assim — qualquer string é tratada como entrada opaca pelo anonimizador, independente de validade de formato.

### Session 2026-09-21 (Security Review)

- Q: A anonimização atual (SHA-256 + salt fixo versionado) é segura? → A: Não. O salt é público no repositório — qualquer leitor reconstroi o mapeamento via brute-force sobre CPF/e-mail de baixa entropia. É segurança por obscuridade, não tratamento adequado de dados pessoais.
- Q: Qual a lógica segura a adotar? → A: Padrão private-key/public-key: **HMAC-SHA256 com chave secreta de ambiente** (chave privada = `HORIZON_PII_HMAC_KEY`). Algoritmo, formato dos tokens e labels de domínio são públicos; a segurança depende exclusivamente da chave secreta (princípio de Kerckhoffs).
- Q: A deduplicação e a idempotência continuam funcionando? → A: Sim. Com a MESMA chave, o mesmo valor gera o mesmo token; os prefixos/sufixos de identificação (`LGPD-`, `@anon.lgpd`) não mudam, então backfill e guards permanecem válidos.
- Q: Rotação da chave? → A: Trocá-la altera todos os tokens já persistidos (perde o determinismo histórico). Política: chave de longa duração, gerada com alta entropia e com cópia segura no secret manager; rotação coordenada documentada.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Exportação de Arquivos com Dados Anonimizados (Priority: P1)

Um operador de dados exporta arquivos do sistema (CSV, relatórios, JSON) e recebe os dados com CPF, telefone e e-mail anonimizados. Como os dados já são persistidos anonimizados, o arquivo reflete o estado do banco.

**Why this priority**: Cumprir a LGPD exige que dados pessoais não sejam expostos em exportações. Como a anonimização ocorre na persistência, as exportações são conformes por construção.

**Independent Test**: Executar um flow de ingestão, exportar os dados e verificar que nenhum CPF ou e-mail legível aparece no arquivo resultante.

**Acceptance Scenarios**:

1. **Given** um flow de ingestão persiste registros com CPF, telefone e e-mail, **When** o arquivo exportado é gerado, **Then** os campos CPF, telefone e e-mail aparecem anonimizados (ex.: `***.***.***-**`, `***@***.***`)
2. **Given** um registro não possui CPF ou e-mail preenchido, **When** o arquivo é exportado, **Then** o campo vazio permanece vazio sem erro

---

### User Story 2 - Backfill de Dados Existentes no Banco (Priority: P2)

Um administrador aplica anonimização nos dados pessoais (CPF, e-mail) já armazenados no banco, de forma controlada e auditável, para conformidade com LGPD em registros anteriores à implementação desta feature.

**Why this priority**: Dados ingeridos antes da implementação desta feature estão em texto claro no banco. O backfill elimina esse risco residual. É uma operação pontual, não recorrente.

**Independent Test**: Executar o processo de backfill para um conjunto de registros existentes e verificar que os campos CPF, telefone e e-mail foram substituídos por valores anonimizados sem perda de integridade referencial.

**Acceptance Scenarios**:

1. **Given** registros existentes no banco com CPF, telefone e e-mail em texto claro, **When** o processo de backfill é executado via `make` target / CLI, **Then** os campos são substituídos por valores mascarados irreversíveis
2. **Given** o backfill foi executado, **When** o sistema gera relatório de auditoria, **Then** o relatório registra quais registros foram anonimizados, quando e quantos
3. **Given** o backfill está em andamento e ocorre falha parcial, **When** a operação é interrompida, **Then** os registros já processados permanecem anonimizados e os não processados permanecem inalterados; o relatório indica o ponto de falha

---

### Edge Cases

- CPF inválido ou incompleto ao persistir: anonimizado mesmo assim — o anonimizador trata qualquer string como entrada opaca, sem validação de formato.
- Registros duplicados no banco durante o backfill: anonimização é consistente — mesmo CPF, telefone ou e-mail produz sempre o mesmo valor mascarado com a mesma chave secreta (HMAC determinístico), garantindo que duplicatas convergem para o mesmo valor mascarado.
- O que acontece com dados pessoais em campos de texto livre (ex.: observações que contêm CPF escrito manualmente)? — Fora do escopo desta feature (ver Assumptions)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE anonimizar os campos CPF, telefone e e-mail **antes de persistir** qualquer registro no banco de dados, em todas as tabelas que contenham esses campos — a anonimização ocorre na camada de persistência, não como passo pós-carga
- **FR-002**: O sistema DEVE oferecer operação de backfill (via `make` target ou CLI) que descobre automaticamente todas as tabelas com colunas CPF, telefone ou e-mail e anonimiza os registros existentes persistidos antes desta feature
- **FR-003**: O sistema DEVE registrar em log de auditoria cada execução do backfill, incluindo: data/hora, quantidade de registros processados, quantidade anonimizados e resultado (sucesso/falha)
- **FR-004**: O sistema DEVE manter a integridade referencial dos registros após anonimização — chaves, relacionamentos e campos não-pessoais permanecem inalterados
- **FR-005**: O sistema DEVE garantir que a anonimização seja **computacionalmente irreversível sem a chave secreta** — o mapeamento original→token só pode ser reproduzido por quem detém a chave (construção HMAC-SHA256 keyed). A chave secreta é variável de ambiente (`HORIZON_PII_HMAC_KEY`), nunca versionada no repositório
- **FR-007**: A função de anonimização DEVE ser determinística para uma MESMA chave — o mesmo valor de entrada (CPF, telefone ou e-mail) com a mesma chave secreta produz sempre o mesmo valor mascarado, de modo que registros duplicados convergem para representação idêntica. Construção: `HMAC-SHA256(subchave_domínio, valor)`, truncada para o formato de token
- **FR-008**: O sistema DEVE ler a chave secreta de anonimização de variável de ambiente / secret manager (`HORIZON_PII_HMAC_KEY`); na ausência da chave, a anonimização DEVE falhar de forma explícita — sem fallback silencioso para hash sem chave
- **FR-009**: A chave secreta DEVE ser gerada com alta entropia (≥ 32 bytes aleatórios, ex.: `secrets.token_urlsafe(32)`) e armazenada fora do repositório (`.env` local / secret manager); um placeholder documentado DEVE existir em `.env.example` sem valor real
- **FR-010**: A rotação da chave DEVE ser documentada com seu impacto: trocar a chave altera todos os tokens persistidos e quebra o determinismo histórico; a política é tratar a chave como de longa duração, com backup seguro no secret manager e rotação coordenada apenas quando necessária
- **FR-006**: O sistema DEVE processar registros com CPF, telefone ou e-mail ausentes ou nulos sem gerar erros, mantendo o campo como nulo

### Key Entities *(include if feature involves data)*

- **Titular**: Pessoa física cujos dados pessoais (CPF, telefone e e-mail) são sujeitos à anonimização; identificada por ID interno no banco
- **Campo Pessoal**: Coluna nomeada `cpf`, `phone`/`telefone` ou `email` em qualquer tabela do banco — descobertos automaticamente via inspeção do schema
- **Registro Anonimizado**: Linha em qualquer tabela onde campos pessoais foram substituídos por valores mascarados irreversíveis
- **Log de Auditoria**: Registro imutável de cada execução de backfill, contendo data/hora, tabelas processadas, quantidade de registros por tabela e resultado

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% dos registros persistidos após a implementação não contêm CPF, telefone ou e-mail legíveis no banco — verificável por consulta direta à tabela `persons`
- **SC-002**: O backfill é concluído sem falhas para 100% dos registros-alvo em uma execução controlada em banco de desenvolvimento
- **SC-003**: O backfill processa 10.000 registros em no máximo 10 minutos, sem degradação de outros serviços em operação paralela
- **SC-004**: A conformidade com LGPD é verificável por relatório de auditoria que demonstra rastreabilidade completa das operações de backfill

## Assumptions

- Campos de texto livre (ex.: observações, comentários) que possam conter dados pessoais escritos manualmente estão fora do escopo desta feature; somente campos estruturados (CPF, telefone, e-mail) são cobertos
- O sistema descobre automaticamente todas as tabelas e colunas com campos pessoais (CPF, telefone, e-mail) via inspeção do schema do banco — não há lista fixa de tabelas
- A anonimização é **pseudonimização keyed**: computacionalmente irreversível SEM a chave secreta; quem detém a chave consegue reproduzir o mapeamento (necessário para auditoria e deduplicação). Não é anonimização irreversível no sentido estrito — é o modelo private-key/public-key em que a chave privada é variável secreta de ambiente
- O salt público fixo anterior (`b":horizon-lgpd-v1"`) é substituído por chave secreta; algoritmo, formato dos tokens e labels de domínio são públicos (princípio de Kerckhoffs)
- Os arquivos exportados refletem o estado do banco; como os dados são anonimizados na persistência, as exportações são conformes por construção
- Dados de teste e ambientes não-produção seguem a mesma política de anonimização
- O formato de mascaramento padrão é: CPF → `***.***.***-**`, telefone → `(**) *****-****`, e-mail → `***@***.***`
- O backfill é uma operação pontual e manual (não recorrente); novos registros são anonimizados automaticamente na camada de persistência
