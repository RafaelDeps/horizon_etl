# Contract: Field Claims and Resolution

**Branch**: `030-deterministic-field-merge`

This is an internal contract between the loaders, a new core module and a new
adapter. Nothing external changes: the exports keep their schema, and only
the values of the fields of FR-006 change.

## Port: `src/core/ports/field_claim_store.py`

```python
@dataclass(frozen=True)
class FieldClaim:
    source_system: str
    document_key: str
    entity_type: str        # "initiative" | "advisorship" | "fellowship"
    entity_id: int
    field: str
    value: Any              # JSON-serializable, PII-scrubbed
    doc_date: Optional[str] # ISO date or None
    source_rank: int        # 0 Lattes, 1 SigPesq, 2 CNPq
    tie_key: str

class IFieldClaimStore(ABC):
    def replace_document_claims(self, source_system: str, document_key: str,
                                claims: Iterable[FieldClaim]
                                ) -> Dict[Tuple[str, int], Set[str]]:
        """Replace every claim of the document. Returns, for each
        (entity_type, entity_id) it claimed before or claims now, the fields
        of those claims. Only these fields are resolved again (see below)."""
    def drop_document_claims(self, source_system: str, document_key: str
                             ) -> Set[Tuple[str, int]]:
        """Remove the claims of a deleted document; returns the touched entities."""
    def drop_entity_claims(self, source_system: str, document_key: str,
                           entity_type: str, entity_id: int) -> None:
        """Remove the claims of one item the document no longer carries."""
    def claims_for(self, entity_type: str, entity_id: int) -> List[FieldClaim]:
        """Every claim of the entity, from every source."""
    def move_claims(self, entity_type: str, from_id: int, to_id: int) -> None:
        """Merge of duplicates: claims of from_id go to to_id."""
```

The adapter is `src/adapters/database/field_claim_store.py`. It writes through
the connection of the `DocumentTransaction`, so a rollback discards the claims
with the rest of the document.

## Core: `src/core/logic/field_merge.py`

```python
EMPTY_STATUS = {"unknown"}

def claim_sort_key(claim: FieldClaim) -> tuple: ...
def is_empty(field: str, value: Any) -> bool: ...
def resolve(claims: List[FieldClaim]) -> Dict[str, Resolution]:
    """Field -> Resolution(value, decided_by) for every field with a
    non-empty claim. decided_by is one of "single", "by_date", "by_source",
    "by_tiebreak". Pure: no I/O, so it is order-free by construction."""

def lattes_document_date(cv_json: dict) -> Optional[str]:
    """informacoes_pessoais.atualizacao_cv (dd/mm/yyyy) -> ISO date, or None."""

class FieldMergeStats:      # counts of research R10, one per phase
    def log(self, phase: str) -> None: ...
```

Merged fields: `status`, `description`, `start_date` and `end_date` of
initiatives and advisorships, `cancelled` of advisorships, and `value` of
fellowships. `cancelled` is claimed only by SigPesq workplans: a workplan whose
student was replaced has a cancelled row and a new row writing the same
advisorship, and the highest SigPesq Id decides. It is compared as a boolean
(`True`/`1`/`"1"` are one value), so the stored `0`/`1` never looks changed.
The writer reads and writes it in `advisorships`, the other fields of an
advisorship in `initiatives`.

`resolve` is a pure function. Calling it on any permutation of the same claims
gives the same result. SC-002 rests on this, and it is unit-tested with
property-style permutations.

## Applying the result: `FieldMergeApplier` (core, uses ports only)

```python
class FieldMergeApplier:
    def __init__(self, store: IFieldClaimStore, writer: IFieldWriter,
                 stats: FieldMergeStats): ...
    def apply(self, touched: Union[Iterable[Tuple[str, int]],
                                   Mapping[Tuple[str, int], Iterable[str]]]) -> int:
        """For each entity: claims_for -> resolve -> write only the fields
        whose winning value differs from the stored one (research R5). Returns
        the number of fields written."""
```

With a mapping (what `replace_document_claims` returns), only the fields the
document claimed, before or now, are resolved. A document never rewrites a
field it did not claim. This matters for parent projects: a project PDF claims
only the description, and resolving its dates and status as well would undo
the values `recalculate_parent_projects` derives from the children. The
replay of 2026-11-06 found this on 28 parent projects (pass 3, enrichment run
alone).

`IFieldWriter` reads and writes the stored values of `initiatives`,
`advisorships` and `fellowships`. Its adapter does it in the document's
transaction, so `ProjectLoader.flush_change_log` sees the final state and logs
one net change.

## Callers

| Caller | When | What it does |
|---|---|---|
| `ProjectLoader._process_row` (SigPesq projects, Lattes projects) | after `handler.create_or_update` | collects one claim per FR-006 field from `project_data`, with the document's date, rank and tie key |
| `AdvisorshipHandler` (SigPesq and Lattes advisorships) | after create or update | same for the advisorship fields; plus the `fellowship.value` claim (SigPesq workplans only) |
| document end (`DocumentSkip._commit`, before `commit_processed`) | once per processed document | `replace_document_claims`, then `FieldMergeApplier.apply(touched)` |
| deletions of branch 024 (`commit_processed` deletions) | per deleted item or document | `drop_*`, then `apply` on the touched entities |
| `ProjectEnrichmentLoader._enrich_winners` | per enriched initiative | PDF description claim (rank SigPesq, tie `1|code`), then `apply` |
| `ReferenceConsolidator` merge | per merged pair | `move_claims`, then `apply` on the winner |

## Log line (FR-013)

One INFO line per phase, after the document summary of branch 024:

```
field merge <phase>: fields=<n> by_date=<n> by_source=<n> by_tiebreak=<n> collisions_resolved=<n> collisions_reported=<n>
```

A `title_collision` WARNING for each project not stored because its name
belongs to an advisorship (FR-011):

```
title collision: lattes_projects <lattes_id> project '<title>' has the name of advisorship <id>; not stored
```

## Errors

- An error in a claim write or in a resolution raises inside the document. The
  document is rolled back and recorded as failed, as for any other error
  (branch 024 contract).
- An unreadable CV date is not an error. The claims get `doc_date=None`, and
  the run counts them in a `dates_missing=<n>` field of the log line.
