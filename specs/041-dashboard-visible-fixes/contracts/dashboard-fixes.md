# Contract: Dashboard-visible fixes

**Feature**: `041-dashboard-visible-fixes`

Every table below is a test table: each row is one assertion.

## 1. `is_name_fragment(text) -> bool`

`src/core/logic/person_name_rules.py`. Comparison after trimming spaces,
dots and dashes, without accents, ignoring case.

| Input | Result |
|---|---|
| `None`, `""`, `"  "`, `".."` | True |
| `"Dr"`, `"Dr."`, `"Dra"`, `"Drª"`, `"Prof"`, `"PROF"`, `"Profa"`, `"Profª"`, `"Pro"` | True |
| `"Ph"`, `"PhD"`, `"MSc"`, `"M"`, `"D"`, `"DSc"`, `"Me"`, `"Ma"` | True |
| `"J"`, `"H"`, `"1"`, `"2"`, `"-"`, `"xxx"`, `"Licenciatura"`, `"Esp"`, `"Eng"`, `"Ing"` | True |
| `"Graciela"`, `"Alan"`, `"Adélia"`, `"Rhian"`, `"Elson"` | False |
| `"José Antônio da Silva"`, `"C. Silva"` | False |

## 2. `advisor_name(description, co=False) -> Optional[str]`

`src/core/logic/person_name_rules.py`.

| Description (excerpt) | `co=False` | `co=True` |
|---|---|---|
| `Orientador: Prof. Dr. José Antônio da Silva. Bolsista do(a): …` | `José Antônio da Silva` | `None` |
| `Orientador: Dr. José Rafael Cápua Proveti. Coorientador: Dr. Wanderley Cardoso Celeste. …` | `José Rafael Cápua Proveti` | `Wanderley Cardoso Celeste` |
| `Orientador: Ph.D. Alberto Ferreira de Souza, Ph.D. Hansjorg Schneebeli.` | `Alberto Ferreira de Souza` | `None` |
| `Orientador: M.Sc. Rostan Piccoli, D.Sc. Sergio Antônio Andrade de Freita.` | `Rostan Piccoli` | `None` |
| `Orientador: Profa. DSc. Luciana Rodrigues Cardoso Trigueiro.` | `Luciana Rodrigues Cardoso Trigueiro` | `None` |
| `Orientador: Profa. Michèle Schubert Pfeil. Coorientador: Prof. Ronaldo C. Battista e Prof. Romildo D. Toledo F…` | `Michèle Schubert Pfeil` | `Ronaldo C. Battista` |
| `Orientador: PROF. DR. CREDINE SILVA DE MENEZES. Grande área: …` | `CREDINE SILVA DE MENEZES` | `None` |
| `Orientador: Profª. Drª. Isabel Ferin Cunha). Título: …` | `Isabel Ferin Cunha` | `None` |
| `Orientador: 1.Zilma Rodrigues da Silva. 2.Margarida M. A. de Vasconcelos.` | `Zilma Rodrigues da Silva` | `None` |
| `Orientador: Pro. Dr. Jorge Luiz Viesenteiner. Coorientador: Não Definido.` | `Jorge Luiz Viesenteiner` | `None` |
| `Orientador: Edson Terra.` (no title; behaviour of today) | `Edson Terra` | `None` |
| `Orientador: -.` / `Orientador: ..` / `Orientador: xxx.` / `Orientador: Licenciatura.` | `None` | `None` |
| `Orientador: Alan.` | `Alan` | `None` |
| `Coorientador: Maria Souza. Orientador: João Lima.` | `João Lima` | `Maria Souza` |
| `Orientador: Msc: Talita Miranda Teixeira Xavier.` | `Talita Miranda Teixeira Xavier` | `None` |
| `Orientador: Paulo Faria Santos Amaral http://lattes.cnpq.br/…` | `Paulo Faria Santos Amaral` | `None` |
| `Orientador: Esp. Ana Maria Souza.` / `Orientador: Ing. Fulano de Tal.` | the name without the title | `None` |
| `Orientador: . Ano de interrupção: 2005.` | `None` | `None` |
| `Orientador: Engracia Souza Lima.` (a name that starts like a title) | `Engracia Souza Lima` | `None` |
| no "Orientador:" at all | `None` | `None` |

Notes:
- The co-advisor cell "Não Definido" gives `None` (a known placeholder).
- A capture keeps initials as part of the name ("Ronaldo C. Battista").

## 3. `clean_student_name(raw) -> CleanedName`

`src/core/logic/student_name_rules.py`. Rows of the 036 contract that are not
listed here keep their result.

| Input | `name` | `names` | kinds include |
|---|---|---|---|
| `Gladston Campos/Niase Borjaille` | `Gladston Campos` | `(Gladston Campos, Niase Borjaille)` | `split` |
| `Carlos José Rocha Silva / Renato Barros Vasconcelos` | `Carlos José Rocha Silva` | both | `split` |
| `Eliane N. Oliveira / Laiane C. Vettorazzi / Lidyan Procópio` | `Eliane N. Oliveira` | all three | `split` |
| `Ederson de Souza. Nitretação a plasma … (orientador: Prof. MSc. …; coorientador: …` | `Ederson de Souza` | `(Ederson de Souza,)` | `citation`, `work_title` |
| `Vitor de Sá Nunes. Desenvolvimento de um sistema … hardware/software …` | `Vitor de Sá Nunes` | `(Vitor de Sá Nunes,)` | `work_title` |
| `Juliana Guzzo Pignaton Schneider / Rafael Cardinot Araújo. Fatores Influenciadores …` | `Juliana Guzzo Pignaton Schneider` | both | `work_title`, `split` |
| `Bruno Giacomin/Glício Baptista/Ilvécio Luis Rosi/Rodrigo Mai. Vantagens …` | `Bruno Giacomin` | all four | `work_title`, `split` |
| `Emanuela V. Souza / Rhamila O. Dassié / Edivaldo Antonio` | `Emanuela V. Souza` | all three | `split` |
| `Maria Silva / Xavier` (a part with fewer than two words) | `Maria Silva / Xavier` | `(Maria Silva / Xavier,)` | `several` |
| `Ana Lima` | `Ana Lima` | `(Ana Lima,)` | (none) |
| text that is not a name | `None` | `()` | `not_a_name` |

## 4. `fix_lost_dash(title) -> str` and `plausible_year(value) -> Optional[int]`

`src/core/logic/title_rules.py`.

| Input | Output |
|---|---|
| `Implantação de um Laboratório de Análise de Solos no Ifes ? Campus Ibatiba` | `… no Ifes – Campus Ibatiba` |
| `"Fomento pesqueiro e aquícola do litoral de Piúma ? IFES ? Campus Piúma"` | `… Piúma – IFES – Campus Piúma"` |
| `… ORGÂNICOS DE NOVA VENÉCIA ? ES` | `… NOVA VENÉCIA – ES` |
| `Ifes Portas Abertas: por qual delas entrar?` | unchanged |
| `O que é ? Um estudo` | `O que é – Um estudo` (accepted: a spaced "?" between words is treated as a lost dash) |
| `ANALISE DA ?FESTA DOS PESCADORES?.` | unchanged (quotes are out of scope) |
| `EFEITO DA ADUBAÃ?Ã?O` | unchanged |
| `None` / `""` | unchanged |
| `normalize_text(fix_lost_dash(t)) == normalize_text(t)` for every `t` | always true |

`plausible_year` is applied when articles are exported
(`CanonicalDataExporter.export_articles`), not in the parsers: the database
keeps the source year, because `articles.year` is NOT NULL (research R9).
An exported article from year 0 has `"year": null`.

| `plausible_year` input | Output |
|---|---|
| `2015`, `"2015"`, `1950` | `2015`, `2015`, `1950` |
| current year + 1 | that year |
| `0`, `"0"`, `1949`, current year + 2, `"abc"`, `None`, `""` | `None` |

## 5. Graphs and teams

- `PeopleCollaborationGraphGenerator._add_evidence(G, a, a, ...)` adds
  nothing and changes nothing. The same holds for every subclass.
- In `initiatives_canonical.json`, for every initiative, the `person_id`
  values in `team` are distinct. When a person appears in two teams with
  start dates 2019 and 2020 and roles `Coordinator`, the entry has
  `start_date` 2019 and `roles == ["Coordinator"]`.

## 6. Slack gate

`src/scripts/notify_slack.py`, `NOTIFY_BRANCH = "main"`.

| `GITHUB_REF_NAME` | Event | Webhook set | Sent | Output line |
|---|---|---|---|---|
| `main` | start / end | yes | yes | as spec 040 |
| `main` | start / end | no | no | `::warning::Slack não configurado …` (spec 040) |
| `041-dashboard-visible-fixes` | start / end | yes | no | `::notice::Slack pulado: a branch 041-dashboard-visible-fixes não é a main.` |
| empty / unset | start / end | yes | no | `::notice::Slack pulado: a branch (desconhecida) não é a main.` |

In every row, `main()` returns 0 and nothing ever prints the webhook.

The `curl` fallback of the end step in `.github/workflows/weekly-etl.yml`
sends only when `$GITHUB_REF_NAME` is `main`; otherwise it prints the same
notice.

## 7. Rule version

- `HORIZON_RULE_VERSION == 7`.
- `rule_version_requires_reset` is true for a database recorded with 6.
