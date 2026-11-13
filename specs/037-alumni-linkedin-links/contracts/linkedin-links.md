# Contract: LinkedIn links from a local list

**Feature**: `037-alumni-linkedin-links`

## 1. `normalize_profile_link(text) -> Optional[str]`

Module `src/core/logic/linkedin_links.py`, pure.

| Input | Result |
|-------|--------|
| `https://www.linkedin.com/in/maria-silva` | `https://www.linkedin.com/in/maria-silva` |
| `http://linkedin.com/in/maria-silva/` | `https://www.linkedin.com/in/maria-silva` |
| `linkedin.com/in/maria-silva` | `https://www.linkedin.com/in/maria-silva` |
| `www.linkedin.com/in/maria-silva?utm_source=share&utm_medium=x` | `https://www.linkedin.com/in/maria-silva` |
| `https://br.linkedin.com/in/maria-silva#about` | `https://www.linkedin.com/in/maria-silva` |
| `HTTPS://WWW.LinkedIn.com/in/Maria-Silva` | `https://www.linkedin.com/in/Maria-Silva` (host lowered, profile as written) |
| `https://www.linkedin.com/in/jo%C3%A3o-souza-1a2b3c` | the same, unchanged |
| `https://www.linkedin.com/in/maria-silva/details/experience/` | `https://www.linkedin.com/in/maria-silva` |
| `  https://www.linkedin.com/in/maria-silva  ` | `https://www.linkedin.com/in/maria-silva` |
| `https://www.linkedin.com/company/ifes` | `None` |
| `https://www.linkedin.com/school/ifes/`, `.../posts/...`, `.../feed/` | `None` |
| `https://www.linkedin.com/in/` (no profile) | `None` |
| `https://example.com/in/maria-silva`, `https://notlinkedin.com/in/x` | `None` |
| `maria-silva`, `""`, `None` | `None` |

## 2. `parse_list(lines) -> list[ListLine]`

| Line | Result |
|------|--------|
| `https://www.linkedin.com/in/maria,Maria da Silva` | link normal, name `Maria da Silva`, no problem |
| `  linkedin.com/in/maria/ ,  Maria da Silva  ` | the same |
| `https://www.linkedin.com/in/maria,Silva, Maria da` | name `Silva, Maria da` (split at the first comma) |
| empty line, spaces only, `# anything` | not returned |
| `https://www.linkedin.com/in/maria` (no comma) | `invalid` |
| `https://www.linkedin.com/in/maria,` (no name) | `invalid` |
| `https://www.linkedin.com/company/x,Maria da Silva` | `invalid`, name kept for the report |
| `,Maria da Silva` | `invalid` |

`number` is the line's position in the file, counting ignored lines.

## 3. `plan(lines, persons, stored) -> Plan`

`persons`: pairs `(person id, name)`. `stored`: `person id -> (link, listed
name)`. `Plan`: `add`, `change`, `remove` and `outcomes` (one per line).

| Case | Outcome | Change |
|------|---------|--------|
| name equals one person's name ignoring case, accents and spaces; no row stored | `stored` | add |
| the same, the same link stored | `stored` | none |
| the same, another link stored | `stored` | change |
| name matches no person | `not_found` | none |
| name matches two or more persons | `several_persons` | none for any of them |
| the same name (normalized) on two lines with the same link | one `stored`, counted once | as a single line |
| the same name on two lines with different links | both `conflict` | none; a stored link of that person is removed |
| the same link on the lines of two different names | both `conflict` | none; stored links of those persons are removed |
| invalid line | `invalid` | none |
| a stored row whose person has no `stored` outcome, list with one usable line or more | (no line) | remove |
| a stored row whose person no longer exists, list with one usable line or more | (no line) | remove |
| no line with outcome `stored` in the whole list | outcomes as above | no add, change or remove at all |

Properties: `plan` of the same inputs gives the same result; applying a plan
and planning again with the same list gives no change; the persons with a
link after applying are exactly the persons of the `stored` outcomes.

## 4. The step (`app.py linkedin_links`, weekly phase `linkedin_links`)

| Situation | Result |
|-----------|--------|
| no file at `data/linkedin_run/linkedin.list` | exit 0; log `no list ... nothing changed`; table untouched; report with `list_found: false` |
| file with no usable line | exit 0; warning that the list is empty; table untouched |
| file with usable lines | table made equal to the plan; summary line; one line per unused line with name and reason; report written |
| the same file again | exit 0; no row written; summary with added 0, changed 0, removed 0 |
| database without the table (created before the feature) | the migration creates it first |
| the step fails | the weekly continues (phase not critical); the exports carry the links stored before |

The step never writes the list, never reads outside the repository, never
creates, renames or deletes a person.

Order in the weekly: after `consolidate_duplicates`, before
`assign_horizon_ids` and `export_canonical`.

## 5. Merge hook (`repoint_linkedin_link(conn, winner_id, loser_id)`)

| Loser has a link | Winner has a link | Result |
|------------------|-------------------|--------|
| yes | no | the row now belongs to the winner |
| yes | yes | the winner's row stays; the loser's row is deleted |
| no | any | nothing |
| the table does not exist | any | nothing |

## 6. Exports

| Person | `linkedin_url` in the person entry |
|--------|-------------------------------------|
| has a row in `person_linkedin_links` | the stored link |
| has no row | `null` (the key is always present) |
| the table does not exist | `null` for everyone |

The field is added to the person entry of `researchers_canonical.json` and of
the classification files built from it. No other key of the entry and no
other file changes.
