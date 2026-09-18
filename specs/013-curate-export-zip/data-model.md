# Data Model: Curated Export Archive

**Branch**: `013-curate-export-zip` | **Date**: 2026-09-18

No database entities change. This document models the artifact shapes and the
per-document state transitions the feature introduces.

## Entity 1 — Export archive (`exports_canonical.zip`)

The single versioned deliverable written by `zip_exports_task(output_dir)`.

### Contents manifest

| Entry kind | Source | Treatment |
|---|---|---|
| Canonical export JSONs (`*_canonical.json`, marts, graphs, tracking, …) | `os.walk(output_dir)` | Included verbatim (unchanged behavior) |
| Nested report/format folders `docentes/…`, `formandos/…`, `mestrado/…`, `parquet/…` | walk | **Pruned** (`SKIP_DIRS`) |
| Raw project corpus `project_sigpesq_files_json/` | walk | **Pruned** (never enters the zip raw) |
| Any file `*.zip` (incl. `data_snapshot.zip`, the archive itself, its `.tmp`) | walk | **Skipped** by name |
| Scrubbed project documents `project_sigpesq_files_json/PJ_*.json` | explicit post-walk block | **Added** after anonymization |

### Invariants (tested)

- INV-1: every `PJ_*.json` present in the raw corpus appears exactly once in
  the archive, same filename, path prefix `project_sigpesq_files_json/`.
- INV-2: no archive member contains a clear-text e-mail or phone number.
- INV-3: no archive member path ends with `.zip` and no member path starts
  with `formandos/`, `docentes/`, `mestrado/`, or `parquet/`.
- INV-4: all members outside the excluded kinds are byte-identical to their
  on-disk sources (no accidental re-encoding).
- INV-5: archive generation succeeds when any/all source categories are
  absent.

## Entity 2 — Scrubbed project document (`PJ_<code>.json` copy)

The archived copy of a `Projeto` extraction result (pydantic model dumped
`by_alias=True` by the pinned `agent_sigpesq` library). Shape is unchanged by
this feature; only leaf string values may be transformed.

### Field treatment map

| Field | Type | Treatment |
|---|---|---|
| `coordenador.email` | string (e-mail) | → `<sha256[:12]>@anon.lgpd` |
| `coordenador.nome`, `equipe[].nome` | strings (names) | **unchanged** (catalogue policy: names ship) |
| any string containing a phone pattern (area code or +55) | string | matched substring → `LGPD-PHONE-<sha256[:16]>` |
| any other string (descricao, objetivos, cronograma, `_meta.*`, …) | string | e-mail/phone regex scrub only; otherwise verbatim |
| numbers, lists of dicts, booleans | — | recursed, never re-typed |

### Rules

- SCR-1: scrubbing is idempotent — already-anonymized tokens pass through
  unchanged (`is_anonymized_email` / `is_anonymized_phone` guards).
- SCR-2: the on-disk raw file is never rewritten; transformation happens in
  memory between `json.load` and `zf.writestr`.
- SCR-3: a raw file that fails to parse is skipped individually with a
  warning; the archive is still produced.

## Entity 3 — Extraction stats (`extract_json` return)

Extended by one counter:

| Key | Meaning | Change |
|---|---|---|
| `pdfs` | PDFs found | unchanged |
| `extracted` | paid extraction calls that succeeded | unchanged semantics |
| `skipped` | PDFs whose local JSON already existed | unchanged |
| **`reused`** | pending PDFs satisfied from the archive (no extractor call) | **NEW** |
| `errors` | extractor failures | unchanged |

Log line "… already extracted (skipped) … to extract" gains the reused count
so a run is auditable at a glance (constitution IV).

## Entity 4 — Pending-PDF decision state machine

Per PDF `PJ_<code>.pdf` (stem = filename without extension):

```text
                 ┌────────────────────────────┐
                 │ PDF present in pdf_dir     │
                 └────────────┬───────────────┘
                              ▼
                 local JSON exists at json_dir?
                    yes ───────────────► skipped (no archive consult)   [R11]
                    no
                              ▼
                 force == True?
                    yes ───────────────► paid extraction (bypass reuse)  [R14]
                    no
                              ▼
                 archive readable & entry
                 project_sigpesq_files_json/<stem>.json exists?
                    no  ───────────────► paid extraction                 [R15]
                    yes
                              ▼
                 entry parses as JSON?
                    no  ───────────────► paid extraction (warn)          [R15]
                    yes ───────────────► REUSE: write parsed copy to
                                         json_dir, stats["reused"] += 1,
                                         zero extractor calls            [R12]
```

Notes:
- Matching is by stem only (the stem encodes the SigPesq project code).
- Reuse writes the **archived (anonymized) copy**; per spec assumption, mixed
  anonymization across the local corpus is acceptable because enrichment
  never consumes contact fields.
- The archive consulted is the one in the export folder — always the previous
  run's archive during a weekly run (see research.md D4 timing note).
