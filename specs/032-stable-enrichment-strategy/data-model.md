# Data Model: Stable enrichment strategy for document-created projects

No table, column or export shape changes. This feature changes when one field
of an existing JSON payload is rewritten.

## Enrichment note (`initiatives.enrichment_json`, `EnrichmentPayload`)

| Field | Meaning | Changed by this feature |
|-------|---------|-------------------------|
| `source` | always `sigpesq_project_files` | no |
| `project_code` | normalized code of the document that wrote the note, or `null` | no (read by the rule) |
| `source_file` | PDF name (`_meta.arquivo`) of that document | no (read by the rule) |
| `origin` | `new_from_document` or `matched_existing`; permanent | no (read by the rule) |
| `match_strategy` | how the document matched | **yes**: see the rule below |
| `needs_review`, `reviewed_at`, `reviewed_by` | review state | no |
| content fields (`objetivos`, `cronograma`, ...) | from the PDF | no |

## Rule for `match_strategy`

Inputs: the prior note (may be absent), the resolved origin
(`origin_from_prior`), the current document's code and file, the current
match strategy.

```text
if origin == new_from_document
   and prior exists
   and current strategy in {title_exact, title_fuzzy}
   and same document:
       match_strategy = new_from_document
else:
       match_strategy = current strategy

same document:
    current code set    -> current code == prior.project_code
    current code empty  -> current file set and current file == prior.source_file
```

## State transitions of a document-created note

| Run | Before | After |
|-----|--------|-------|
| creation | (no initiative) | origin `new_from_document`, strategy `new_from_document` |
| next run, same document, title match | strategy `new_from_document` | unchanged, no UPDATE, no change log |
| first run after this feature, drifted note | strategy `title_exact` | strategy `new_from_document` (one change) |
| later, same document, code match | any | strategy `sigpesq_project_code` |
| later, another document, any match | any | that document's strategy |

## Unchanged tracking

- `entity_matches.match_strategy`: the real strategy of each run.
- `entity_change_logs`: a row only when the canonical note or the description
  changed.
