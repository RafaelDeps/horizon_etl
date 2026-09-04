# Data Model: participant deduplication scenarios

**Feature**: 008-guard-participant-merge | **Date**: 2026-08-28

No persisted schema is created or changed by this feature. What this document
describes are the **scenarios** the deduplication logic must handle — the
fixtures the tests build, and the state the production run must converge to.

## Participant record

A participant is a `Person` row (optionally with a `Researcher` side) plus every
link that points at it. Two participant records are *records of the same
physical person* when the rule of the dedup contract holds — that and only that.

## Normalized name key

The primary identity key: the full name passed through the single shared
normalization function (case, accents, whitespace, punctuation and particles).
Any two spellings that differ only in those dimensions produce the same key.

Examples pinned by the tests:

| Raw name | Key |
|---|---|
| `Israel Magalhães do Carmo` | `ISRAEL MAGALHAES do CARMO` |
| `ISRAEL MAGALHÃES DO CARMO` | `ISRAEL MAGALHAES do CARMO` |
| `Gustavo Maia De Almeida` | `GUSTAVO MAIA de ALMEIDA` |
| `Gustavo Maia de Almeida` | `GUSTAVO MAIA de ALMEIDA` |
| `Maria-Aparecida Santos!` | `MARIA APARECIDA SANTOS` |
| `Maria Aparecida Santos` | `MARIA APARECIDA SANTOS` |
| `Paulo Sérgio Dos Santos Júnior` | `PAULO SERGIO dos SANTOS JUNIOR` |

## Scenario A — the observed defect (same person, two sources)

Two records for "Israel Magalhães do Carmo", neither holding a strong identifier:

| | Record 579 | Record 5767 |
|---|---|---|
| name | `Israel Magalhães do Carmo` | `Israel Magalhães do Carmo` |
| normalized key | `ISRAEL MAGALHAES do CARMO` | `ISRAEL MAGALHAES do CARMO` |
| initiatives | 5 (advisorships + research projects, role Student) | none |
| research groups | none | Núcleo de Estudos em Robótica e Automação |

They are the same person. After dedup the catalog (and therefore the dashboard)
must show **one** participant with **both** the five initiatives **and** the
research-group membership. This scenario recurs 176 times in the 2026-08-28
export.

## Scenario B — spelling variants across sources (case, accents, particles, punctuation)

| | Record 1 | Record 2 |
|---|---|---|
| raw name | `Paulo Sérgio Dos Santos Júnior` | `PAULO SERGIO dos SANTOS JUNIOR` |
| normalized key | `PAULO SERGIO dos SANTOS JUNIOR` | `PAULO SERGIO dos SANTOS JUNIOR` |

Same key → same person. Scenario B is about the *key function*: it must collapse
these differences before any matching decision is made.

## Scenario C — the initiative guard that must not weaken

| | Record 1 | Record 2 |
|---|---|---|
| entity | advisorship | advisorship |
| name (title) | `Análise Comparativa de Desempenho` | `ANÁLISE COMPARATIVA DE DESEMPENHO` |
| student | Eduardo Vicente | Eduardo Vicente |
| advisor | **Marco Cuadros** | **Cassius Resende** |

Same normalized *title*, different participants. Under the initiative-level
guard these remain **two** advisorships — normalizing the title is still not
identity for an advisorship. This feature preserves and regression-tests this
rule (FR-012); it changes participant matching, not initiative matching.

## Scenario D — complementary data across duplicate records (merge by union)

Record A and record B of the same person:

| | Record A | Record B |
|---|---|---|
| advisorship X (Student) | ✓ | |
| project Y (Researcher) | | ✓ |
| research group G (Estudante/Egresso) | | ✓ |

After consolidation the winner holds **X + Y + G**. A link shared by both (same
initiative, same role) appears exactly once. This is the operational core of the
feature: *union, never discard*.

## Scenario E — simultaneous initiatives and same-researcher initiatives

One person is concurrently Student on advisorship A (2022) and Student on
advisorship B (2022–2023), both under the same advisor, and Researcher on
project C. A duplicate pair splits A into one record and B + C into another.

| | Record 1 | Record 2 |
|---|---|---|
| advisorship A (Student, 2022) | ✓ | |
| advisorship B (Student, 2022–2023) | | ✓ |
| project C (Researcher, 2022) | | ✓ |
| shared researcher R | ✓ | ✓ |

After consolidation all of **A, B, C** survive and the shared researcher R's
links are intact. Overlapping dates prove nothing; shared researchers prove
nothing — both observations are normal for one person.

## Scenario F — homonyms and conflicting strong identifiers (the veto)

Two physically distinct people under one normalized name:

| | Record 1 | Record 2 |
|---|---|---|
| name | `José da Silva` | `José da Silva` |
| Lattes URL | `http://lattes.cnpq.br/1111111111111111` | `http://lattes.cnpq.br/2222222222222222` |

The conflicting Lattes IDs make the group a **refusal**: no merge, and the group
is reported with the reason. The same veto fires on conflicting identification
IDs. Scenario F is what keeps the feature from becoming the very damage the
initiative guard was created to avoid.

## Scenario G — junk names

Records such as `Dr`, `Prof Dr` and `PROF` (four exist today) have no plausible
surname. They must be flagged and never merged, so a junk row cannot absorb a
real participant under "the same normalized name".

## Supporting structures the tests reuse

- **In-memory catalog**: the consolidated tests build the real SQLite tables
  (`persons`, `researchers`, `advisorship_members`, `team_members`,
  `initiative_persons`, `article_authors`, `person_emails`, ...) as fixtures;
  the scenarios above map directly onto rows of these tables.
- **Deduplication report**: the merge output records, per normalized name group,
  the decision (**merged** / **refused-homonym** / **refused-junk**) and, for
  refusals, the reason.

## Invariant the tests fix

> Two participant records are one person exactly when their normalized names
> agree and no strong identifier disagrees. Merging transfers every link the
> loser owns that the winner does not, so the union of the two records' data is
> preserved and nothing is arbitrarily discarded; groups that fail the guard are
> reported as refusals, never merged.