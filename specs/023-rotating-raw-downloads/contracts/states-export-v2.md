# Contract: `source_document_states_canonical.json` with `downloaded_at`

Extends the spec 021 contract
(`specs/021-skip-unchanged-documents/contracts/source-document-states-export.md`).
It is the only export that changes, and it changes only by adding one field.

```json
{
  "rule_version": 1,
  "generated_at": "2026-11-07T04:12:09Z",
  "documents": [
    {
      "source_system": "cnpq_group",
      "document_key": "cnpq:4439471564090237",
      "status": "active",
      "last_seen_at": "2026-11-07T03:10:44Z",
      "processed_at": "2026-10-31T03:12:02Z",
      "downloaded_at": "2026-11-07T02:12:44Z"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `downloaded_at` | ISO-8601 UTC of the download the document's current data comes from, or `null` when no run after this spec has read it yet. For a Lattes CV it is the curriculum's download; for a CNPq group, its page's; for a SigPesq row, its report's. |

Reading guide for consumers: `downloaded_at` tells how old the data is. A
date a few weeks old is normal with the default rotation (every item is
downloaded again about every four weeks). Data older than that is still
exported, because old data is better than none; it means the source could
not be downloaded since.

Sorting, privacy and the other fields are unchanged.
