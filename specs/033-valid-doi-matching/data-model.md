# Data Model: Only real DOIs identify an article

No table, column or export field is added or removed. The feature changes
which values one field may hold and what is derived from it.

## DOI value

| State | Meaning | Example |
|-------|---------|---------|
| Raw | The text of the curriculum's DOI field, as written | `http://www.scopus.com/…&doi=10.1186/1753-6561-8-s4-p29&md5=…` |
| Cleaned | The DOI read from the raw text by the rule (contracts/doi-rule.md) | `10.1186/1753-6561-8-s4-p29` |
| None | The raw text is empty or has no DOI form after cleaning | raw `1982-9434` -> none |

Validation: a cleaned DOI matches `10.` + 4 to 9 digits (+ optional
`.digits`) + `/` + a non-empty suffix without spaces, in lower case.

## Where each state lives

| Place | Before | After |
|-------|--------|-------|
| `source_records.raw_payload_json` (curriculum item) | Raw | Raw (unchanged, FR-008) |
| `articles.doi` | Raw | Cleaned, or empty |
| Exported article `doi` (`articles_canonical.json` and the files built from it) | Raw | Cleaned, or empty |
| `attribute_assertions` value for `doi` | Raw | Cleaned, or empty |
| `entity_change_logs` (`create`, `Filled missing article fields`) | Raw | Cleaned, or empty |
| `entity_matches.match_strategy` | `doi_exact` when the raw text is not empty | `doi_exact` only when there is a cleaned DOI; `title_year` otherwise |
| Article permanent id (`horizon_ids`) | `article:doi:<raw without address, lower case>` | `article:doi:<cleaned>`; content id when none |
| Tracking key of the item (`source_records.source_record_id`) | curriculum + raw-based DOI (or title and year) + venue fields | curriculum + cleaned DOI (or title and year) + venue fields |

## Article identity (unchanged rule, new input)

1. An item with a cleaned DOI is the stored article with the same cleaned DOI,
   whatever the titles.
2. Otherwise it is the stored article with the same normalized title and year,
   unless both have a cleaned DOI and the DOIs differ.
3. Otherwise a new article is created.

An existing article without a DOI takes the cleaned DOI of a later item of the
same work; a stored DOI is never overwritten.

## Identity rule version

| Field | Before | After |
|-------|--------|-------|
| `HORIZON_RULE_VERSION` (code) | 2 | 3 |
| `horizon_meta.rule_version` (database) | 2 | 3 after the rebuild |

State transition of a database: recorded version 2 and code version 3 ->
the weekly rebuilds it once before the phases -> recorded version 3 ->
later runs are incremental. Old article ids that no longer exist become
aliases through the existing id history.
