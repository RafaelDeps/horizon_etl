# Contract: `strategy_from_prior` and the unchanged-note skip

Module: `src/core/logic/project_enrichment.py`

## `strategy_from_prior(prior, origin, strategy, code, source_file) -> str`

Pure function: no database, file or clock access. Never raises.

| Argument | Type | Meaning |
|----------|------|---------|
| `prior` | `Optional[dict]` | the note stored for the initiative, or `None` |
| `origin` | `str` | the resolved origin (`origin_from_prior`) |
| `strategy` | `str` | how the document matched in this run |
| `code` | `Optional[str]` | the document's normalized code; empty means none |
| `source_file` | `Optional[str]` | the document's `_meta.arquivo` |

Returns `new_from_document` when all hold, otherwise `strategy`:

1. `origin == "new_from_document"`;
2. `prior` is a dict;
3. `strategy in {"title_exact", "title_fuzzy"}`;
4. same document: with a `code`, `prior["project_code"] == code`; without one,
   `source_file` is truthy and `prior["source_file"] == source_file`.

Examples:

| prior (relevant keys) | origin | strategy | code | file | result |
|-----------------------|--------|----------|------|------|--------|
| code `1`, strategy `new_from_document` | new | `title_exact` | `1` | - | `new_from_document` |
| code `1`, strategy `title_exact` (drifted) | new | `title_exact` | `1` | - | `new_from_document` |
| code `1` | new | `title_exact` | `2` | - | `title_exact` |
| code `1` | new | `sigpesq_project_code` | `1` | - | `sigpesq_project_code` |
| code `null`, file `PJ_x.pdf` | new | `title_exact` | `""` | `PJ_x.pdf` | `new_from_document` |
| code `null`, file `PJ_x.pdf` | new | `title_exact` | `""` | `PJ_y.pdf` | `title_exact` |
| any | matched_existing | `title_exact` | any | any | `title_exact` |
| `None` | new | `new_from_document` | any | any | `new_from_document` |

`build_enrichment` stores its result in `match_strategy`. Its other fields are
built as before.

## `_enrich_winners`: unchanged note

When `canonical(enrichment) == canonical(prior)` and no description is to be
written for the row, the loader does not run the `enrichment_json` UPDATE; the
row counts as written, so the description merge, `entity_matches` tracking and
the counters run as before, and `changed=False` keeps the change log empty.
`dry_run` behaviour is unchanged.
