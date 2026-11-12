# Contract: Small fixes batch

**Feature**: `036-small-fixes-batch`

Internal contracts: the name rule (a pure function) and the three behaviours
that change. The tests of each section are written from these tables.

## 1. `clean_student_name(raw) -> CleanedName(name, kinds)`

Module `src/core/logic/student_name_rules.py`. No database, no network, no
state. `name` is `None` when the text is not a name. `kinds` holds, in the
order applied, any of: `empty`, `link`, `several`, `work_title`, `uncut`,
`title`, `footnote`, `not_a_name`.

Steps, in this order (research R3):

1. Collapse runs of spaces and strip. Empty or `None`: `(None, ("empty",))`.
2. Link: cut from `javascript:`, `http://`, `https://` or `www.` to the end,
   when text comes before it.
3. Several people: the text has `/`, `;` or "co-orientador" (any case, with
   or without the hyphen). Return the text of step 2 with `several`.
4. Work title: the first ". " (full stop and space) that does not follow an
   initial. An initial is a token of one or two letters, a token that holds
   a full stop, or a title ("Prof.", "Dr."). The head is the text before
   that full stop.
   - no such full stop and the text has a comma: `several`, return the text
     of step 2;
   - head has a comma, or the word "e" between two words: `several`, return
     the text of step 2;
   - head has two words or more and no digit: the name is the head,
     `work_title`;
   - otherwise: keep the whole text, `uncut`, and return it (no later step).
5. Titles: remove, at the start and at the end, one or more of `prof`,
   `profa`, `profª`, `professor`, `professora`, `dr`, `dra`, `drª`,
   `doutor`, `doutora`, `me`, `ms`, `msc`, `m.sc`, `mestre`, `phd`, `ph.d`,
   `d.sc` (any case; the full words `professor`, `doutor`, `mestre` and
   `me`, `ms` at the start only, because at the end they may be a surname),
   each a whole word, with its full stop and the spaces,
   commas, colons, hyphens or question marks that join it. `title` when
   something was removed.
6. Footnote: remove digits glued to the end of the last word. `footnote`.
7. Not a name: what is left has no letter, has a digit, or has one or two
   letters: `(None, (..., "not_a_name"))`.

| Input | `name` | `kinds` |
|-------|--------|---------|
| `"Maria da Silva"` | `"Maria da Silva"` | `()` |
| `"  Maria   da Silva "` | `"Maria da Silva"` | `()` |
| `None`, `""`, `"   "` | `None` | `("empty",)` |
| `"Graciela"` | `"Graciela"` | `()` |
| `"Eduarda Q. O. Senra"` | `"Eduarda Q. O. Senra"` | `()` |
| `"Dr. Hamilton Carvalho Tolosa"` | `"Hamilton Carvalho Tolosa"` | `("title",)` |
| `"Profª Drª Teresa Cristina Janes Carneiro"` | `"Teresa Cristina Janes Carneiro"` | `("title",)` |
| `"Professor Doutor Frederico Carlos de Sá Costa"` | `"Frederico Carlos de Sá Costa"` | `("title",)` |
| `"Profª Msc: Talita Miranda Teixeira Xavier"` | `"Talita Miranda Teixeira Xavier"` | `("title",)` |
| `"Dácio Guimarães de Moura ? Dr"` | `"Dácio Guimarães de Moura"` | `("title",)` |
| `"Drago Pereira Lima"` | `"Drago Pereira Lima"` | `()` |
| `"Mestre"` as a middle word: `"João Mestre Souza"` | `"João Mestre Souza"` | `()` |
| `"Professora Dra"`, `"Prof Dr"`, `"Profª Ms"` | `None` | `("title", "not_a_name")` |
| `"Silas Gambarine Soaresjavascript:void(0)"` | `"Silas Gambarine Soares"` | `("link",)` |
| `"Paulo Faria Santos Amaral http://lattes"` | `"Paulo Faria Santos Amaral"` | `("link",)` |
| `"Guilherme Lopes de Oliveira. Uso do método OTA (Over-The-Air) (PT 10550)"` | `"Guilherme Lopes de Oliveira"` | `("work_title",)` |
| `"ANDRÉ LUIS KEREK. USO DO ANIME DR"` | `"ANDRÉ LUIS KEREK"` | `("work_title",)` |
| `"Alcione Maria de Andrade. Palicourea marcgravii St. Hil"` | `"Alcione Maria de Andrade"` | `("work_title",)` |
| `"Lucas Basseti. BIOMASSA E ESTRUTURAÇÃO VEGETATIVA"` | `"Lucas Basseti"` | `("work_title",)` |
| `"Andre. \"ELABORAÇÃO DE ENSAIOS DIDÁTICOS\""` | the input, spaces collapsed | `("uncut",)` |
| `"Katianni Garcia Suhett e Monique Vargas de Gouvêa. Resíduos sólidos"` | the input | `("several",)` |
| `"Carlos Huhn de Paiva Siqueira, Felipe Kuhn. Comparativo entre"` | the input | `("several",)` |
| `"Adriana S.N. Marchezi, Izack de P. vieira, Fernando B. Rocha"` | the input | `("several",)` |
| `"Rafael Scopel Paviotti/Sidarta Barroso Veloso"` | the input | `("several",)` |
| `"Daiane Costa; Elizana Faria; Matheus Schulz;"` | the input | `("several",)` |
| `"Nina Waszczynskyj Co-orientador: Peter Gaber Kirschnik"` | the input | `("several",)` |
| `"Roseanne Gomes Gonçalves2"` | `"Roseanne Gomes Gonçalves"` | `("footnote",)` |
| `"Acadêmicos do 6 periodo"` | `None` | `("not_a_name",)` |
| `"Turma \"C\" do 1º ano EBTT"` | `None` | `("not_a_name",)` |
| `"1"`, `"-"`, `"D"`, `"Ph"` | `None` | `("not_a_name",)` |

Properties:

- The same input always gives the same output.
- Cleaning a clean name gives the same name: `clean(clean(x).name).name ==
  clean(x).name` for every row above with a name and no `several`/`uncut`.
- A text with `several` or `uncut` is returned as written, apart from spaces
  and a removed link.

## 2. Lattes parser

Both paths that read the student (`_parse_items`,
`_parse_generic_advisorships`):

| Item | Result |
|------|--------|
| title and a student text that cleans to a name | item kept, `student_name` = the clean name, `student_name_kinds` = the kinds |
| title and a student text that is not a name | item kept, `student_name` = `None`, `student_name_kinds` holds `not_a_name` |
| title and no student text (missing or empty) | item dropped, as today |
| no title | item dropped, as today |

Downstream, unchanged code: an item with `student_name = None` gives
`student_names = []`; the handler stores the advisorship with its supervisor
and no student; the loader matches it by title as branch 035 defines for an
item without a student.

The Lattes advisorship flow logs, once per phase, the number of items of each
kind.

## 3. Fellowship

`AdvisorshipHandler._ensure_fellowship`:

| Case | Result |
|------|--------|
| row with programme and funding agency, no stored fellowship | one fellowship is created and stored with that sponsor |
| the same row in a later run (cache filled from the database) | the stored fellowship is returned; nothing is created or updated |
| row with programme and no funding agency, twice | one fellowship, no sponsor |
| the same programme with two funding agencies | two fellowships, as today |
| funding agency written with other case or spaces | the same fellowship |
| row with no programme | no fellowship, as today |

## 4. Project PDF matching

`ProjectEnrichmentLoader`:

| Case | Result |
|------|--------|
| PDF title equals a research project's name | matched to the project, as today |
| PDF title equals the name of an initiative that has a row in `advisorships`, whatever its stored type | not matched to it |
| PDF title is similar (fuzzy) to such an initiative only | not matched to it |
| PDF code points, through the tracked SigPesq project records, to such an initiative | not matched to it |
| PDF that matches nothing and whose title is taken by another initiative | not created, counted as a skipped duplicate, as today (TD-020) |

## 5. SigPesq project row change

`SigPesqProjectMappingStrategy.change_content(row)` and the loader:

| Second arrival of a stored row | Result |
|--------------------------------|--------|
| identical | skipped as unchanged |
| "Estudantes" with the same names in another order | skipped as unchanged |
| "Pesquisadores" with the same names in another order | skipped as unchanged |
| spaces around a name or around `;` differ | skipped as unchanged |
| a name added or removed | processed as changed |
| any other column differs | processed as changed |
| a strategy without `change_content` (every other source) | the row is compared as read, as today |

The tracked payload of the row is the row as read.

## 6. Rule version

| Database recorded under | Run |
|-------------------------|-----|
| 6 | incremental |
| 5 or lower | rebuilt before use, then recorded as 6 |
