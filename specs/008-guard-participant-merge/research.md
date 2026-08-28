# Research: proteger participantes contra fusão por nome

**Feature**: 008-guard-participant-merge | **Data**: 2026-08-28

## R1 — Que nível de teste teria pego o defeito

**Decisão**: duas camadas — resolvedor (unidade) e consequência (`_process_row`
com colaboradores mockados). Nenhum teste com banco.

**Racional**: o defeito era **determinístico e sem dependência de estado**: dado
um índice normalizado contendo uma orientação, `_resolve_existing_initiative`
devolvia essa orientação para outra orientação de mesmo título. Reproduzir isso
não exige banco, arquivo nem rede — exige apenas montar o índice e chamar a
função. O fato de o defeito ter sido descoberto por uma execução de 75 minutos é
acidente histórico, não necessidade técnica.

**Por que a camada de consequência é obrigatória**: os 283 testes existentes
falharam justamente por só cobrirem a primeira camada. Um teste que verifica "a
função devolveu `None`" prova que o mecanismo mudou; ele **não** prova que
nenhuma orientação foi absorvida por outra. A segunda camada afirma o que
importa: a segunda orientação de mesmo título chega ao handler com
`existing_initiative=None`, ou seja, **vira linha nova**.

**Alternativas descartadas**:

- *Teste de integração com SQLite em memória.* Reproduziria o cenário completo,
  incluindo os vínculos de participante — mas `ProjectLoader.__init__` instancia
  sete controllers presos a uma sessão global do `eo_lib`, e o schema vem de
  bibliotecas externas. O custo de montar isso é alto e o resultado seria frágil
  a mudanças de biblioteca, sem cobrir nada que as duas camadas não cubram.
- *Verificar contagem de `advisorship_members` após execução do pipeline.* É como
  o defeito foi achado, e é justamente o que não serve como rede de proteção:
  leva mais de uma hora e ninguém roda antes de um commit.

## R2 — Como instanciar o `ProjectLoader` sem o banco

**Decisão**: `ProjectLoader.__new__(ProjectLoader)` e atribuição direta dos
colaboradores necessários, seguindo o padrão que `tests/test_project_loader_matching.py`
já usa nos dois testes existentes.

**Racional**: `__init__` cria `InitiativeController`, `PersonController`,
`TeamController`, `ResearchGroupController`, `AdvisorshipController`,
`FellowshipController` e mais — todos ligados à sessão global. `__new__` pula
isso; o teste fornece só o que o caminho exercitado toca.

**Colaboradores que `_resolve_existing_initiative` exige**: `adv_controller` e
`controller` (usados por `_candidate_matches_model` e
`_lookup_existing_by_exact_name`).

**Colaboradores que `_process_row` exige**, levantados por leitura do método:
`mapping_strategy`, `handlers`, `entity_manager`, `initiative_type`, `org_id`,
`linker`, e o `controller` para a busca exata. O `tracking_recorder` é módulo
global e retorna cedo sem contexto de ingestão ativo — não precisa de mock, mas o
teste não deve depender disso silenciosamente (ver R4).

## R3 — Como distinguir projeto de orientação nos mocks

**Decisão**: `MagicMock(spec=Advisorship)` para orientações; `MagicMock()` simples
para projetos.

**Racional**: `_candidate_matches_model` decide por `isinstance(candidate, Advisorship)`
e, em caso negativo, consulta `adv_controller.get_by_id`. Com `spec=Advisorship`,
o `isinstance` responde verdadeiro sem tocar no controller — é o mecanismo que os
testes existentes já usam (`MagicMock(spec=Advisorship)` na linha 18 do arquivo).
Para projetos, `adv_controller.get_by_id` deve devolver `None`.

## R4 — O risco de um teste que passa pelo motivo errado

**Decisão**: incluir o experimento da SC-001 como tarefa explícita — desfazer a
restrição no código de produção, confirmar que a suíte reprova, e **restaurar**.

**Racional**: este é o ponto central da feature. Um teste de regressão que nunca
foi visto reprovando pode estar passando por acidente — mock mal montado, caminho
não exercitado, asserção que sempre vale. Foi exatamente o que aconteceu com os
283 testes existentes: passavam, e não protegiam nada.

O experimento é barato — uma linha comentada, `pytest`, descomentar — e é a única
evidência de que a rede funciona. Sem ele, a feature entrega a **sensação** de
proteção.

## R5 — Escopo: o que estes testes deliberadamente NÃO cobrem

Registrado para que a ausência não seja lida como esquecimento:

- **A perda de vínculos em si.** Os testes afirmam que duas entidades permanecem
  duas; não contam `advisorship_members`. A perda de vínculo é *consequência* da
  fusão, e barrar a fusão basta.
- **As 101 orientações com título repetido** que hoje existem no catálogo. São
  legítimas sob a regra atual e continuam existindo; a feature protege a regra,
  não muda o dado.
- **As outras dimensões de duplicata** encontradas na mesma investigação —
  pessoas duplicadas, orientações com tipo trocado, grupos compartilhando
  endereço de origem. Cada uma tem causa própria e escopo próprio.
