# Contract: Export Campus Resolution

**Feature**: `010-campus-resolution-fallback`

`ExportCampusResolver` is an internal interface consumed by
`CanonicalExporter` and `MartGenerator`. This contract fixes the behaviour they
may rely on; it is the reference for the resolver's unit tests.

## Interface

```
get_campus(entity_type: str, entity_id: Any) -> Optional[dict]
```

Returns `{"id": int, "name": str}` or `None`. The signature is unchanged by
this feature.

Supported `entity_type` values (unchanged): `campus`, `research_group`,
`initiative`, `advisorship`, `researcher`, `article`, `knowledge_area`,
`source_record`, `ingestion_run`.

## Guarantees

| ID | Guarantee |
|----|-----------|
| C-01 | For a given database state, `get_campus` returns the same answer on every call and on every process run. |
| C-02 | An entity with no evidence returns `None`. The resolver never invents, defaults, or substitutes a campus. |
| C-03 | A `researcher` with direct evidence resolves from direct evidence alone; supervisor inference cannot override it. |
| C-04 | A `researcher` with no direct evidence resolves to the weighted-dominant campus of the `Supervisor` members of their advisorships, or `None` if no such supervisor has a campus. |
| C-05 | Supervisor inference is computed from directly-evidenced campuses only; an inferred campus is never an input to another inference. |
| C-06 | An `initiative` or `advisorship` with an asserted `execution_campus_id` resolves to that campus even when it has no linked research group. |
| C-07 | Asserted execution campus and research-group membership are the same level of authority; when they disagree, weight decides, and the loser is not discarded silently — both remain countable evidence. Group membership carries weight 3 to the execution campus weight of 1, so the group is unseated only by clear dominance (research.md R8). |
| C-08 | Equal weights are broken by campus name, then by campus id — the ordering the resolver already applies. |
| C-09 | A campus id that does not correspond to a loaded campus is ignored rather than exported as a dangling reference. |
| C-10 | A failing internal query degrades to "no evidence from that source" and is logged; it never raises out of `get_campus`. |

## Non-guarantees

- No ordering or stability is promised across *different* database states.
- The resolver does not deduplicate people; it consumes whatever identity
  resolution the consolidator produced.
- Campus is not promised to be the person's employment campus — it is the
  dominant campus of their recorded research activity.

## Ingestion-side contract

| ID | Guarantee |
|----|-----------|
| I-01 | A SigPesq row stating an execution campus produces `execution_campus_id` and `execution_campus_name` assertions on the resulting initiative or advisorship, whether or not the row names a research group. |
| I-02 | Campus names differing only in case, accents, surrounding whitespace, or a leading `"Campus "` token resolve to one campus record; none of those variants creates a new campus. |
| I-03 | An unresolvable campus name never aborts the ingestion of its row. |
| I-04 | Existing behaviour is preserved: when a row does name a research group, that group still receives its campus as it does today. |
