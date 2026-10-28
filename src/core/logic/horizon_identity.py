"""Permanent, readable entity ids (``horizon_id``) and idempotent tracking keys.

Spec 020. Everything here is a pure function of source data: no I/O, no
database ids, no processing order. The same functions build the ``horizon_id``
in the ``assign_horizon_ids`` phase and the tracking keys at ingestion time, so
both agree, and two rebuilds from the same inputs give the same ids.

Id grammar and rules: ``specs/020-horizon-id-idempotent-hash/contracts/``.
"""

import hashlib
import json
import math
import os
import re
from typing import Any, Optional

from src.core.logic.initiative_identity import normalize_text

# Bump on any change to a key, hash or id rule (FR-024): a database recorded
# with another version is rebuilt, and the history turns old ids into aliases.
HORIZON_RULE_VERSION = 1

# Similarity (rapidfuzz token_sort_ratio, 0-100) at which two names or titles
# are the same thing: PersonMatcher's fuzzy threshold, and the "key corrected"
# relink of old ids (FR-013b) uses the same value.
FUZZY_MATCH_THRESHOLD = 90

_EMPTY_TEXT = {"", "nan", "NaN", "None"}

_LATTES_URL = re.compile(r"lattes\.cnpq\.br/(\d{16})")
_CNPQ_GROUP_URL = re.compile(r"espelhogrupo/(\w+)")
_LATTES_CV_FILE = re.compile(r"(\d{16})\.json$")
_DOI_PREFIX = re.compile(r"^(https?://)?(dx\.)?doi\.org/")


def canonical(value: Any) -> Any:
    """Type-stable form of a payload, so the same information hashes the same.

    Empty values (None, NaN, "nan", "") become None; an integral float becomes
    an int; every other scalar becomes its trimmed text. ``600``, ``600.0`` and
    ``"600"`` are therefore equal. Applied recursively to dicts and lists.
    """
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        # Sets have no order: sort their canonical items so the hash is stable.
        return sorted(
            (canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True)
        )
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            value = int(value)
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    text = str(value).strip()
    return None if text in _EMPTY_TEXT else text


def canonical_hash(payload: Any) -> str:
    """SHA-256 of the JSON of the canonical form, keys sorted."""
    encoded = json.dumps(canonical(payload), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def hash12(*parts: Any) -> str:
    """First 12 hex characters of the SHA-256 of the normalized parts."""
    joined = "|".join(normalize_text(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def slug(text: Any) -> str:
    """Readable form of a name: normalized, spaces replaced by hyphens."""
    return normalize_text(text).replace(" ", "-")


def normalize_doi(doi: Any) -> Optional[str]:
    """Lowercased DOI without the doi.org / dx.doi.org URL prefix, or None."""
    if doi is None:
        return None
    text = _DOI_PREFIX.sub("", str(doi).strip().lower()).strip()
    return text or None


def lattes_id_from_url(url: Any) -> Optional[str]:
    """The 16-digit Lattes id of a ``lattes.cnpq.br/<id>`` URL, or None."""
    match = _LATTES_URL.search(str(url or ""))
    return match.group(1) if match else None


def cnpq_group_id_from_url(url: Any) -> Optional[str]:
    """The CNPq group id of an ``espelhogrupo/<id>`` mirror URL, or None."""
    match = _CNPQ_GROUP_URL.search(str(url or ""))
    return match.group(1) if match else None


def lattes_id_from_cv_path(path: Any) -> Optional[str]:
    """The Lattes id at the end of a CV file name (``..._<id>.json``), or None."""
    match = _LATTES_CV_FILE.search(str(path or ""))
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# horizon_id rules (contracts/horizon-id-format.md, research R2)
# --------------------------------------------------------------------------

REFERENCE_PREFIX = {
    "knowledge_area": "knowledge-area",
    "organization": "organization",
    "campus": "campus",
    "initiative_type": "initiative-type",
    "production_type": "production-type",
    "role": "role",
    "language": "language",
    "education_type": "education-type",
}


class IdDecision:
    """The id chosen for one entity, plus every id it could be known by."""

    __slots__ = (
        "entity_type",
        "entity_id",
        "horizon_id",
        "rule",
        "natural_key",
        "parent_horizon_id",
        "candidates",
        "origin_document",
        "content_hash",
        "collision_suffix",
    )

    def __init__(
        self,
        entity_type: str,
        entity_id: Any,
        horizon_id: str,
        rule: str,
        natural_key: Optional[str] = None,
        parent_horizon_id: Optional[str] = None,
        candidates: Optional[list] = None,
        origin_document: str = "",
        content_hash: str = "",
    ):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.horizon_id = horizon_id
        self.rule = rule
        self.natural_key = natural_key
        self.parent_horizon_id = parent_horizon_id
        # The winner first, then lower-priority ids, without duplicates.
        ordered = [horizon_id] + [c for c in (candidates or []) if c != horizon_id]
        self.candidates = list(dict.fromkeys(ordered))
        self.origin_document = origin_document or ""
        self.content_hash = content_hash
        self.collision_suffix: Optional[str] = None

    def as_row(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "horizon_id": self.horizon_id,
            "rule": self.rule,
            "natural_key": self.natural_key,
            "parent_horizon_id": self.parent_horizon_id,
            "collision_suffix": self.collision_suffix,
        }


def _content_hash(row: dict) -> str:
    """Hash of a row's source content: every column except database ids."""
    return canonical_hash(
        {k: v for k, v in row.items() if k != "id" and not k.endswith("_id")}
    )


def _origin(source_keys: Optional[list]) -> str:
    """The first source document of an entity, by file name only: the stored
    path is absolute and depends on the checkout (local, GitHub Actions)."""
    files = sorted(
        os.path.basename(k.get("source_file") or "") for k in source_keys or []
    )
    return files[0] if files else ""


def _identity_part(source_record_id: str) -> str:
    """Strips the ``lattes:<cv>|`` document prefix of a tracking key, so the
    same project in several CVs gives the same id."""
    if source_record_id.startswith("lattes:") and "|" in source_record_id:
        return source_record_id.split("|", 1)[1]
    return source_record_id


def _name_key(*parts: Any) -> str:
    return "|".join(normalize_text(p) for p in parts)


def person_decision(row: dict, source_keys: Optional[list] = None) -> IdDecision:
    lattes = lattes_id_from_url(row.get("cnpq_url"))
    if not lattes:
        for key in source_keys or []:
            rid = key.get("source_record_id") or ""
            if key.get("source_entity_type") == "researcher_profile" and re.fullmatch(
                r"\d{16}", rid
            ):
                lattes = rid
                break
    name_key = _name_key(row.get("name"))
    by_name = f"person:h:{hash12(row.get('name'))}"
    if lattes:
        winner, rule, natural = f"person:lattes:{lattes}", "lattes_id", None
    else:
        winner, rule, natural = by_name, "name", name_key
    return IdDecision(
        "person",
        row["id"],
        winner,
        rule,
        natural,
        candidates=[by_name],
        origin_document=_origin(source_keys),
        content_hash=_content_hash({"name": row.get("name")}),
    )


def research_group_decision(
    row: dict, source_keys: Optional[list] = None
) -> IdDecision:
    cnpq = cnpq_group_id_from_url(row.get("cnpq_url"))
    by_name = f"group:sigpesq:h:{hash12(row.get('name'))}"
    if cnpq:
        winner, rule, natural = f"group:cnpq:{cnpq}", "cnpq_id", None
    else:
        winner, rule, natural = by_name, "sigpesq_name", _name_key(row.get("name"))
    return IdDecision(
        "research_group",
        row["id"],
        winner,
        rule,
        natural,
        candidates=[by_name],
        origin_document=_origin(source_keys),
        content_hash=_content_hash(row),
    )


def initiative_decision(
    row: dict, source_keys: Optional[list] = None, entity_type: str = "initiative"
) -> IdDecision:
    """Initiatives and advisorships. Every source key gives a candidate; the
    highest-priority one wins: SigPesq workplan, SigPesq project code, PJ code,
    Lattes/SigPesq identity key, then type + name."""
    found = []  # (priority, id, rule, natural_key)
    for key in source_keys or []:
        rid = _identity_part(key.get("source_record_id") or "")
        if rid.startswith("sigpesq workplan|"):
            code = rid.split("|", 1)[1].replace("|", "-")
            found.append(
                (0, f"advisorship:sigpesq-pt:{code}", "sigpesq_workplan", None)
            )
        elif rid.startswith("sigpesq project|"):
            code = rid.split("|", 1)[1]
            found.append(
                (1, f"{entity_type}:sigpesq-pj:{code}", "sigpesq_project_code", None)
            )
        elif rid.startswith("PJ "):
            found.append((2, f"{entity_type}:sigpesq-pj:{rid[3:]}", "pj_code", None))
        elif rid.startswith(("lattes project|", "lattes advisorship|")):
            found.append(
                (3, f"{entity_type}:lattes:h:{hash12(rid)}", "lattes_identity", rid)
            )
        # A SigPesq advisorship without a workplan code has an identity key
        # built from advisor and student e-mails: never hash it into an id
        # (FR-007). Such rows fall back to type + name.
    fallback_key = _name_key(row.get("type_name"), row.get("name"))
    found.append(
        (
            4,
            f"{entity_type}:h:{hash12(row.get('type_name'), row.get('name'))}",
            "name",
            fallback_key,
        )
    )
    found.sort(key=lambda item: (item[0], item[1]))
    _, winner, rule, natural = found[0]
    return IdDecision(
        entity_type,
        row["id"],
        winner,
        rule,
        natural,
        candidates=[item[1] for item in found],
        origin_document=_origin(source_keys),
        content_hash=_content_hash(
            {"name": row.get("name"), "type": row.get("type_name")}
        ),
    )


def article_decision(row: dict, source_keys: Optional[list] = None) -> IdDecision:
    parts = (
        row.get("title"),
        row.get("year"),
        row.get("type"),
        row.get("journal_conference"),
    )
    by_content = f"article:h:{hash12(*parts)}"
    doi = normalize_doi(row.get("doi"))
    if doi:
        winner, rule, natural = f"article:doi:{doi}", "doi", None
    else:
        winner, rule, natural = by_content, "title_year_type_venue", _name_key(*parts)
    return IdDecision(
        "article",
        row["id"],
        winner,
        rule,
        natural,
        candidates=[by_content],
        origin_document=_origin(source_keys),
        content_hash=_content_hash(row),
    )


def research_production_decision(
    row: dict, source_keys: Optional[list] = None
) -> IdDecision:
    parts = (row.get("title"), row.get("year"), row.get("type_name"))
    return IdDecision(
        "research_production",
        row["id"],
        f"production:h:{hash12(*parts)}",
        "title_year_type",
        _name_key(*parts),
        origin_document=_origin(source_keys),
        content_hash=_content_hash(row),
    )


_CHILD_PARTS = {
    "academic_education": ("education", ("type_name", "title", "start_year")),
    "professional_activity": (
        "activity",
        ("institution_name", "start_year", "end_year", "role_function", "bond"),
    ),
    "award": ("award", ("title", "year")),
}


def child_decision(
    entity_type: str, row: dict, parent: Optional[IdDecision]
) -> IdDecision:
    """Children of a person: the parent's id, the kind, and a hash of the
    fields that distinguish the item (a slug for proficiencies). Candidates are
    built from every parent candidate, so a parent upgrade carries its
    children's old ids along."""
    parents = parent.candidates if parent else ["person:unknown"]
    if entity_type == "proficiency":
        tail, natural = f"proficiency:{slug(row.get('language'))}", None
        rule = "parent+language"
    else:
        kind, fields = _CHILD_PARTS[entity_type]
        parts = tuple(row.get(f) for f in fields)
        tail, natural = f"{kind}:h:{hash12(*parts)}", _name_key(*parts)
        rule = "parent+" + "+".join(fields)
    return IdDecision(
        entity_type,
        row["id"],
        f"{parents[0]}/{tail}",
        rule,
        natural,
        parent_horizon_id=parents[0],
        candidates=[f"{p}/{tail}" for p in parents],
        content_hash=_content_hash(row),
    )


def team_decision(row: dict, initiatives: list) -> IdDecision:
    """A team that is not a research group is named after the initiative it
    staffs (the alphabetically first one when several share it)."""
    if initiatives:
        ordered = sorted(initiatives, key=lambda d: d.horizon_id)
        first = ordered[0]
        candidates = [f"{c}/team" for d in ordered for c in d.candidates]
        return IdDecision(
            "team",
            row["id"],
            f"{first.horizon_id}/team",
            "initiative",
            parent_horizon_id=first.horizon_id,
            candidates=candidates,
            content_hash=_content_hash(row),
        )
    return IdDecision(
        "team",
        row["id"],
        f"team:h:{hash12(row.get('name'))}",
        "name",
        _name_key(row.get("name")),
        content_hash=_content_hash(row),
    )


def fellowship_decision(row: dict) -> IdDecision:
    value = row.get("value")
    shown = "" if value is None else ("%g" % float(value))
    return IdDecision(
        "fellowship",
        row["id"],
        f"fellowship:{slug(row.get('name'))}:{shown}",
        "slug+value",
        content_hash=_content_hash(row),
    )


def reference_decision(entity_type: str, row: dict) -> IdDecision:
    return IdDecision(
        entity_type,
        row["id"],
        f"{REFERENCE_PREFIX[entity_type]}:{slug(row.get('name'))}",
        "slug",
        content_hash=_content_hash(row),
    )


def id_priority(horizon_id: str) -> tuple:
    """Sort key of the ids an entity may keep after a merge (FR-010): a source
    id before a hash of the content, then alphabetical."""
    return (":h:" in horizon_id, horizon_id)


def merge_candidates(entity_type: str, row: dict) -> list:
    """Every id the loser of a merge could be known by, computed from its row
    before it is deleted (research R7). ``row`` holds the columns the type's
    rule reads (a person: ``name`` and ``cnpq_url``)."""
    if entity_type == "person":
        return person_decision(row).candidates
    if entity_type == "team":
        return team_decision(row, []).candidates
    return reference_decision(entity_type, row).candidates


def resolve_collisions(decisions: list) -> dict:
    """Makes every horizon_id unique without depending on processing order
    (FR-008, research R4). Colliding ids first get ``~`` plus 6 hex of their
    source document of origin; rows that still collide get ``~2``, ``~3`` in
    the order of their content hash (the first keeps its id). Returns, per
    entity type, the number of collision groups and rows, with examples."""
    report: dict = {}

    def groups(items):
        by_id: dict = {}
        for d in items:
            by_id.setdefault(d.horizon_id, []).append(d)
        return [g for g in by_id.values() if len(g) > 1]

    for group in groups(decisions):
        entry = report.setdefault(
            group[0].entity_type, {"groups": 0, "rows": 0, "examples": []}
        )
        entry["groups"] += 1
        entry["rows"] += len(group)
        if len(entry["examples"]) < 3:
            entry["examples"].append(group[0].horizon_id)
        for d in group:
            d.collision_suffix = "~" + hash12(d.origin_document)[:6]
            d.horizon_id += d.collision_suffix
    for group in groups(decisions):
        group.sort(key=lambda d: d.content_hash)
        for n, d in enumerate(group[1:], start=2):
            d.collision_suffix = (d.collision_suffix or "") + f"~{n}"
            d.horizon_id += f"~{n}"
    for d in decisions:
        if d.collision_suffix:
            d.candidates = list(dict.fromkeys([d.horizon_id] + d.candidates))
    return report


# --------------------------------------------------------------------------
# Tracking keys (contracts/tracking-keys.md): source_record_id values built
# only from source-native fields, never from database ids.
# --------------------------------------------------------------------------


def join_normalized(*parts: Any) -> str:
    return "|".join(normalize_text(p) for p in parts)


def _cnpq(url: Any) -> str:
    group = cnpq_group_id_from_url(url)
    return f"cnpq:{group}" if group else f"cnpq-url:{str(url or '').strip()}"


def _cv(cv_path: Any) -> str:
    lattes = lattes_id_from_cv_path(cv_path)
    if lattes:
        return f"lattes:{lattes}"
    return f"lattes-file:{os.path.basename(str(cv_path or ''))}"


def cnpq_payload_key(url: Any) -> str:
    return _cnpq(url)


def cnpq_member_key(url: Any, member: dict) -> str:
    return "|".join(
        [
            _cnpq(url),
            join_normalized(
                member.get("name"),
                member.get("role"),
                member.get("data_inicio"),
                member.get("data_fim"),
            ),
        ]
    )


def cnpq_line_key(url: Any, line_name: Any) -> str:
    return f"{_cnpq(url)}|{normalize_text(line_name)}"


def lattes_education_key(cv_path: Any, edu: dict) -> str:
    return "|".join(
        [
            _cv(cv_path),
            join_normalized(
                edu.get("course_name"),
                edu.get("degree"),
                edu.get("start_year"),
                edu.get("end_year"),
                edu.get("institution") or edu.get("description"),
            ),
        ]
    )


def lattes_article_key(cv_path: Any, art: dict) -> str:
    doi = normalize_doi(art.get("doi"))
    work = doi or join_normalized(art.get("title"), art.get("year"))
    return "|".join(
        [
            _cv(cv_path),
            work,
            join_normalized(
                art.get("type"),
                art.get("journal_conference"),
                art.get("volume"),
                art.get("pages"),
            ),
        ]
    )


def lattes_initiative_key(cv_path: Any, identity_key: Any) -> str:
    return f"{_cv(cv_path)}|{identity_key}"


def lattes_advisorship_key(cv_path: Any, identity_key: Any, row: dict) -> str:
    return "|".join(
        [
            _cv(cv_path),
            str(identity_key),
            join_normalized(row.get("type"), row.get("institution")),
        ]
    )


def dedupe_same_document(items: list, key_fn) -> tuple:
    """Keeps, per key, the item with the smallest canonical hash (FR-020): an
    item recorded twice in the same document is processed once, always the
    same version. Returns (kept items in their original order, dropped count)."""
    best: dict = {}
    for index, item in enumerate(items):
        key = key_fn(item)
        digest = canonical_hash(item)
        if key not in best or digest < best[key][0]:
            best[key] = (digest, index)
    keep = {index for _, index in best.values()}
    kept = [item for index, item in enumerate(items) if index in keep]
    return kept, len(items) - len(kept)
