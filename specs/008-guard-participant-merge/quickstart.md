# Quickstart: validate the deduplication guards

**Feature**: 008-guard-participant-merge | **Date**: 2026-08-28

This runbook proves the two pillars of the feature: (1) the participant
deduplication guards are load-bearing and (2) the prior initiative-level guard
still holds. It follows the discipline established by the previous version of
this feature — a regression test that has never been seen failing proves
nothing.

## 1. Run the feature tests

```bash
.venv/bin/python -m pytest tests/test_person_identity.py tests/test_person_consolidator.py tests/test_project_loader_matching.py -v
```

Expected: all pass in less than 5 seconds, with no database and no network.

## 2. The experiments that give the feature its meaning

Think of each guard this feature adds — the strong-identifier veto (R8), the
junk-name refusal (R13), the shared key function (R7) — plus the initiative
guard that stays (R1). Break one and the suite must scream.

### 2a. Break the strong-identifier veto

In `src/core/logic/person_consolidator.py`, disable the veto that refuses to
merge a normalized-name group whose members carry conflicting Lattes/CNPq URLs
or identification IDs.

```bash
.venv/bin/python -m pytest tests/test_person_consolidator.py -v
```

**Expected: fail.** If it passes, the guard is not tested and must be re-written
— exactly the state of the 283 tests that let the fused adviseships enter
production.

### 2b. Break the shared key function

In `src/core/logic/person_identity.py`, stop canonicalizing particles (or stop
stripping diacritics), so "Israel Magalhães do Carmo" and "ISRAEL MAGALHÃES DO
CARMO" no longer produce the same key.

```bash
.venv/bin/python -m pytest tests/test_person_identity.py tests/test_person_consolidator.py -v
```

**Expected: fail** on the spelling-table and Scenario B tests.

### 2c. Break the initiative guard (prior art)

In `src/core/logic/project_loader.py`, inside `_resolve_existing_initiative`,
comment out the guard that stops advisories matching by normalized name:

```python
        # if model_class is Advisorship:
        #     return None
```

```bash
.venv/bin/python -m pytest tests/test_project_loader_matching.py -v
```

**Expected: fail.** Restore the guard and confirm there is no diff:

```bash
git diff src/core/logic/project_loader.py
```

## 3. Full suite, to prove nothing else changed

```bash
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration
```

Expected: the same result as before the feature — 277 passing and the 6
pre-existing failures (Chrome/chromedriver, canonical export, loader mapping,
SigPesq adapter), none related to this change (spec SC-006).

## 4. Reproduce the real defect and the fix

The observed defect: the 2026-08-28 export (`researchers_canonical.json`, 9,738
records) lists the student "Israel Magalhães do Carmo" twice — one record with
five initiatives, one with only a research-group membership — and the whole
file holds 176 such duplicate groups.

- **Before the fix**: run the weekly pipeline against `db/horizon.db` and count
  duplicate groups in the export; expect 176.
- **After the fix**: the same run exports exactly one record per person, with
  the union of both records' links. Aggregate link counts in the entire export
  must be unchanged (nothing discarded, spec SC-002); refused homonym groups
  appear in `data/reports/dedup_report.json` with their reasons.

```bash
.venv/bin/python - <<'EOF'
import json
from collections import Counter
from src.core.logic.person_identity import normalize_participant_name

rows = json.load(open("data/exports/researchers_canonical.json"))
groups = Counter(normalize_participant_name(r["name"]) for r in rows)
print("duplicate groups:", sum(1 for k, c in groups.items() if c > 1))
EOF
```

Expected after the fix: `duplicate groups: 0`.

## 5. Why this exists

In a full 75-minute run, the rule without the guard produced:

- 100 fused advisories
- 200 destroyed participant links, one advisor per fusion

No test failed. The defect only surfaced by comparing `advisorship_members`
counts before and after. The participant-level deduplication of this feature is
the same trap visited a second time — this time on participants and their
complementary data — and the experiments above are what keep every one of its
guards honest.