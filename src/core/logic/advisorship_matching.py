"""Spec 035: when an advisorship item is an advisorship already stored.

Two advisorships cannot share a name, so the advisorships of one title are the
row named as the title and the rows named ``<title> | Orientacao ...``. An
item belongs to one of them only when the student is the same and their years
do not differ; otherwise it is a new advisorship. Pure functions: no database.
"""

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple

SUFFIX_MARK = " | Orientacao"

Years = Optional[Tuple[int, int]]

_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")


@dataclass(frozen=True)
class StoredAdvisorship:
    """One stored advisorship as the rule sees it. ``student_name`` is
    normalized (case and accents removed); empty when there is no student."""

    id: Any
    name: str
    student_id: Optional[int]
    student_name: str
    years: Years


def base_title(name: Any) -> str:
    """The title an advisorship name was built from: the text before the last
    ``| Orientacao`` marker, or the name itself."""
    text = str(name or "")
    head, mark, _ = text.rpartition(SUFFIX_MARK)
    return head if mark else text


def _year(value: Any) -> Optional[int]:
    if value is None:
        return None
    year = getattr(value, "year", None)
    if isinstance(year, int):
        return year
    if isinstance(value, int):
        return value
    found = _YEAR.search(str(value))
    return int(found.group(1)) if found else None


def year_range(start: Any, end: Any) -> Years:
    """The years an item or an advisorship covers, from its start to its end
    (one year when it has only one); None when it has neither."""
    first, last = _year(start), _year(end)
    if first is None and last is None:
        return None
    if first is None:
        first = last
    if last is None:
        last = first
    return (min(first, last), max(first, last))


def years_differ(a: Years, b: Years) -> bool:
    """True only when both ranges exist and share no year."""
    if a is None or b is None:
        return False
    return a[1] < b[0] or b[1] < a[0]


def widen(a: Years, b: Years) -> Years:
    """The range that covers both; the other one when either is missing."""
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), max(a[1], b[1]))


def same_student(
    item_id: Optional[int],
    item_name: str,
    stored_id: Optional[int],
    stored_name: str,
) -> bool:
    """The same person, or the same (normalized, non-empty) name."""
    if item_id is not None and stored_id is not None and item_id == stored_id:
        return True
    return bool(item_name) and item_name == stored_name


def _is_bare(candidate: StoredAdvisorship) -> bool:
    return SUFFIX_MARK not in (candidate.name or "")


def pick_match(
    item_student_id: Optional[int],
    item_student_name: str,
    item_years: Years,
    candidates: Iterable[StoredAdvisorship],
) -> Optional[StoredAdvisorship]:
    """The stored advisorship of the item's title that is this item's, or None
    (the item is then a new advisorship)."""
    candidates = list(candidates)
    has_student = item_student_id is not None or bool(item_student_name)

    if not has_student:
        bare = [c for c in candidates if _is_bare(c)]
        return min(bare, key=lambda c: c.id) if bare else None

    def order(candidate: StoredAdvisorship):
        known = candidate.years is not None and item_years is not None
        first = candidate.years[0] if candidate.years else float("inf")
        return (0 if known else 1, first, 0 if _is_bare(candidate) else 1, candidate.id)

    same = [
        c
        for c in candidates
        if same_student(
            item_student_id, item_student_name, c.student_id, c.student_name
        )
        and not years_differ(item_years, c.years)
    ]
    if same:
        return min(same, key=order)

    empty = [c for c in candidates if c.student_id is None and not c.student_name]
    if empty:
        return min(empty, key=lambda c: (0 if _is_bare(c) else 1, c.id))
    return None
