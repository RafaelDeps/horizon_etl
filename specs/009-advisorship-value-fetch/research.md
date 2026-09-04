# Research: Advisorship Canonical Data Values Fetch

Phase 0 output of `/speckit.plan`. Every unresolved/undecided point from the spec
is answered here with a Decision + Rationale + Alternatives considered.

## 0. Summary of the problem

The canonical advisorship export (`advisorships_canonical.json`) does not carry the
advisorship **program** (category) or **provider** (funder), and carries no report **year**.
In the DB all 3,199 `advisorships.program` / `advisorships.type` values are NULL;
only 506 advisorship rows are linked to a `Fellowship`, so for 84% of rows the program
is nowhere in the canonical data. Meanwhile the SigPesq report rows that created them
hold `Programa` + `AgFinanciadora` (+ the advisorship `Ano`), and these rows survive
anonymized in `source_records.raw_payload_json`.

## 1. Decision: where the category values come from

**Decision:** Read `program` and `provider` for each advisorship from its SigPesq
`source_records.raw_payload_json` (`Programa`, `AgFinanciadora`) via an
`entity_matches` join at export time, with precedence fallback to the
advisorship DB columns and the linked fellowship when present. Additionally,
for new ingestions (FR-007), persist the program into the existing
`advisorships.program` column so the value exists in the DB and the export
consumes it directly.

**Rationale:**
- `source_records` are the only per-row, per-year authoritative copy of the category
  for the 2,693 advisorship rows that have no fellowship. Re-deriving from the raw
  `.xlsx` files would require re-ingestion or re-reading stale raw dirs (constitution:
  raw files are ephemeral). The payloads are already stored (schema `raw_payload_json`,
  PII already masked at write).
- The `advisorships.program` column already exists (research_domain
  `Advisorship.program`, String(500)) — no schema change required.
- `Advisorship.type` is an `AdvisorshipType` enum (academic level: Scientific
  Initiation, PhD Thesis, ...), NOT the program/provider concept; the user confirmed
  category = program + provider, so `type` is left untouched (still NULL).
- Provider has no dedicated column; it lives on the fellowship's sponsor and in the
  payload. Keep it in those two places; the export resolves it from payload →
  fellowship sponsor.

**Alternatives considered:**
- Re-ingest all year reports to reconstruct fellowship linkage. Rejected: heavy,
  violates the "DB is single source of truth" spirit, and the raw files are cleaned
  between runs.
- Populate program only at ingestion (no export-side source join). Rejected: the
  3,199 existing rows would stay empty until every report is re-ingested; that does
  not fix today's export.
- Compute from `start_date`/`end_date`. Rejected: cannot express the program or provider.

## 2. Decision: the "specific year" rule (Q2=A, refined)

**Decision:** Each canonical advisorship gets a `year` field:
1. For SigPesq-sourced rows: the **report/directory year** (`source_path` containing
   `.../advisorships/YYYY/...`), per the user's Q2=A answer.
2. If an advisorship resolved to multiple SigPesq source records (observed: same row
   `Id`/`Orientador` can appear under several report directories), pick the record
   whose directory year **equals the payload `Ano`**; if none matches, take the most
   recent directory year. (Observed real case: `Id 4882`, `Ano=2021`, present under
   both `advisorships/2021/` and `advisorships/2022/`.)
3. For Lattes-sourced rows (no response reports): use the payload `year` /
   `ano_conclusao` / `ano_inicio`; Lattes CVs have no report directory.
4. If no source record yields a year, the field is `null` (explicit, documented).

**Rationale:** Q2=A literally defines the year from the report/directory. The data
showed the directory is not always equal to `Ano`, and the same advisorship can appear
in multiple directories — the `Ano` match is used purely as a tie-breaker, keeping the
definition aligned with the user's chosen semantics.

**Alternatives considered:**
- Always use payload `Ano`. Rejected: contradicts the user's explicit Q2=A decision
  that the year is the report/directory year.
- Always use the most recent directory year. Rejected: loses the association when the
  advisorship truly belongs to an earlier report year.

## 3. Decision: normalization & representation

**Decision:** Preserve the report's spelling for both fields (trimmed): `program` from
`Programa` (e.g., `Pibic`, `Picti`, `Pivic`), `provider` from `AgFinanciadora`
(e.g., `Fapes`, `Ifes`, `Cnpq`, `Voluntário`). NULL → `null` in JSON (never `"N/A"`).
Lattes-sourced rows export `program: null`, `provider: null` — the defined value is
"not reported by the source" (FR-008), documented in the contract.

**Rationale:** FR-001/SC-001 require values "matching the report row", not a re-cased
normalization. The fellowship name convention (UPPERCASE) is a different artifact
(`fellowships_canonical.json`); re-casing here would break parity with the source.

**Alternatives considered:**
- Uppercase on export to match fellowship names. Rejected: differs from report parity.
- `"N/A"`/empty string sentinel. Rejected: `null` is the JSON-native explicit "absent".

## 4. Decision: export contract

**Decision:** Add three **additive** keys to every advisorship object in
`advisorships_canonical.json`: `year` (int|null), `program` (string|null),
`provider` (string|null). Backward compatible (FR-005); no existing key is renamed or
retyped.

**Rationale:** Scope decision Q3=C limits the change to this artifact; additive fields
are the lowest-risk change and let PH dashboards read them incrementally.

## 5. Decision: ingestion changes (FR-007)

**Decision:** `SigPesqAdvisorshipMappingStrategy` adds `program` to its return dict
(the trimmed report `Programa`); `AdvisorshipHandler._handle_advisorship_details`
persists `initiative.program` (create and update paths). `LattesAdvisorshipMappingStrategy`
does not set program/provider (source does not carry them).

**Rationale:** Populating the DB column makes new ingestions self-describing while the
export-side source join covers the historical rows. Wires cleanly through the existing
strategy → handler → controller flow (no new entity fields).

## 6. Decision: LGPD (FR-006)

**Decision:** Only the non-PII keys `Programa`, `AgFinanciadora`, `Ano` are read from
the payload. No email/phone/CPF key is ever surfaced. Payloads are already masked at
write time; the canonical export already passes through `scrub_pii_deep` on person
files; for this artifact the only new data is program/provider/year which are not PII.

## 7. Verification / audit (FR-004)

**Decision:** Parity is verified (a) by the unit/integration tests in
`tests/test_canonical_exporter.py` (every advisorship present; new fields populated for
SigPesq rows, null for Lattes) and (b) by the runnable validations in `quickstart.md`.

## 8. Research gaps → plan

- `entity_matches` + `source_records` join for advisorship already demonstrated
  (3,808 advisorship source records; sigpesq 701, lattes 3,107). No gap.
- Files to touch are limited to `src/core/logic/` + `tests/` (details in `plan.md`).