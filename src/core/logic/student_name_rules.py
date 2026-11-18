"""The name of the student of a Lattes advisorship item (branch 036).

The "orientando" field of a curriculum item should hold a name and sometimes
holds more: the title of the work after the name, an academic title, a link,
a footnote number, several people, or a text that is not a name at all. The
ETL used to store the text as the person's name.

``clean_student_name`` returns the name to store, or ``None`` when the text is
not a name, and the kinds of cleaning applied. It depends on the text alone,
so an incremental run and a rebuild agree. When the rule is unsure it leaves
the text as it is: a field with several people (``several``) and a full stop
after a one-word head (``uncut``) are returned as written.

Branch 041: a citation ("Name. Title of the work (orientador: …") is cut
before anything else, and a field with several students joined by "/" is
split when every part is a name of two words or more: ``names`` then holds
every student and ``name`` the first one (kind ``split``). Other fields with
several people are still returned as written (``several``).

Contract: specs/036-small-fixes-batch/contracts/small-fixes.md, section 1, and
specs/041-dashboard-visible-fixes/contracts/dashboard-fixes.md, section 3.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple

from src.core.logic.person_name_rules import START_TITLE as _START_TITLE
from src.core.logic.person_name_rules import head_before_work_title, is_name_fragment

# Whole-word academic titles (person_name_rules.START_TITLE). The full words
# are removed at the start only: at the end "Mestre" or "Doutor" may be a
# surname.
_END_TITLE = r"(?:prof[aª]?|dr[aª]?|m\.sc|msc|ph\.d|phd|d\.sc)"
_JOIN = r"[\s:,;\-–?]*"

_TITLES_AT_START = re.compile(rf"^(?:{_START_TITLE}\b\.?{_JOIN})+", re.IGNORECASE)
_TITLES_AT_END = re.compile(
    rf"(?:[\s,;:\-–?(]+{_END_TITLE}\b\.?\)?)+\s*$", re.IGNORECASE
)
_LINK = re.compile(r"javascript:|https?://|www\.", re.IGNORECASE)
_SEVERAL = re.compile(r"[/;]|\bco-?orientador", re.IGNORECASE)
_SEVERAL_NOT_SLASH = re.compile(r";|\bco-?orientador", re.IGNORECASE)
_JOINED_BY_E = re.compile(r"\S\s+e\s+\S")
_FOOTNOTE = re.compile(r"^(.*[^\W\d_])\d+$", re.DOTALL)
_EDGE = " .,;:-–?"
_CITATION = re.compile(r"\(\s*(?:co-?)?orientador", re.IGNORECASE)


@dataclass(frozen=True)
class CleanedName:
    """The name to store (``None``: not a name) and what was done to get it."""

    name: Optional[str]
    kinds: Tuple[str, ...]
    # Branch 041: every student, in source order; (name,) or () by default.
    # Left out of equality so the results of branch 036 compare as before.
    names: Tuple[str, ...] = field(default=None, compare=False)

    def __post_init__(self):
        if self.names is None:
            object.__setattr__(
                self, "names", (self.name,) if self.name is not None else ()
            )


def clean_student_name(raw) -> CleanedName:
    """Clean the student text of a Lattes advisorship item."""
    text = " ".join(str(raw).split()) if raw is not None else ""
    if not text:
        return CleanedName(None, ("empty",))
    kinds = []

    link = _LINK.search(text)
    if link and link.start() > 0:
        text = text[: link.start()].rstrip()
        kinds.append("link")

    # Branch 041: "(orientador: …" belongs to a citation, never to the name.
    citation = _CITATION.search(text)
    if citation and citation.start() > 0:
        text = text[: citation.start()].rstrip(_EDGE + "(")
        kinds.append("citation")

    # Branch 041: a "/" after the name belongs to the work title; cut it first.
    if "/" in text and not _SEVERAL_NOT_SLASH.search(text):
        head = head_before_work_title(text)
        if (
            head is not None
            and len(head.split()) >= 2
            and not any(char.isdigit() for char in head)
        ):
            text = head
            kinds.append("work_title")
        if "/" in text:
            return _split(text, kinds)
        if "work_title" in kinds:
            return _finish(text, kinds)

    if _SEVERAL.search(text):
        return CleanedName(text, tuple(kinds + ["several"]))

    head = head_before_work_title(text)
    if head is None:
        if "," in text:
            return CleanedName(text, tuple(kinds + ["several"]))
    elif "," in head or _JOINED_BY_E.search(head):
        return CleanedName(text, tuple(kinds + ["several"]))
    elif len(head.split()) >= 2 and not any(char.isdigit() for char in head):
        text = head
        kinds.append("work_title")
    else:
        return CleanedName(text, tuple(kinds + ["uncut"]))

    return _finish(text, kinds)


def _finish(text: str, kinds: list) -> CleanedName:
    """Drops academic titles and a footnote number, then checks the name."""
    without_titles = _TITLES_AT_END.sub("", _TITLES_AT_START.sub("", text))
    without_titles = without_titles.strip(_EDGE)
    if without_titles != text.strip(_EDGE):
        kinds.append("title")
        text = without_titles

    footnote = _FOOTNOTE.match(text)
    if footnote:
        text = footnote.group(1)
        kinds.append("footnote")

    letters = [char for char in text if char.isalpha()]
    if len(letters) <= 2 or any(char.isdigit() for char in text):
        return CleanedName(None, tuple(kinds + ["not_a_name"]))
    return CleanedName(text, tuple(kinds))


def _split(text: str, kinds: list) -> CleanedName:
    """Branch 041: one student per part of a field joined by "/", when every
    part that is not a fragment is a name of two words or more; otherwise the
    field is returned as written (``several``)."""
    names = []
    for part in text.split("/"):
        part = part.strip(_EDGE)
        if is_name_fragment(part):
            continue
        cleaned = clean_student_name(part)
        if cleaned.name is None or len(cleaned.name.split()) < 2:
            return CleanedName(text, tuple(kinds + ["several"]))
        names.append(cleaned.name)
    if not names:
        return CleanedName(None, tuple(kinds + ["not_a_name"]))
    return CleanedName(names[0], tuple(kinds + ["split"]), tuple(names))
