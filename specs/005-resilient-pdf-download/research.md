# Phase 0 — Research

**Feature**: `005-resilient-pdf-download`
**Date**: 2026-08-25

Tudo abaixo foi verificado — as sondas contra o portal foram somente-leitura, e a
prova de conceito da solução rodou offline, com páginas locais.

---

## D1 — O que está quebrado

> ⚠️ **Esta seção foi corrigida em 25/08 21:20.** A redação original afirmava que
> a biblioteca procurava um identificador "que não existe mais na página" e
> apontava para quebra de compatibilidade do portal. **Isso estava errado**, e a
> investigação posterior provou o contrário. O texto abaixo é a versão correta; o
> registro completo de como a conclusão mudou está em *Diagnóstico ENCERRADO*, no
> fim deste documento.

**Constatação**: a etapa reporta sucesso sem baixar nenhum documento, e não há
como saber, pelo relato dela, se isso ocorre porque os projetos não têm anexo ou
porque a página deixou de ser legível.

**Evidência** (busca no documento inteiro, modal aberto, 5 projetos):

```
linha 0..4: links imediato=0 | após espera=0 | tabela: (sem rptArquivo: TimeoutError)
```

**Interpretação correta dessa evidência**: o identificador `rptArquivo` não
aparece porque um `Repeater` do ASP.NET **não renderiza elemento algum quando não
tem itens**. A ausência do identificador é consequência de não haver anexo — não
prova de que o portal mudou. A leitura da biblioteca estava certa; o que faltava
era poder demonstrá-la.

**Corrida descartada**: medir na hora e medir após 8 s de espera pelo seletor mais
1,5 s de assentamento dá zero nos dois casos. Não é postback pendente.

**Não é versão nem uso**: o arquivo da estratégia é byte a byte idêntico ao
instalado em `horizon_etl_h`, que em 10/08 produziu os 342 documentos com os
mesmos parâmetros (`file_label="Projeto"`, `skip_existing=True`).

**Detalhe relevante**: o container `ContentPlaceHolder_ModalConsultaProjeto` não
existe com esse id exato, mas o painel real
(`ContentPlaceHolder_ModalConsultaProjeto_pnlModal`) existe, abre normalmente e
contém a seção "Arquivos" — vazia.

**O defeito real, então, não é de leitura da página: é de observabilidade.** Duas
situações de significado oposto — "não tem anexo" e "não sei ler esta página" —
produziam a mesma mensagem, e distingui-las exigiu cinco sondagens manuais ao
portal ao longo de horas. É isso que esta feature corrige.

**Alternatives considered**: corrida de renderização (descartada por medição);
diferença de versão da lib (descartada por comparação binária); quebra de
compatibilidade do portal (**considerada e depois refutada** — ver o fim deste
documento).

---

## D2 — Por que a solução não pode escolher entre as duas leituras

**Decisão**: implementar de modo correto sob ambas as leituras, e instrumentar
para que a execução revele qual é a verdadeira.

**Rationale**: fechar o diagnóstico exige varrer dezenas de projetos, incluindo os
mais antigos, e o portal recusou acesso após três tentativas em poucos minutos.
Esperar para só então projetar atrasaria sem necessidade: a instrumentação que
distingue "sem anexo" de "não reconheci" é valiosa em qualquer cenário, e é
justamente o que responde a pergunta.

**Consequência honesta**: se a leitura correta for "os anexos foram removidos do
portal", a US1 não muda nada na prática. O valor entregue passa a ser da US2 —
tornar essa conclusão visível em vez de disfarçada de execução normal.

---

## D3 — Estratégia de descoberta resiliente

**Decisão**: localizar o controle de download por **duas características
independentes**, e classificar o resultado em quatro situações.

Um controle é candidato quando:

1. o identificador contém `download`, `baixar` ou `arquiv` (sem diferenciar
   maiúsculas); **ou**
2. o texto visível termina em extensão de documento (`.pdf`, `.doc`, `.docx`,
   `.odt`).

O critério (1) sobrevive a renomeações do container porque em ASP.NET o nome do
controle costuma preservar o verbo; o (2) sobrevive mesmo a uma renomeação total,
porque o nome do arquivo aparece para o usuário.

**Distinguir ausência de incompatibilidade**: se não houver candidatos, olha-se se
existe **área de anexos** — algum cabeçalho, tabela ou bloco cujo texto inicial
mencione "Arquivo(s)". Havendo área e nenhum candidato → o projeto não tem anexo.
Não havendo área → a estrutura não foi reconhecida.

**Escolha entre vários anexos**: prevalece o candidato cujo texto seja exatamente
o rótulo desejado ("Projeto"); na ausência dele, o primeiro, e o fato de ter sido
por fallback é registrado.

**Prova de conceito** (offline, Playwright com páginas locais):

```
marcação ANTIGA    -> ANEXO  id=..._rptArquivo_Download_0   txt=Projeto  total=2  porRotulo=True
marcação NOVA      -> ANEXO  id=ctl00_..._lnkBaixar_1       txt=Projeto  total=2  porRotulo=True
SEM anexo          -> SEM_ANEXO
IRRECONHECÍVEL     -> NAO_RECONHECIDA
```

O caso "marcação NOVA" é o mais instrutivo: os anexos aparecem em ordem
diferente, e a escolha correta é o **índice 1**. A lógica antiga, que caía no
"primeiro da lista", teria baixado o *Parecer* em vez do *Projeto* — um erro
silencioso pior que a falha atual.

**Alternatives considered**: casar por XPath do container (frágil do mesmo jeito);
usar posição na tabela (frágil a reordenação); pedir a correção na biblioteca
(fora de cogitação — restrição do usuário; e dependeria de merge em outro
repositório).

---

## D4 — Onde a adaptação mora

**Decisão**: subclasse de `ProjectFilesDownloadStrategy` dentro de
`src/adapters/sources/sigpesq/`, sobrescrevendo apenas a inspeção de um projeto e
acrescentando as contagens.

**Rationale**: a restrição do usuário é inegociável — a biblioteca externa não
pode ser tocada. O repositório já tem o precedente de ajustar o `agent_sigpesq` a
partir do ETL, em `SigPesqAdapter._patch_browser_factory`. A subclasse é mais
segura que um patch em tempo de execução porque não depende de detalhes internos
do módulo importado: reaproveita login, navegação, paginação e retomabilidade da
lib, e substitui só o trecho que quebrou.

**Alternatives considered**: monkey-patch das constantes do módulo (funcionaria,
mas altera comportamento global e é invisível para quem lê o código); reescrever
a estratégia inteira (jogaria fora paginação e retomabilidade já testadas).

---

## D5 — Verificação sem o portal

**Decisão**: testes com Playwright carregando HTML local via `set_content`.

**Rationale**: exercita o mesmo motor de navegador e as mesmas consultas ao DOM
que rodarão em produção, sem rede e sem consumir tentativas de acesso ao portal.
Os quatro cenários rodaram em poucos segundos na prova de conceito.

**Alternatives considered**: simulacro (`mock`) da página — rejeitado, porque o
defeito atual é precisamente sobre o DOM real e um simulacro reproduziria as
suposições erradas; teste apenas contra o portal — impossível pelo limite de
acesso, e lento demais para servir de rede de segurança.

---

## Follow-ups

1. **Encerrar o diagnóstico** (US3): varredura ampla quando o portal liberar.
2. **Relatar à biblioteca**: independentemente do resultado, a fragilidade do
   seletor fixo merece uma issue no `sigpesq_agent` — sem que o ETL dependa disso.

---

## Resultado da tarefa T021 — diagnóstico NÃO encerrado

**Execução real** (`make extract-project-files PROJECT_FILES_LIMIT=30`, 25/08 19:00):

```
{'downloaded': 0, 'skipped_existing': 0, 'no_attachment': 30,
 'unrecognized': 0, 'modal_failed': 0, 'examined': 30}
```

Pela tabela de leitura do `data-model.md`, "tudo em `no_attachment` e
`unrecognized = 0`" corresponderia a "os anexos foram removidos do portal".

**Essa conclusão foi rejeitada.** Ao revisar a própria heurística, descobriu-se
que a detecção de "área de anexos" varria a **página inteira**, não o modal.
Comprovado offline:

```
modal sem anexos, MAS 'Arquivos' no menu da página  -> no_attachment
página com 'Arquivos' como cabeçalho de coluna      -> no_attachment
```

Como o portal quase certamente contém a palavra "Arquivos" em algum menu ou
cabeçalho de grade, **toda** página irreconhecível seria classificada como "sem
anexo" — reintroduzindo exatamente a confusão que esta feature existe para
eliminar. O resultado de 19:00 é, portanto, inconclusivo.

**Correção aplicada**: a descoberta passou a se restringir à região do modal,
ancorada no botão "Fechar" (cujo id existe, ao contrário do container que a
biblioteca assume). Quando o âncora não é encontrado, o resultado é
`unrecognized` — nunca um palpite. Dois testes travam esse comportamento:
`test_word_arquivos_outside_the_modal_does_not_count` e
`test_missing_modal_anchor_is_unrecognized`.

**Pendente**: repetir a varredura com a versão corrigida, respeitando o limite de
tentativas do portal. Só então a leitura do resumo terá valor probatório.

---

## Segunda rodada: outro defeito meu, e a estrutura real do modal

Com a heurística restrita ao modal, a execução de 19:10 inverteu o resultado:

```
{'downloaded': 0, 'no_attachment': 0, 'unrecognized': 30, 'examined': 30}
```

Trinta de trinta como "não reconheci" — o oposto exato do que a versão anterior
afirmava. Isso confirmou que a primeira conclusão ("anexos removidos") teria sido
um erro, mas também levantou suspeita sobre a nova delimitação da região.

**Sonda da cadeia de ancestrais** (somente leitura), a partir do botão "Fechar":

```
 nv id                                                chars  ctrl  Arq?  quebra?
  1 (sem id)                                              0     1 False     True
  4 ContentPlaceHolder_ModalConsultaProjeto_pnlModal   1420     3  True    False
 11 form_Master                                        4373    61  True    False
```

O laço testava `id + className` e o rodapé do modal tem `class="modal-footer"`,
sem id. Resultado: a busca parava no **nível 1**, num contêiner de **zero
caracteres**. Todo projeto virava `unrecognized` — um alarme falso tão nocivo
quanto o falso "sem anexo" anterior.

**Correção**: a região passa a ser localizada **apenas por id**. O painel real é
o do nível 4. Travado por `test_footer_class_named_modal_does_not_truncate_the_region`.

### O que a sonda revela sobre o portal

O painel do modal **tem** 1420 caracteres, **3 controles** e **contém a palavra
"Arquivos"**. Ou seja: a área de anexos existe. Com a região correta, a
classificação destes projetos tende a ser `no_attachment` — área presente, sem
controle de download — e não `unrecognized`.

**Isso é previsão, não conclusão.** Falta confirmar com a região corrigida; a
tentativa de 19:1x foi recusada pelo limite de acesso do portal.

Se a previsão se confirmar, a pergunta remanescente passa a ser por que oito
projetos com documento extraído em 10/08 hoje não têm anexo — o que apontaria
para remoção dos arquivos no portal, e não para defeito de código.

---

## Diagnóstico ENCERRADO (25/08 21:05)

Execução com a região corrigida, 60 projetos:

```
{'downloaded': 0, 'skipped_existing': 0, 'no_attachment': 60,
 'unrecognized': 0, 'modal_failed': 0, 'examined': 60}
```

E a inspeção dos controles dentro do painel do modal, em dois projetos:

```
A     ..._Consulta_Projeto_rptUsuarios_hlinkExterno_0   "Lattes"
A     ..._Consulta_Projeto_rptUsuarios_hlinkExterno_1   "Lattes"
INPUT ..._btnModal_Fechar                               "Fechar"
rotulo <h4>Arquivos</h4> presente
```

**Conclusão**: a seção "Arquivos" **renderiza**, e não há **nenhum** controle de
download no modal — apenas links para currículos Lattes e o botão de fechar. Os
projetos examinados realmente não têm arquivo anexado hoje.

### Correção de uma afirmação anterior

Este documento afirmou, em D1, que a biblioteca "procura por um nome que não
existe mais na página" e sugeriu quebra de compatibilidade. **Isso estava
errado.** O identificador `rptArquivo` não existe porque um `Repeater` do ASP.NET
não renderiza nada quando está vazio — exatamente o caso aqui. A mensagem
original da biblioteca, "no files in Arquivos (likely a draft)", estava
**correta**.

O que faltava não era a leitura certa da página: era **poder provar** que a
leitura estava certa. Antes, "não tem arquivo" e "não sei ler esta página" eram
indistinguíveis, e não havia como saber qual era o caso sem inspecionar o portal
à mão — foi o que consumiu esta investigação inteira.

### O que o trabalho entregou, então

O risco registrado no `plan.md` **se materializou**: a US1 (descoberta resiliente)
não muda o resultado prático hoje, porque não há o que descobrir. O valor veio da
US2: a etapa deixou de afirmar sem verificar e passou a classificar com
evidência, e é por isso que o diagnóstico pôde ser encerrado em uma execução em
vez de dias de sondagem.

A US1 continua valendo como seguro: se o portal mudar a marcação de verdade, a
descoberta sobrevive, e se não sobreviver, dirá `unrecognized` em vez de mentir.

### Pergunta remanescente (fora do alcance do código)

Oito dos projetos examinados têm documento extraído de PDF real em 10/08 e hoje
não têm anexo no portal: PJ 9760, 9742, 9720, 9702, 9674, 9642, 9628 e 9608.
Nenhuma mudança de código recupera isso — é questão de dado no SigPesq, para quem
administra o portal.
