# Phase 0 — Research: Correção da falha da fase de enriquecimento

**Feature**: `004-fix-enrichment-transaction`
**Date**: 2026-08-24

Todas as afirmações abaixo foram verificadas empiricamente neste repositório, no
`.venv` do projeto (Python 3.14.4, SQLAlchemy 2.0.52) e, onde indicado, também
dentro da imagem Docker (Python 3.12.13, SQLAlchemy 2.0.51).

---

## D1 — Causa raiz da falha

**Decisão**: A falha é o `self._session.begin()` explícito em
`src/core/logic/project_enrichment.py:401`, executado depois que a sessão já
possui uma transação aberta.

**Rationale**: No SQLAlchemy 2.0 a `Session` faz *autobegin* em qualquer
`execute()`, **inclusive `SELECT`**. O método `run()` executa três carregamentos
de índice antes da linha 401 (`_load_code_index`, `_load_research_project_names`,
`_load_current_descriptions`), e o primeiro deles já abre a transação. O
`run_migrations()` chamado por `ensure_schema()` faz `commit()` próprio e deixa a
sessão limpa, mas os SELECTs seguintes a reabrem.

Reprodução mínima:

```
in_transaction após SELECT: True
InvalidRequestError: A transaction is already begun on this Session.
```

**Determinismo**: o `begin()` é incondicional no caminho não-`dry_run` e ocorre
antes de qualquer verificação sobre a existência de documentos. Falha com 342
documentos e falha com zero. Isso é o que explica a fase nunca ter funcionado.

**Não é diferença de ambiente**: reproduzido idêntico em 2.0.52 (venv) e 2.0.51
(imagem Docker). *Autobegin* não é novidade de patch — é comportamento base da
`Session` desde a linha 1.4/2.0.

**Evidência independente**: o registro de execução em `ingestion_runs` do banco
atual traz `source_system='sigpesq_project_files'`, `status='failed'`,
`notes='A transaction is already begun on this Session.'`, e
`SELECT COUNT(*) FROM initiatives WHERE enrichment_json IS NOT NULL` retorna 0.

**Alternatives considered**: diferença de versão do SQLAlchemy (descartada pela
reprodução cruzada); estado sujo do banco (descartada — falha com banco recém
criado); dados de entrada malformados (descartada — falha com zero arquivos).

---

## D2 — Forma da correção

**Decisão**: Remover o `begin()` explícito e operar sobre a transação ambiente,
com `self._session.commit()` no sucesso e `self._session.rollback()` na exceção.

**Rationale**: É a menor mudança que restaura o comportamento pretendido sem
alterar regra de negócio. As escritas passam a integrar a transação que os SELECTs
já abriram — continua sendo uma unidade só. Verificado que os `SAVEPOINT` de
`_write_row` (`begin_nested`) seguem funcionando aninhados na transação ambiente:
numa execução com três linhas, a linha defeituosa foi descartada e as duas íntegras
persistiram.

**Alternatives considered**:

| Alternativa | Por que foi rejeitada |
|---|---|
| `rollback()` antes do `begin()` original | Frágil: qualquer `SELECT` inserido entre as duas chamadas reintroduz o defeito, de forma silenciosa e idêntica. |
| Guard `if not self._session.in_transaction()` | Esconde a intenção; deixa o código dependente de estado implícito e igualmente sujeito a reordenação. |
| Mover `ensure_schema()` para fora de `run()` | Conserta a fronteira de verdade, mas mexe em mais lugares e colide com a discussão de adotar ferramenta de migração. Registrado como follow-up (ver D5). |

---

## D3 — ACHADO CRÍTICO: a atomicidade prometida não existe hoje com SQLite

**Descoberta**: a garantia "todas as escritas de uma execução numa única
transação, com rollback total em caso de falha" (**FR-004** da especificação)
**não se sustenta** no banco SQLite atual — e isso é independente da correção
deste trabalho.

**Evidência**: isolando o comportamento em dois cenários idênticos exceto pelo
uso de `SAVEPOINT`:

```
INSERT direto (sem savepoint)  : linhas após rollback = 0    ← rollback funciona
INSERT dentro de SAVEPOINT     : linhas após rollback = 1    ← rollback NÃO desfaz
```

**Causa**: é o comportamento legado documentado do driver `pysqlite`. Ele emite
`BEGIN` implicitamente apenas antes de instruções DML, e **não** considera
`SAVEPOINT` como DML. Resultado: quando o primeiro comando da transação é um
`SAVEPOINT`, a conexão ainda está em autocommit no nível do banco, o próprio
`SAVEPOINT` abre a transação e o `RELEASE` correspondente **confirma** a escrita.
O `rollback()` posterior não tem mais o que desfazer.

**Alcance no código real**: confirmado que o engine da aplicação não aplica
nenhuma mitigação — `eo_lib/infrastructure/database/postgres_client.py:37` faz
`create_engine(db_url, echo=False)`, sem `isolation_level` nem listener de
`BEGIN`. Como **todas** as gravações de linha do loader passam por `_write_row`
(portanto por `SAVEPOINT`), na prática cada linha é confirmada individualmente.

**Consequência prática**: se `run()` falhar no meio (por exemplo em
`_record_tracking`, que fica fora do savepoint, ou durante `_ingest_new`), as
linhas já gravadas **permanecem** no banco. Não há gravação parcial hoje apenas
porque nada chega a ser gravado.

**Decisão**: **fora do escopo deste trabalho**, registrado como follow-up. A
correção do D2 não cria nem agrava esse problema — ela apenas o torna alcançável
pela primeira vez, já que hoje a fase aborta antes de escrever qualquer coisa.

**Rationale para adiar**: a mitigação padrão exige configurar o engine
(`isolation_level=None` mais listener emitindo `BEGIN`), e esse engine é criado
dentro da dependência externa `eo_lib`, sendo compartilhado por todos os flows do
projeto. Alterar isso pela borda afetaria ingestão de SigPesq, Lattes, CNPq e o
hook de anonimização LGPD — um raio de impacto incompatível com o escopo "só a
correção da transação" definido para esta branch.

**Impacto na especificação**: a **FR-004** não será integralmente satisfeita ao
final deste trabalho. Ver a seção *Complexity Tracking* do plano — requer decisão
explícita antes da implementação.

**Alternatives considered**:

| Alternativa | Avaliação |
|---|---|
| Configurar o engine no `eo_lib` | Correto, porém fora de escopo e em dependência externa. |
| Registrar listeners de `BEGIN` sobre o engine obtido da sessão | Tecnicamente viável a partir do nosso código, mas altera o comportamento transacional de **todo** o aplicativo como efeito colateral de uma correção pontual. |
| Emitir uma DML trivial antes do primeiro savepoint | Gambiarra: depende de detalhe do driver e não se autoexplica no código. |
| Abandonar os `SAVEPOINT` e tratar erro de linha em memória | Mudaria a semântica de "pular linha defeituosa", que é requisito (**FR-005**). |

---

## D4 — Estratégia de teste sem banco real

**Decisão**: exercitar `run()` com `dry_run=False` contra um SQLite em memória,
injetando a sessão no loader sem instanciar o `InitiativeController` real.

**Rationale**: `ProjectEnrichmentLoader.__init__` instancia
`InitiativeController()`, que conecta ao banco configurado em `DATABASE_URL` — um
teste não pode depender disso. Como `_session` é uma *property* que apenas navega
`controller._service._repository._session`, basta construir a instância com
`__new__` e montar essa cadeia com um objeto simples. Verificado empiricamente:

```
loader._session é a sessão injetada: True
```

**Esquema mínimo necessário**: `initiatives`, `initiative_types`,
`schema_migrations`, mais `source_records` e `attribute_assertions` (consultadas
pelo `_load_code_index`). A migração `0001` cria a coluna `enrichment_json`, então
a tabela `initiatives` deve ser criada **sem** ela, exercitando também o
`ensure_schema()`.

**Simplificação verificada**: `_record_tracking` começa com
`if not tracking_recorder.has_active_run(): return`. Sem contexto de execução
ativo, o teste não precisa montar nada de rastreamento.

**Escopo do teste**: `ingest_new=False`. O caminho de criação de novas iniciativas
usa a entidade ORM `Initiative` do `eo_lib` e exigiria replicar o mapeamento
completo — desproporcional para cobrir a regressão em questão.

**Autossuficiência**: os documentos `PJ_*.json` de entrada são criados pelo
próprio teste em `tmp_path`, sem depender de nenhum arquivo externo ao
repositório.

**Alternatives considered**: teste de integração contra `db/horizon.db` (rejeitado
— depende de estado de máquina e viola a autossuficiência exigida pela FR-010);
*mock* da sessão (rejeitado — um mock não teria reproduzido o defeito, que é
justamente comportamento real do SQLAlchemy).

---

## D5 — Onde o teste deve morar

**Decisão**: arquivo novo `tests/test_project_enrichment_db.py`.

**Rationale**: `tests/test_project_enrichment.py` declara na primeira linha que
cobre *"the pure (DB-free) logic"*. Acrescentar ali um teste que monta banco
contradiz o contrato do arquivo. A separação também deixa explícito, para quem
ler a suíte depois, que existe uma camada de cobertura com banco.

---

## D6 — Portão de qualidade

**Decisão**: validar com `make ci-check`.

**Rationale**: a constituição do projeto (seção *Development Workflow & Quality
Gates*) define `make ci-check` como portão mínimo antes de qualquer merge.
Verificado no Makefile que o alvo expande para `format-check lint test`
(black + isort, flake8 e pytest). Estilo: black com 88 colunas, isort com perfil
black.

**Observação**: a constituição menciona também verificação de tipos (mypy) como
parte do `ci-check`, mas o alvo real do Makefile não a executa. Divergência
registrada aqui como observação; corrigi-la está fora do escopo desta branch.

---

---

## Decisão registrada da tarefa T004 (2026-08-24)

**Decisão**: manter o **escopo estreito**. A limitação de atomicidade descrita em
D3 permanece fora desta branch e é tratada como follow-up.

**Como foi decidida**: a alternativa de ampliar o escopo exigiria retornar ao
planejamento, porque mudaria o desenho da solução. A implementação foi acionada
diretamente, o que confirma o caminho recomendado no plano. A **FR-004** fica,
portanto, **parcialmente atendida** ao final deste trabalho: o rollback existe e é
acionado corretamente, mas o driver de banco confirma cada `SAVEPOINT` liberado,
de modo que gravações de linhas já processadas podem sobreviver a uma falha
posterior na mesma execução.

**Consequência a comunicar**: esta é uma limitação preexistente, não introduzida
aqui. Ela só passa a ser observável porque a fase, pela primeira vez, chega a
gravar algo.

---

## Follow-ups identificados (fora do escopo desta branch)

1. **Atomicidade real das gravações** (D3) — decidir entre configurar o engine ou
   documentar formalmente a limitação, revisando a FR-004.
2. **Fronteira transacional do `ensure_schema()`** (D2) — mover a execução de
   migrações para a subida do aplicativo, junto da eventual adoção de Alembic.
3. **Divergência constituição × Makefile** quanto à verificação de tipos (D6).
