# Contract: `horizon_id` format and rules

This is the contract with every consumer of the ids, in particular the team
that combines this ETL's data with other projects. Once published, an id never
designates another entity (FR-012). Changing any rule below requires a bump of
`HORIZON_RULE_VERSION` (FR-024), and the history turns the old ids into
aliases (research R5).

## Grammar

```text
horizon_id   := root ( "/" child )* suffix?
root         := entity ":" origin ":" source_id        ; the source has an id
              | entity ":" origin ":" "h:" hash12      ; computed from content
              | entity ":" "h:" hash12                 ; computed, no single origin
              | entity ":" slug ( ":" qualifier )?     ; reference records
child        := kind ":" "h:" hash12 | kind ":" slug | "team"
suffix       := "~" hex6 | "~" digit+                  ; collision only (FR-008)
hash12       := first 12 hex chars of sha256( "|".join(normalize_text(part)) )
slug         := normalize_text(name) with spaces replaced by "-"
```

`normalize_text` is the function in `src/core/logic/initiative_identity.py`:
accents removed (NFD, combining marks dropped), every non-alphanumeric
character replaced by a space, lowercase, whitespace collapsed.

## Rules (priority order within each entity)

| entity | Rule | Example |
|---|---|---|
| `person` | 1. `person:lattes:<16-digit lattes_id>` from `researchers.cnpq_url` or the `researcher_profile` source record | `person:lattes:9860697624155451` |
| | 2. `person:h:<hash12(name)>` | `person:h:3f9a0c1b2d4e` |
| `group` | 1. `group:cnpq:<id from espelhogrupo URL>` | `group:cnpq:4439471564090237` |
| | 2. `group:sigpesq:h:<hash12(SigPesq name)>` | |
| `initiative` | 1. `initiative:sigpesq-pj:<project code>` (from `sigpesq project\|<code>` or `PJ <code>`) | `initiative:sigpesq-pj:2342` |
| | 2. `initiative:lattes:h:<hash12(Lattes identity key)>` | |
| | 3. `initiative:h:<hash12(type, name)>` | |
| `advisorship` | 1. `advisorship:sigpesq-pt:<workplan code>-<row id>` | `advisorship:sigpesq-pt:10045-4882` |
| | 2. `advisorship:sigpesq-pj:<code>` | |
| | 3. `advisorship:lattes:h:<hash12(Lattes identity key)>` | |
| | 4. `advisorship:h:<hash12(type, name)>`; a SigPesq row without workplan code lands here, because its identity key holds e-mails (FR-007) | |
| `article` | 1. `article:doi:<DOI lowercased, without https://doi.org/ or http://dx.doi.org/>` | `article:doi:10.1016/j.theriogenology.2018.10.032` |
| | 2. `article:h:<hash12(title, year, type, venue)>` | |
| `production` | `production:h:<hash12(title, year, production type)>` | |
| children of a person | `<person id>/education:h:<hash12(type, course, start year)>` | `person:lattes:9860…/education:h:e7c38e0af1df` |
| | `<person id>/activity:h:<hash12(institution, start, end, role, bond)>` | |
| | `<person id>/award:h:<hash12(title, year)>` | |
| | `<person id>/proficiency:<language slug>` | `person:lattes:9860…/proficiency:ingles` |
| `team` (not a research group) | `<id of the initiative it staffs>/team` (alphabetically first if several) | `initiative:sigpesq-pj:2342/team` |
| | else `team:h:<hash12(name)>` | |
| `fellowship` | `fellowship:<slug(name)>:<value>` | `fellowship:pibiti:700` |
| reference | `knowledge-area:`, `organization:`, `campus:`, `initiative-type:`, `production-type:`, `role:`, `language:`, `education-type:` + slug | `campus:serra`, `knowledge-area:educacao` |

## Never in an id

- Any numeric database id.
- CPF, e-mail address or phone number, in clear or hashed.
- Anything derived from `HORIZON_PII_HMAC_KEY` or any other secret.
- Processing order.

## Collisions (FR-008)

When two rows derive the same id, each gets `~<hex6>` from the hash of the
name of its source document of origin. A Lattes CV is named
`lattes:<lattes_id>`, never its file name, which starts with the CV's
position in the Lattes list. Any other document is named by its file name,
never its path, which depends on the checkout. If they still collide, rows ordered by the
canonical hash of their content get `~2`, `~3`, …, and the first keeps the
step-1 id. On the 2026-10-24 database this happens in 149 groups, all rows
duplicated in the database by case or accent (research R2).

## Stability promises

| Event | What happens to the id |
|---|---|
| Next weekly, same source data | Same id |
| `make full-refresh` or rule-version rebuild | Same id for the same source data; ids that change become aliases (`rebuild`) |
| Entity gains a higher-priority source id | New id current; old one alias (`upgraded key`), children too |
| Two entities merged | Survivor keeps the highest-priority id; the other is an alias (`merge`) |
| Source corrects the text of a computed key | New id current; old one alias (`key corrected`) if exactly one similar candidate (token-sort ratio ≥ 90) in the same document; else the old id is retired |
| Entity disappears | Old id retired, never reused for something else |
