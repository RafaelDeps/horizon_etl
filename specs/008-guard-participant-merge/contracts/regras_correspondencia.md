# Contrato: regras de correspondência que os testes fixam

**Feature**: 008-guard-participant-merge | **Data**: 2026-08-28

Estas são as regras de comportamento que a suíte passa a garantir. Não são
descrição da implementação atual: são o contrato que qualquer implementação
futura precisa honrar.

## R1 — Orientação nunca casa por nome aproximado

Dada uma orientação a ser resolvida, a correspondência **não pode** devolver
outra orientação apenas porque os títulos coincidem depois de normalizados.

*Por quê*: o título é o do trabalho e se repete entre orientador e coorientador,
com participantes diferentes em cada registro.

## R2 — Projeto casa por nome aproximado

Dado um projeto a ser resolvido, a correspondência **deve** devolver o projeto
existente cujo nome coincida depois de normalizado, ainda que a grafia difira.

*Por quê*: no projeto o nome identifica a entidade; grafias diferentes são o
mesmo projeto vindo de fontes diferentes.

## R3 — Exato tem precedência sobre aproximado

Havendo coincidência exata de nome, ela prevalece sobre qualquer correspondência
por normalização.

## R4 — O nome persistido prevalece

Reconhecida a equivalência por R2, o nome já gravado **não** é substituído pelo
do registro que chegou.

*Por quê*: renomear faz a linha disputar um nome que outra pode ocupar, o que
descarta o registro por violação de unicidade.

## R5 — Ausência de índice não quebra

Índice ausente, vazio ou título vazio produzem "não encontrado", nunca erro.

## Consequência observável (o que a segunda camada verifica)

Processados em sequência dois registros de orientação com o mesmo título e
participantes distintos, o segundo chega ao handler **sem** iniciativa existente
associada — isto é, como criação, não como atualização.

É esta a afirmação que os 283 testes anteriores não faziam, e por isso não viram
100 orientações serem fundidas.
