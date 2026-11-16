# Data Model: LinkedIn links from a local list

**Feature**: `037-alumni-linkedin-links`

## 1. The list (local input, not versioned)

`data/linkedin_run/linkedin.list`, UTF-8 text, one person per line:

```text
# comment
https://www.linkedin.com/in/maria-silva,Maria da Silva
linkedin.com/in/joao-souza/,João Souza
```

| Part | Rule |
|------|------|
| Line | split at the first comma: link, then name; spaces around both ignored |
| Empty line, line starting with `#` | ignored, not counted |
| Link | must be a LinkedIn profile address; stored in the normal form |
| Name | full name; compared with person names ignoring case, accents and spaces |

Parsed line (`ListLine`): `number` (line number in the file), `link` (normal
form or `None`), `name` (as written, trimmed), `problem` (`None` or
`invalid`).

## 2. `person_linkedin_links` (new, ETL-owned; migration 0015)

| Column | Type | Rule |
|--------|------|------|
| `person_id` | INTEGER PRIMARY KEY | id of a row of `persons`; one link per person |
| `linkedin_url` | TEXT NOT NULL UNIQUE | normal form `https://www.linkedin.com/in/<profile>`; one person per link |
| `listed_name` | TEXT NOT NULL | the name as written in the list, kept for audit |
| `updated_at` | TEXT NOT NULL | UTC timestamp of the last change of the row; unchanged when the row is unchanged |

No foreign key is declared (the ETL's other tables do not declare them
either); the step removes rows whose person is gone when it reads a usable
list, and the merge hook moves a row to the surviving person.

State of a row:

| Event | Result |
|-------|--------|
| usable line, person without a row | row inserted |
| usable line, same link stored | nothing |
| usable line, another link stored | `linkedin_url`, `listed_name`, `updated_at` replaced |
| stored row with no usable line for that person (list with at least one usable line) | row deleted |
| no list file, or list with no usable line | nothing |
| person merged into another (consolidation) | row moves to the surviving person unless that person already has one |

## 3. Line outcome (reported, not stored)

| Outcome | Meaning |
|---------|---------|
| `stored` | the name matches exactly one person; the link is (or stays) stored |
| `not_found` | the name matches no person |
| `several_persons` | the name matches more than one person |
| `conflict` | the name is on lines with different links, or the link is on lines of different names |
| `invalid` | no comma, no name, or a link that is not a LinkedIn profile address |

## 4. Exports

| File | Change |
|------|--------|
| `researchers_canonical.json` (every person) | each entry gains `linkedin_url`: the stored link, or `null` |
| `students_canonical.json`, `researchers_only_canonical.json`, `outside_ifes_canonical.json`, `null_researchers_canonical.json` | the same entry, so the same field |
| every other export | unchanged |

## 5. Report

`data/reports/linkedin_links_report.json` (ignored by git): `list_path`,
`list_found`, `lines`, `stored`, `added`, `changed`, `removed`, `not_found`,
`several_persons`, `conflicts`, `invalid`, and `unused`: a list of
`{line, name, reason}`.

## 6. What does not change

`persons`, `researchers` and every library table; `horizon_ids`,
`horizon_meta` (rule version stays 6); tracking tables; document states.
