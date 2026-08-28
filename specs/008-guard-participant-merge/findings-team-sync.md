## Follow-ups — origin: `specs/008-guard-participant-merge` (2026-08-28)

- **TD-011 — Lattes project sync wiped SigPesq students from project teams**:
  observed while validating dedup on the real run — the fresh
  `researchers_canonical.json` showed "Israel Magalhães do Carmo" (person 579)
  with **5** initiatives vs. the previously deployed run (person 567) with **9**.
  The four missing memberships were "*Research Project*" team links (BPM
  Pós-Gestão + 3× Air Writing). Root cause, confirmed from DB artifacts only (no
  replay needed):
  1. `sigpesq` loads the project team correctly — raw row
     `research_projects/Relatorio_28_08_2026.xlsx` (SR 367) lists "Israel
     Magalhães do Carmo" under `Estudantes` of PJ 8438.
  2. `ingest_lattes_projects` runs **after** SigPesq and upserts the *same*
     initiative (`entity_matches` SR 2563 → initiative 18, `identity_key`) with
     `raw_members` taken from the Lattes CV only — which lists just the
     coordinator and one researcher ("Francisco de Assis Bold", a typo) and no
     students.
  3. `TeamSynchronizer.synchronize_members` is a full sync:
     `_remove_obsolete_members` deleted every (person, role) not in the Lattes
     list, dropping the SigPesq students (and leaving a typo person
     `Francisco de Assis Bold`) on the project team. The dedup feature was NOT
     involved: the merge transfers `team_members`/`advisorship_members` (unit
     tested) and no orphaned rows referencing merged person 1209 exist.
  **Fix applied**: removal in `TeamSynchronizer` is now scoped to the roles the
  source actually provides (a Lattes sync claiming only coordinator/researcher
  roles no longer removes `Student` members from SigPesq; an empty member list
  removes nothing). Tests covering the invariant were added to
  `tests/test_team_synchronizer.py`. Note: a re-run of the weekly pipeline is
  required to restore Israel's BPM/Air Writing project memberships. Status: Fixed
  (needs re-run).