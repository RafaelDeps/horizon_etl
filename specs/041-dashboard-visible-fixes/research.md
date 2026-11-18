# Research: Dashboard-visible data fixes and Slack notices on main only

**Feature**: `041-dashboard-visible-fixes` | **Date**: 2026-11-17

All measurements are read-only: the published exports of fork main (commit
`c5ffe55`, weekly run of 2026-11-17), the local database of 2026-11-16
(`db/horizon.db`, rule version 6, 18,335 persons, 15,550 initiatives) and the
435 curricula of `data/lattes_json/`. Only counts and public names from
Lattes, SigPesq and CNPq are quoted; no CPF or phone number was read.

## R1. Why the fixes need the rule version (6 -> 7)

- **Finding**: a source document is skipped when its content hash and the
  rule version are the same as when it was processed
  (`Document.unchanged`, `src/core/logic/document_skip.py:92`). A fix in the
  parser or in a flow is therefore applied only to curricula whose content
  changed; every other curriculum keeps the old result.
- **Finding**: the incremental database would then differ from a rebuild from
  the same sources, which the constitution forbids (Data Integrity, rule 3).
  Branch 036 met the same situation when it cleaned student names and raised
  the version from 5 to 6.
- **Decision**: `HORIZON_RULE_VERSION` goes from 6 to 7 with a comment line
  for branch 041. The weekly's guard (`_reset_if_rule_version_changed`,
  `src/flows/pipelines/weekly_orchestrator.py`) rebuilds a database written
  under version 6 once; the history turns old ids into aliases or reports
  them as retired. The id rules (which fields form each key) do not change.
  Clarification of 2026-11-17: a rebuild is accepted.
- **Alternatives considered**: fixing only in the exporter, so no version
  change is needed (it cannot split one person into several or give them ids,
  and the fake people would stay in the database); fixing at ingestion
  without the version (breaks rule 3).

## R2. Slack notices only on main

- **Finding**: both steps run on every branch.
  - "Notify Slack: start" (`.github/workflows/weekly-etl.yml:96`) calls
    `python3 -m src.scripts.notify_slack start`.
  - "Notify Slack: end" (`:231`, `if: always()`) calls the script, or, when the
    checkout failed and the script is missing, sends a minimal message with
    `curl`.
- **Finding**: `notify_slack.main` already turns every problem into a
  `::warning::` line and returns 0, and it reads `GITHUB_REF_NAME` for the
  message.
- **Decision**: the branch check goes in two places.
  - In `notify_slack.main`, before the webhook is read: when `GITHUB_REF_NAME`
    is not `main`, print `::notice::Slack pulado: a branch <name> não é a
    main.` and return 0, for both events. The start event still writes
    `WEEKLY_STARTED_AT` (harmless, keeps the step's behaviour simple).
  - In the `curl` fallback of the end step: a shell test on `$GITHUB_REF_NAME`
    in front of the `curl`, with the same notice.
  - The branch name is read from the environment GitHub sets, so a test can set
    it.
- **Decision**: the allowed branch is the constant `NOTIFY_BRANCH = "main"`,
  with no new setting or workflow input. The scheduled run always uses main.
- **Alternatives considered**: a step-level `if: github.ref_name == 'main'`
  (the step would vanish from the log on other branches, with no line saying
  why, against FR-002); a repository variable listing branches (a new
  setting the spec did not ask for).

## R3. Where the fake people "Dr", "Prof", "Ph", "M", "-" come from

- **Finding**: 49 one-word people. Most of them are advisors of an academic
  degree, cut by `re.search(r"Orientador:\s*([^.;)]+)", description)` in
  `src/flows/lattes/projects.py:680`. The capture stops at the first full stop.
  - "Orientador: Prof. Dr. José Antônio da Silva." gives "Prof".
  - "Orientador: Ph.D. Alberto Ferreira de Souza" gives "Ph".
  - "Orientador: M.Sc. Rostan Piccoli, D.Sc. …" gives "M".
  - The co-advisor regex on the next lines has the same defect.
- **Finding**: on the 435 curricula, 1,296 degree descriptions have
  "Orientador:" and 112 are cut to one word or less:

  | Cut text | Count |
  |---|---|
  | Prof / PROF | 36 |
  | Dr | 23 |
  | - | 12 |
  | M | 8 |
  | empty (from "Orientador: ..") | 7 |
  | D | 6 |
  | Profa | 4 |
  | Drª | 4 |
  | Dra | 3 |
  | Ph | 2 |
  | Profª, Pro, 1, xxx, Licenciatura, Alan, Adélia | 1 each |

  The real advisor's name is lost in all of them, and every degree with that
  advisor points to the same fake person.
- **Finding**: "Orientador:" also matches inside "Coorientador:", so a text
  that names the co-advisor first can give the co-advisor as advisor.
- **Finding**: the one-letter members ("D" 22 times, "J" 7, "H", "R", "L",
  "G", "A") come from the `integrantes` list of Lattes projects. The
  downloaded curriculum already holds the letter as a member's whole name.
  For example, `37_Anderson-Mathias-Holtz` lists "Anderson Mathias Holtz"
  and "D". They are read in `LattesProjectMappingStrategy.map_row`
  (`src/core/logic/strategies/lattes_projects.py:52`).
- **Decision**: the advisor and co-advisor texts are read by a new pure
  function `advisor_name(description, co=False)` in
  `src/core/logic/person_name_rules.py`, which:
  - takes the text after `Orientador:` (not preceded by "Co-"/"Co") or
    `Coorientador:` / `Co-orientador:`, up to the next field label
    (`Coorientador:`, `Bolsista`, `Palavras-chave:`, `Grande área:`,
    `Título:`, `Área:`), a `;`, a `)` or the end;
  - drops leading academic titles, repeated (`Prof.`, `Profa.`, `Profª.`,
    `Pro.`, `Dr.`, `Dra.`, `Drª.`, `M.Sc.`, `MSc.`, `D.Sc.`, `DSc.`,
    `Ph.D.`, `PhD`, `Me.`, `Ma.`), in any case, and a leading enumeration
    ("1.");
  - keeps the first person when several are listed (cut at ", " or " e "
    followed by a title, or at " e " between two names of two words or more);
  - cuts at the first ". " that ends the name (the same test as
    `student_name_rules._head_before_work_title`, which treats initials
    such as "C." as part of the name);
  - returns `None` when what is left is empty or a fragment (R4).

  `projects.py` calls it instead of the two regular expressions; a `None`
  advisor leaves `advisor_id` empty, as when there is no "Orientador:".
- **Decision**: the strategy of Lattes projects skips a member whose name is
  a fragment (R4) before sorting members into coordinator, students and
  researchers.
- **Alternatives considered**: widening the regular expression only (the
  titles would stay in the name, and "Prof Fulano" and "Fulano" would be two
  people); skipping the advisor whenever the text starts with a title (loses
  112 real advisors).

## R4. What counts as a name fragment

- **Decision**: one predicate `is_name_fragment(text)` in
  `person_name_rules.py`. After trimming spaces, dots and dashes and removing
  accents and case, it is true for:
  - an empty text;
  - a single letter;
  - digits only;
  - "xxx";
  - "-";
  - an academic title alone: `dr`, `dra`, `prof`, `profa`, `pro`, `ph`, `phd`,
    `msc`, `me`, `ma`, `m`, `d`, `dsc`;
  - "licenciatura".

  It is used by R3 (advisors, project members) and by R5 (each student of a
  split field).
- **Finding**: real one-word names stay. Examples: "Graciela", "Adikto",
  "Rhian", "Alan", "Adélia", "Elson", "Rodney", and the 3 CNPq one-word
  members. The spec keeps them (Edge Cases).
- **Finding**: other one-word texts from Lattes advisorships are left as
  they are. They are not in the spec's list and come from the source.
  - "Vários", "FAPEC", "Inovafiltros", "www.es.estacio.br".
  - Comma lists with no spaces, such as
    "AngeloBarros,CrisleiPaula,DaviSchultz,…".

  They are recorded in `docs/backlog.md` as a known remainder.

## R5. Several students in one field, and citations

- **Finding**: `clean_student_name` (branch 036,
  `src/core/logic/student_name_rules.py`) flags a field with `/`, `;` or
  "coorientador" as `several` and returns it as written, on purpose.
  - The 55 people whose name holds "/" are all from Lattes advisorships.
  - The 5 "citations" are flagged `several` too. Examples:
    "Ederson de Souza. Nitretação … (orientador: Prof. MSc. …" (the word
    "coorientador" appears later), and
    "Vitor de Sá Nunes. Desenvolvimento … hardware/software …" (the "/" is
    inside the work title).
- **Decision**: in `clean_student_name`, first cut the work title, then
  split:
  1. Cut the text at the first ". " that ends the name, with the existing
     `_head_before_work_title`, and at "(orientador" / "(coorientador".
     This handles the citations and removes any "/" that belongs to the work
     title.
  2. Split what is left on "/". When every part is a name of two words or
     more (initials count as words), the field has several students. Each
     part goes through the same cleaning, and a part that is a fragment (R4)
     is dropped.
  3. When a part has fewer than two words (for example "Edivaldo Antonio /
     X"), the field is returned as written with the kind `several`, as
     today.
- **Decision**: `CleanedName` gains `names: Tuple[str, ...]`, which holds all
  the students. `name` stays as the first name, so existing callers do not
  change.
  - The parser passes `student_names` (all names) next to `student_name`.
  - `LattesAdvisorshipMappingStrategy.map_row` uses `student_names` for the
    team.
  - The identity key keeps the names joined by " / ". `normalize_text` turns
    "/" into a space, so the key of a split advisorship is the same text as
    before and its horizon_id does not move.
- **Finding**: the advisorship handler reads only the first name of
  `student_names` (`AdvisorshipHandler._student_person`,
  `src/core/logic/initiative_handlers.py:319`), and the 035 matching compares
  that first student (`item_student`).
- **Decision**:
  - `_student_person` stays as it is, so the first name remains the item's
    student for matching and for the person id.
  - The initiative team already loops over every name of `student_names`
    (`InitiativeLinker`, `src/core/logic/initiative_linker.py:63`), so the
    team gets one Student per name with no change.
  - The advisorship's own member list does not. `_sync_advisorship_member`
    keeps one person per role, and its deferred queue is keyed by
    `(initiative id, role)`. It gains a list form for the Student role,
    `persons=[...]`, which keeps one member per person and removes the
    Student members not in the list, using the same "same person, same role,
    same day: keep the row" rule (spec 020, FR-022). Each further name is
    resolved with the same `person_matcher.match_or_create(...,
    strict_match=True)`.
  - A field with one student behaves exactly as today.
- **Alternatives considered**: splitting on " e " as well (one case,
  "GUTTO GABRIEL KUSTER LUBE e MAURÍCIO G. PINHEIRO GUERRA", but " e " also
  joins words in real names and titles; left for later); splitting in the
  handler (the identity key and the 035 matching would see the joined text).

## R6. A person linked to themselves in the graphs

- **Finding**: the 9 self-edges of `people_collaboration_graph` and of each
  subgraph come only from advisorships (`advisorship_count`).
  - In the curriculum, the owner lists their own work as an advisorship of
    theirs. For example, the curriculum `3073250835960964` lists its owner as
    the "orientando" of her own scientific initiation. The supervisor (the
    curriculum owner) and the student are then the same person.
  - The relationship graphs have none.
  - All 21 advisorships with the same person as supervisor and student are
    Lattes items of this kind, plus one project merged with an advisorship.
- **Decision**: the source error is kept, as the clarification asks for
  source errors. Only the graph changes: `_add_evidence` in
  `src/core/logic/people_collaboration_graph_generator.py` returns at once
  when `a == b`. Every collaboration graph inherits that method (people,
  researchers only, students, outside IFES, null researchers).
- **Alternatives considered**: dropping the student when it resolves to the
  supervisor (changes stored data for a source error, against the
  clarification).

## R7. One person twice in a team

- **Finding**: the exporter groups members by person inside each team
  (`canonical_exporter.py`, initiatives section, `person_map`). It resets the
  map for every team of the initiative.
  - Initiative 7622 has two teams that both hold the coordinator (start 2019
    in one, 2020 in the other), so the coordinator is listed twice.
  - `initiative_teams` has 15,582 rows for 15,550 initiatives.
  - The kept start date is the first member row read, not the earliest.
- **Decision**: build `person_map` once per initiative, across all its
  non-research-group teams. Merge the roles. Keep the earliest start date,
  and keep the latest end date (no end date wins, since the person is still
  in the team). The export shape does not change.
- **Alternatives considered**: merging the two teams in the database (an
  ingestion change with its own risk; the duplicate team is a separate
  defect, recorded in `docs/backlog.md`).

## R8. "?" in titles

- **Finding**: the downloaded curricula already hold a literal "?" (byte
  0x3F). For example, `45_Anna-Isabel-Guido-Costa` has "Laboratório de
  Análise de Solos no Ifes ? Campus Ibatiba". The crawler is a third-party
  library and stays as it is.
- **Finding**: counts by pattern on the local database:

  | Pattern | Initiatives | Productions | Articles |
  |---|---|---|---|
  | " ? " between words | 237 | 57 | 80 |
  | "?" as an opening or closing quote ("?FESTA DOS PESCADORES?") | about 150 | 16 | 39 |
  | Broken encoding ("ADUBAÃ?Ã?O") | — | — | some |
  | Real question at the end ("…entrar?") | many | many | many |

  All 237 initiatives come from Lattes (191 advisorships, 46 projects).
- **Decision**: a pure function `fix_lost_dash(title)` in
  `src/core/logic/title_rules.py` replaces a "?" that has a space on each
  side and a letter or digit next to those spaces with " – ". Every other "?"
  is kept (FR-010).
  - The Lattes parser applies it to the title of projects (`name`),
    advisorships (`titulo`), articles, conference papers and technical
    productions.
  - `normalize_text` and `normalize_title` turn "?" and "–" into a space, so
    no key changes.
- **Finding**: initiative names are unique in the database, and the loader
  already matches a title written another way to the stored row
  (`project_loader.py`, "Mesma iniciativa com grafia diferente"). A title
  that becomes equal to another title once fixed resolves to that row, as any
  case or accent variant does today.
- **Alternatives considered**: guessing quotes for "?WORD … WORD?" (the
  pairing is ambiguous next to real questions; left for later in
  `docs/backlog.md`); fixing in the exporter (the stored title would keep the
  "?").

## R9. Article years

- **Finding**: the 3 articles from year 0 are Lattes conference items whose
  downloaded `ano` is the integer 0, with an empty `evento`. Examples: "R.. ",
  "Eletricidade Básica. 2015. (Curso de curta duração ministrado/Outra)".
  `parse_conference_papers` and `parse_articles` accept any digits.
- **Decision (revised after the first local run, T035)**: the parsers keep
  the year as the source gives it, and the database stores it unchanged. The
  export (`CanonicalDataExporter.export_articles`) gives `null` for a year
  outside 1950 to the current year plus one (FR-011). The rule is a helper in
  `title_rules.py` (`plausible_year`).
- **Why revised**: the first version applied `plausible_year` in the parsers.
  `articles.year` is NOT NULL, so the insert of those articles failed. The
  article loop did not roll the session back after a failure, so the next
  statement raised `PendingRollbackError` and the whole curriculum failed
  (3 curricula on 2026-11-17, with all their projects and articles). The
  article loop of `ingest_articles_task` now calls `session.rollback()` when
  an article fails, so one bad article never drops the rest of a curriculum.
- **Alternatives rejected**: making `articles.year` nullable (a schema change
  of the third-party `research_domain` table); skipping the articles (drops a
  real record, against "old data is better than none").
- **Finding**: the titleless article (1, `10.48178/intersecao.v10i1.770`) and
  the 3 SigPesq workplans that end before they start stay as they are
  (clarification of 2026-11-17: source errors).

## R10. Effect on ids and counts

- **Finding**: the horizon_id history already covers people who disappear.
  When the database is rebuilt, a person that no longer exists, such as
  "Prof", gets an alias when a "key corrected" match reaches the fuzzy
  threshold. Otherwise the person is reported as `retired`
  (`horizon_id_assigner.py`). FR-007 needs no new code; the quickstart checks
  that every old id resolves.
- **Expected changes**:

  | What | Change |
  |---|---|
  | One-word fake people | about 40 fewer |
  | People whose name joins several | 55 fewer, replaced by about 130 people of their own (some already exist and are matched) |
  | Real advisors recovered | up to about 110 degree descriptions |
  | Repeated team members | 1 fewer |
  | Self-edges | 9 fewer per collaboration graph |
  | Titles with " ? " | 374 fewer |
  | Articles with a year outside the range | 3 fewer |

  Every other count stays the same or goes up.
- **Finding**: the rebuild also brings back what a rebuild always brings. On
  the first run after the change, items of curricula whose download fails
  have no old data to keep, as seen in run 1 of 2026-11-17. The second run
  recovers them. The quickstart compares the second run, not the first.
