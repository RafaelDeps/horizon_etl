"""Assigns a permanent ``horizon_id`` to every entity of the database (spec 020).

Runs after ``consolidate_duplicates``, on the final state of the database. The
ids come only from source data through the pure rules of
``horizon_identity``, so two rebuilds from the same inputs give the same ids
whatever the order rows were inserted in.
"""

import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger
from rapidfuzz import fuzz as rapid_fuzz
from rapidfuzz import process as rapid_process

from src.core.logic.atomic_io import atomic_write_json
from src.core.logic.horizon_identity import (
    FUZZY_MATCH_THRESHOLD,
    HORIZON_RULE_VERSION,
    REFERENCE_PREFIX,
    IdDecision,
    article_decision,
    child_decision,
    fellowship_decision,
    id_priority,
    initiative_decision,
    person_decision,
    reference_decision,
    research_group_decision,
    research_production_decision,
    resolve_collisions,
    team_decision,
)
from src.core.ports.horizon_id_store import IHorizonIdStore

# The canonical_entity_type each entity type is matched under in
# entity_matches (persons are matched as researchers).
_MATCH_TYPE = {
    "person": "researcher",
    "research_group": "research_group",
    "initiative": "initiative",
    "advisorship": "advisorship",
    "article": "article",
    "research_production": "research_production",
}


# Alias reasons (data-model.md, horizon_id_aliases.reason).
MERGE = "merge"
UPGRADED_KEY = "upgraded key"
REBUILD = "rebuild"
KEY_CORRECTED = "key corrected"
RETIRED = "retired"


def _apply_merges(layer: List[IdDecision], merges: List[dict]) -> int:
    """FR-010: a merged entity keeps the highest-priority id among its own and
    its losers' (ties alphabetical), whichever row survived. The merge log is
    kept, so the choice is the same on every later run. Returns how many
    entities changed id."""
    by_entity = {(d.entity_type, d.entity_id): d for d in layer}
    used = {d.horizon_id for d in layer}
    changed = 0
    for merge in merges:
        d = by_entity.get((merge["entity_type"], merge["winner_entity_id"]))
        if d is None:
            continue
        pool = [c for c in merge["loser_candidate_ids"] if c not in used]
        best = min(pool + [d.horizon_id], key=id_priority)
        if best == d.horizon_id:
            continue
        used.discard(d.horizon_id)
        used.add(best)
        # The survivor's own id stops being current because of the merge.
        merge.setdefault("displaced", []).append(d.horizon_id)
        d.candidates = list(dict.fromkeys([best] + d.candidates))
        d.horizon_id, d.rule, d.natural_key = best, "merge", None
        changed += 1
    return changed


class HorizonIdAssigner:
    def __init__(self, store: IHorizonIdStore):
        self.store = store

    def _keys(self, source_keys, entity_type: str, entity_id) -> list:
        keys = list(source_keys.get((_MATCH_TYPE.get(entity_type), entity_id), []))
        if entity_type in ("initiative", "advisorship"):
            # Advisorships are initiatives too; a row can be matched under
            # either type depending on the loader.
            other = "initiative" if entity_type == "advisorship" else "advisorship"
            keys += source_keys.get((other, entity_id), [])
        return keys

    def derive(self, merges: Optional[List[dict]] = None) -> tuple:
        """All decisions, collisions resolved layer by layer, plus the report.
        ``merges`` (the merge log) are applied to each layer before the next
        one is built, so children follow their parent's id."""
        merges = merges or []
        merged_ids = 0
        store = self.store
        source_keys = store.source_keys()
        collisions: Dict[str, dict] = {}
        decisions: List[IdDecision] = []

        # 1. Reference records and fellowships.
        layer = []
        for entity_type in REFERENCE_PREFIX:
            layer += [
                reference_decision(entity_type, r)
                for r in store.iter_entities(entity_type)
            ]
        layer += [fellowship_decision(r) for r in store.iter_entities("fellowship")]
        collisions.update(resolve_collisions(layer))
        merged_ids += _apply_merges(layer, merges)
        decisions += layer

        # 2. Roots: persons, groups, initiatives, advisorships, productions.
        builders = {
            "person": person_decision,
            "research_group": research_group_decision,
            "article": article_decision,
            "research_production": research_production_decision,
        }
        layer = []
        for entity_type, build in builders.items():
            layer += [
                build(r, self._keys(source_keys, entity_type, r["id"]))
                for r in store.iter_entities(entity_type)
            ]
        for entity_type in ("initiative", "advisorship"):
            layer += [
                initiative_decision(
                    r, self._keys(source_keys, entity_type, r["id"]), entity_type
                )
                for r in store.iter_entities(entity_type)
            ]
        collisions.update(resolve_collisions(layer))
        merged_ids += _apply_merges(layer, merges)
        decisions += layer

        persons = {d.entity_id: d for d in layer if d.entity_type == "person"}
        initiatives = {
            d.entity_id: d
            for d in layer
            if d.entity_type in ("initiative", "advisorship")
        }

        # 3. Children of persons, and teams named after their initiatives.
        layer = []
        for entity_type in (
            "academic_education",
            "professional_activity",
            "award",
            "proficiency",
        ):
            layer += [
                child_decision(entity_type, r, persons.get(r.get("parent_id")))
                for r in store.iter_entities(entity_type)
            ]
        team_inits = store.team_initiatives()
        layer += [
            team_decision(
                r,
                [
                    initiatives[i]
                    for i in team_inits.get(r["id"], [])
                    if i in initiatives
                ],
            )
            for r in store.iter_entities("team")
        ]
        collisions.update(resolve_collisions(layer))
        merged_ids += _apply_merges(layer, merges)
        decisions += layer

        counts: Dict[str, Dict[str, int]] = {}
        for d in decisions:
            per_type = counts.setdefault(d.entity_type, {})
            per_type[d.rule] = per_type.get(d.rule, 0) + 1
        report = {
            "rule_version": HORIZON_RULE_VERSION,
            "entities": len(decisions),
            "counts": counts,
            "collisions": collisions,
            "collision_groups": sum(c["groups"] for c in collisions.values()),
            "ids_kept_from_merges": merged_ids,
        }
        return decisions, report

    def reconcile(self, decisions: List[IdDecision], history: dict) -> tuple:
        """Resolves every previously assigned id that is no longer current
        (research R5): merge log, candidate ids (upgraded key, or rebuild when
        the history came from a reset), same natural key under new rules
        (rebuild), parent prefix of a child, key corrected (R8); the rest is
        retired. Aliases already in the history keep their reason and are
        re-pointed to the current id. Returns the alias rows and their
        summary."""
        current = {d.horizon_id for d in decisions}
        by_entity = {(d.entity_type, d.entity_id): d.horizon_id for d in decisions}

        owners: Dict[str, set] = defaultdict(set)
        naturals: Dict[tuple, set] = defaultdict(set)
        for d in decisions:
            for c in d.candidates:
                owners[c].add(d.horizon_id)
            if d.natural_key:
                naturals[(d.entity_type, d.natural_key)].add(d.horizon_id)
        # Only unambiguous lookups: a homonym's name candidate is shared.
        by_candidate = {c: next(iter(o)) for c, o in owners.items() if len(o) == 1}
        by_natural = {k: next(iter(v)) for k, v in naturals.items() if len(v) == 1}

        merged: Dict[str, str] = {}
        for merge in history.get("merges", []):
            winner = by_entity.get((merge["entity_type"], merge["winner_entity_id"]))
            losers = merge["loser_candidate_ids"] + merge.get("displaced", [])
            for c in losers if winner else []:
                merged.setdefault(c, winner)
        snapshot_merged: Dict[str, str] = {}
        for merge in history.get("snapshot_merges", []):
            for c in merge.get("loser_candidate_ids", []):
                snapshot_merged.setdefault(c, merge.get("winner_horizon_id"))

        old_ids = {
            row["horizon_id"]: row
            for row in history.get("ids", [])
            if row["horizon_id"] not in current
        }
        old_aliases = {a["alias_horizon_id"]: a for a in history.get("aliases", [])}
        resolved: Dict[str, tuple] = {}

        def target_of(horizon_id):
            if horizon_id in current:
                return horizon_id
            return resolved.get(horizon_id, (None,))[0]

        def direct(horizon_id, row):
            if horizon_id in merged:
                return merged[horizon_id], MERGE
            if horizon_id in by_candidate:
                origin = (row or {}).get("origin", "database")
                return (
                    by_candidate[horizon_id],
                    UPGRADED_KEY if origin == "database" else REBUILD,
                )
            natural = (row or {}).get("natural_key")
            key = ((row or {}).get("entity_type"), natural)
            if natural and key in by_natural:
                return by_natural[key], REBUILD
            return None

        def by_parent(horizon_id):
            if "/" not in horizon_id:
                return None
            parent, tail = horizon_id.split("/", 1)
            target = target_of(parent)
            if target and f"{target}/{tail}" in current:
                reason = resolved.get(parent, (None, UPGRADED_KEY))[1]
                return f"{target}/{tail}", reason
            return None

        # 1. Ids that were current: direct lookups, then the parent prefix
        # (children of a merged or upgraded parent), then the snapshot merges.
        for horizon_id in sorted(old_ids):
            found = direct(horizon_id, old_ids[horizon_id])
            if found:
                resolved[horizon_id] = found
        for horizon_id in sorted(set(old_ids) - set(resolved)):
            found = by_parent(horizon_id)
            if not found and horizon_id in snapshot_merged:
                target = target_of(snapshot_merged[horizon_id])
                found = (target, MERGE) if target else None
            if found:
                resolved[horizon_id] = found

        # 2. Key corrected: one new id of the same type, rule and parent with
        # a similar natural key (research R8).
        known = set(old_ids) | {row["horizon_id"] for row in history.get("ids", [])}
        fresh: Dict[tuple, List[IdDecision]] = defaultdict(list)
        for d in decisions:
            if d.horizon_id not in known and d.natural_key:
                fresh[(d.entity_type, d.rule, d.parent_horizon_id)].append(d)
        key_corrected = {"none": 0, "ambiguous": 0}
        for horizon_id in sorted(set(old_ids) - set(resolved)):
            row = old_ids[horizon_id]
            if not row.get("natural_key"):
                continue
            parent = row.get("parent_horizon_id")
            choices = fresh.get(
                (row["entity_type"], row.get("rule"), target_of(parent) or parent),
                [],
            )
            found = rapid_process.extract(
                row["natural_key"],
                [d.natural_key for d in choices],
                scorer=rapid_fuzz.token_sort_ratio,
                score_cutoff=FUZZY_MATCH_THRESHOLD - 0.5,
                limit=None,
            )
            if len(found) == 1:
                resolved[horizon_id] = (choices[found[0][2]].horizon_id, KEY_CORRECTED)
            else:
                key_corrected["none" if not found else "ambiguous"] += 1

        # 3. Aliases of the history: same reason, re-pointed; a retired one
        # may resolve now.
        aliases = []
        for alias_id in sorted(old_aliases):
            if alias_id in current:
                continue  # the same source data is back: current again
            alias = old_aliases[alias_id]
            target = (
                target_of(alias.get("horizon_id")) if alias.get("horizon_id") else None
            )
            reason = alias.get("reason")
            if not target:
                found = direct(alias_id, None) or by_parent(alias_id)
                target, reason = found if found else (None, RETIRED)
            aliases.append(
                {
                    "alias_horizon_id": alias_id,
                    "horizon_id": target,
                    "reason": reason if target else RETIRED,
                    "created_at": alias.get("created_at"),
                }
            )
        for horizon_id in sorted(set(old_ids) - set(old_aliases)):
            target, reason = resolved.get(horizon_id, (None, RETIRED))
            aliases.append(
                {
                    "alias_horizon_id": horizon_id,
                    "horizon_id": target,
                    "reason": reason,
                    "created_at": None,
                }
            )

        per_reason: Dict[str, int] = {}
        for alias in aliases:
            per_reason[alias["reason"]] = per_reason.get(alias["reason"], 0) + 1
        summary = {
            "history_source": history.get("source", []),
            "total": len(aliases),
            "new": sum(1 for a in aliases if a["alias_horizon_id"] not in old_aliases),
            "per_reason": per_reason,
            "retired": per_reason.get(RETIRED, 0),
            "newly_retired": sum(
                1 for h in old_ids if h not in resolved and h not in old_aliases
            ),
            "key_corrected_without_match": key_corrected["none"],
            "key_corrected_ambiguous": key_corrected["ambiguous"],
        }
        return aliases, summary

    def assign(self) -> dict:
        # The history is read before the current ids are replaced.
        history = self.store.load_history()
        decisions, report = self.derive(history.get("merges"))
        aliases, report["aliases"] = self.reconcile(decisions, history)
        candidates = [(d.horizon_id, c) for d in decisions for c in d.candidates]
        self.store.replace_current([d.as_row() for d in decisions], candidates)
        self.store.upsert_aliases(aliases, {d.horizon_id for d in decisions})
        self.store.mark_merges_consumed(
            [m["id"] for m in history.get("merges", []) if not m.get("consumed_at")]
        )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.store.set_meta("rule_version", str(HORIZON_RULE_VERSION))
        self.store.set_meta("last_assigned_at", now)
        report["assigned_at"] = now
        logger.info(
            "Horizon ids: {} entities, {} collision groups, rule version {}; "
            "aliases {} ({} new, {} retired, per reason {}), history from {}",
            report["entities"],
            report["collision_groups"],
            HORIZON_RULE_VERSION,
            report["aliases"]["total"],
            report["aliases"]["new"],
            report["aliases"]["retired"],
            report["aliases"]["per_reason"],
            report["aliases"]["history_source"] or "nothing",
        )
        return report


ID_FILE = "horizon_ids_canonical.json"


def write_id_file(store: IHorizonIdStore, output_dir: str) -> Optional[str]:
    """Writes ``horizon_ids_canonical.json`` (contracts/export-files.md).

    Rows are sorted by entity type and id, so two exports of the same data are
    identical apart from ``generated_at``. Writes nothing (and returns None)
    when no id was assigned, so the export never fails because of it.
    """
    rows = store.current_ids()
    if not rows:
        logger.warning("No horizon ids to export; {} not written", ID_FILE)
        return None
    rows.sort(key=lambda r: (r["entity_type"], r["horizon_id"]))
    payload = {
        "rule_version": int(store.get_meta("rule_version") or HORIZON_RULE_VERSION),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ids": [
            {
                "entity_type": r["entity_type"],
                "id": r["entity_id"],
                "horizon_id": r["horizon_id"],
                "rule": r["rule"],
                "natural_key": r["natural_key"],
                "parent_horizon_id": r["parent_horizon_id"],
            }
            for r in rows
        ],
    }
    path = os.path.join(output_dir, ID_FILE)
    atomic_write_json(path, payload, indent=2)
    logger.info("Exported {} horizon ids to {}", len(rows), path)
    return path


ALIAS_FILE = "horizon_id_aliases_canonical.json"


def write_alias_file(store: IHorizonIdStore, output_dir: str) -> Optional[str]:
    """Writes ``horizon_id_aliases_canonical.json`` (contracts/export-files.md),
    sorted by ``alias_horizon_id``. Written, even empty, whenever ids were
    assigned, so consumers always find it next to the id file."""
    if store.get_meta("rule_version") is None:
        logger.warning("No horizon ids assigned; {} not written", ALIAS_FILE)
        return None
    rows = sorted(store.current_aliases(), key=lambda r: r["alias_horizon_id"])
    payload = {
        "rule_version": int(store.get_meta("rule_version")),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aliases": [
            {
                "alias_horizon_id": r["alias_horizon_id"],
                "horizon_id": r["horizon_id"],
                "reason": r["reason"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }
    path = os.path.join(output_dir, ALIAS_FILE)
    atomic_write_json(path, payload, indent=2)
    logger.info("Exported {} horizon id aliases to {}", len(rows), path)
    return path
