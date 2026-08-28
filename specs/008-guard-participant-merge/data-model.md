# Data Model: cenários de correspondência

**Feature**: 008-guard-participant-merge | **Data**: 2026-08-28

Nenhuma entidade persistida é criada ou alterada. O que este documento descreve
são os **cenários** que os testes montam em memória.

## Cenário A — o defeito que motivou a feature

Duas orientações do mesmo trabalho, vindas de currículos diferentes:

| | Registro 1 | Registro 2 |
|---|---|---|
| título | "Análise Comparativa de Desempenho" | "ANÁLISE COMPARATIVA DE DESEMPENHO" |
| aluno | Eduardo Vicente | Eduardo Vicente |
| orientador | **Marco Cuadros** | **Cassius Resende** |

Sob a regra correta são **duas** orientações. Sob a regra defeituosa viravam uma,
com os participantes do segundo registro — e o orientador Marco Cuadros
desaparecia. Este é o caso real que ocorreu 100 vezes numa execução.

## Cenário B — a deduplicação que deve continuar funcionando

Dois registros do mesmo projeto, um do SigPesq e outro de um currículo Lattes:

| | Registro 1 | Registro 2 |
|---|---|---|
| título | "Recuperação de Conhecimento em Documentos" | "RECUPERAÇÃO DE CONHECIMENTO EM DOCUMENTOS" |
| tipo | projeto | projeto |

São **um** projeto. Este é o caso que a melhoria resolveu, e que a proteção não
pode reabrir.

## Cenário C — precedência

Um registro cujo título coincide **exatamente** com um já existente, havendo
também um candidato que só coincide por normalização. O exato vence.

## Cenário D — preservação do nome

Reconhecido o projeto do Cenário B, o nome que permanece é o **já persistido**.
Renomear é o que produzia violação de unicidade e descarte do registro.

## Estruturas de apoio

**Índice normalizado** (`existing_by_norm_name`): dicionário de nome normalizado
para iniciativa, montado uma vez por arquivo processado. A chave vem de
`normalize_text` — minúsculas, sem acento, pontuação virando espaço.

**Marcador de tipo**: orientações são reconhecidas por serem instâncias de
`Advisorship`; projetos, por não serem. Nos testes, `MagicMock(spec=Advisorship)`
e `MagicMock()` respectivamente.

## Invariante que os testes fixam

> Reconhecer duas entidades como a mesma por semelhança de nome só é permitido
> quando o nome identifica a entidade. No projeto, identifica. Na orientação, o
> nome é o do trabalho, e não identifica — dois registros de mesmo título podem
> ter participantes distintos, e fundi-los apaga um deles.
