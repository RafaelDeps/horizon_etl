"""Rules of a Lattes professional activity (spec 034).

Two defects came from the way activities reached the database. The curriculum
data arrives with the institution text cut at every comma, so a name with
commas gave a wrong name, acronym and country; and an activity was taken for a
repeat whenever the institution and the start year were the same. The rules
here depend only on the curriculum item, never on the database or on the order
curricula are processed in
(specs/034-keep-professional-activities/contracts/activity-rules.md).
"""

from typing import Any, List, Optional, Tuple

from src.core.logic.horizon_identity import normalize_text

# The fields the database keeps for an activity. Two activities of one
# researcher are the same only when all of them are equal (FR-001).
STORED_FIELDS = (
    "institution",
    "institution_name",
    "institution_acronym",
    "institution_country",
    "period",
    "start_year",
    "end_year",
    "bond",
    "classification",
    "work_regime",
    "role_function",
    "activity_type",
    "current",
)

# An item with none of these says nothing beyond the institution (FR-002a).
DETAIL_FIELDS = (
    "period",
    "start_year",
    "end_year",
    "bond",
    "classification",
    "work_regime",
    "role_function",
)

# Column limits of the domain entity.
_INSTITUTION_LIMIT = 500
_NAME_LIMIT = 255
_ACRONYM_LIMIT = 100
_COUNTRY_LIMIT = 100

# Country names as Lattes writes them, found in the "name, acronym, country"
# texts of the curricula. Only a two-part text needs the list: there the last
# part is either a country or a piece of the name.
_KNOWN_COUNTRIES = frozenset(
    normalize_text(name)
    for name in (
        "Brasil",
        "Estados Unidos",
        "Portugal",
        "França",
        "Peru",
        "Alemanha",
        "Espanha",
        "Argentina",
        "Grã-Bretanha",
        "Colômbia",
        "Canadá",
        "África do Sul",
        "Inglaterra",
        "Holanda",
        "Japão",
        "Itália",
        "Índia",
        "Suíça",
        "Escócia",
        "Noruega",
        "Barein",
        "Paraguai",
    )
)


def _has_lowercase(text: str) -> bool:
    return any(ch.islower() for ch in text)


def _cut(text: Optional[str], limit: int) -> Optional[str]:
    return text[:limit] if text else None


def split_institution(
    text: Any,
) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """``(institution, name, acronym, country)`` read from the full institution
    text, from the end: Lattes writes "name, acronym, country" and the name may
    have commas of its own. Countries are never written in capitals, so a last
    part without a lowercase letter is an acronym. A field the text does not
    carry is None; no part is returned in two fields (FR-003 to FR-005)."""
    institution = str(text or "").strip().rstrip(". ").strip()
    if not institution:
        return "", None, None, None
    parts = [part.strip() for part in institution.split(",") if part.strip()]
    name, acronym, country = institution, None, None
    if len(parts) >= 2:
        last = parts[-1]
        if not _has_lowercase(last):
            name, acronym = institution.rsplit(",", 1)[0], last
        elif len(parts) >= 3:
            name = institution.rsplit(",", 2)[0]
            acronym, country = parts[-2], last
        elif normalize_text(last) in _KNOWN_COUNTRIES:
            name, country = institution.rsplit(",", 1)[0], last
    return (
        institution[:_INSTITUTION_LIMIT],
        _cut(name.strip(), _NAME_LIMIT),
        _cut(acronym, _ACRONYM_LIMIT),
        _cut(country, _COUNTRY_LIMIT),
    )


def activity_key(activity: Any) -> tuple:
    """The stored fields of an activity, from a parsed item (a mapping) or a
    database row (an object). Two activities are the same one only when their
    keys are equal."""
    if isinstance(activity, dict):
        values = [activity.get(name) for name in STORED_FIELDS]
    else:
        values = [getattr(activity, name, None) for name in STORED_FIELDS]
    values[-1] = bool(values[-1])  # current: 0/1/None in a database row
    return tuple(values)


def _is_institution_only(activity: dict) -> bool:
    return all(activity.get(name) is None for name in DETAIL_FIELDS)


def distinct_activities(items: List[dict]) -> List[dict]:
    """The activities of one curriculum to store, in their first order of
    appearance: exact repeats once, and an item that carries only the
    institution only when the curriculum has no filled activity there."""
    kept, seen = [], set()
    for item in items:
        key = activity_key(item)
        if key not in seen:
            seen.add(key)
            kept.append(item)
    filled = {
        item.get("institution") for item in kept if not _is_institution_only(item)
    }
    return [
        item
        for item in kept
        if not (_is_institution_only(item) and item.get("institution") in filled)
    ]
