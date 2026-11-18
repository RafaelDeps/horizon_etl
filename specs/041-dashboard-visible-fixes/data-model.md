# Data Model: Dashboard-visible data fixes and Slack notices on main only

**Feature**: `041-dashboard-visible-fixes` | **Date**: 2026-11-17

No table, column or export field is added or removed. This file lists what
each fix reads and writes.

## Source texts (read)

| Text | Where it comes from | Fix |
|---|---|---|
| Degree description, `formacao_academica[].descricao` | Lattes curriculum | The "Orientador:" and "Coorientador:" parts are read by `advisor_name` (R3) |
| Project member, `projetos_*[].integrantes[].nome` | Lattes curriculum | Skipped when `is_name_fragment` (R4) |
| Advisorship student, `orientando` / `nome_do_orientado` | Lattes curriculum | `clean_student_name`: work title cut first, then split on "/" (R5) |
| Titles, `projetos_*[].nome`, `orientacoes…[].titulo`, `artigos_periodicos[].titulo`, `trabalhos_completos_congressos[].titulo`, technical productions | Lattes curriculum | `fix_lost_dash` (R8) |
| Year, `artigos_periodicos[].ano`, `trabalhos_completos_congressos[].ano` | Lattes curriculum | Stored as the source gives it; `plausible_year` at export (R9) |
| `GITHUB_REF_NAME` | GitHub Actions environment | Slack gate (R2) |

## Value objects

### CleanedName (extended)

`src/core/logic/student_name_rules.py`

| Field | Type | Meaning |
|---|---|---|
| `name` | `Optional[str]` | First (or only) student; `None` when the text is not a name. Unchanged meaning. |
| `names` | `Tuple[str, ...]` | **New.** Every student, in source order. `(name,)` for one student, `()` when `name` is `None`. |
| `kinds` | `Tuple[str, ...]` | Cleaning applied. Adds `split` (several students found) and `citation` (an "(orientador" part was cut). `several` remains for fields that were not split. |

Rule: `names[0] == name` whenever `names` is not empty.

## Stored rows (written)

| Row | Change | Rule |
|---|---|---|
| `persons` | Fake people ("Prof", "Dr", "Ph", "M", "D", "-", "1", "xxx", "Licenciatura", one letters) are no longer created. People named "A / B" are no longer created; "A" and "B" are created or matched instead. | Rebuild (R1); ids by the alias history (R10) |
| `academic_educations.advisor_id`, `co_advisor_id` | Point to the real advisor, or are empty when the text has no name | `advisor_name` (R3) |
| `advisorship_members` (role Student) | One row per student of the item | List form of `_sync_advisorship_member` (R5) |
| `team_members` of an advisorship's team | One Student per name (already the case once `student_names` holds them all) | `InitiativeLinker`, unchanged |
| `initiatives.name`, `research_productions.title`, `articles.title` | " ? " becomes " – " | `fix_lost_dash` (R8); keys unchanged |
| `articles.year` | Unchanged: the source year (NOT NULL column). The export `articles_canonical.json` gives `null` for a year outside 1950 to the current year plus one | `plausible_year` in `export_articles` (R9) |
| `horizon_meta.rule_version` | 6 becomes 7 | R1 |

## Exported values (changed)

| Export | Change |
|---|---|
| `initiatives_canonical.json`, `team[]` | One entry per `person_id` across all non-research-group teams. `roles` is the union, `start_date` the earliest, and `end_date` the latest (none when any row has none). |
| `*_collaboration_graph.json` (people, researchers only, students, outside IFES, null researchers) | No edge with `source == target`. Node set and other edges unchanged. |
| Everything else | Same shape. Values follow the stored rows above. |

## States and invariants

- **Run on a non-main branch**: the start and end notice steps each print one
  `::notice::Slack pulado: a branch <name> não é a main.` and send nothing.
  The job result is unchanged.
- **Run on main**: behaviour of spec 040, unchanged.
- **Database written under rule version 6**: the weekly's guard resets it
  before ingestion, so all curricula are processed again under version 7.
- **Second run with unchanged sources**: no row is written (fixpoint). The
  member list keeps the same rows.
