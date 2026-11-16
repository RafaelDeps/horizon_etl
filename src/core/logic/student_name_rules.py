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

Contract: specs/036-small-fixes-batch/contracts/small-fixes.md, section 1.
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# Whole-word academic titles. The full words are removed at the start only: at
# the end "Mestre" or "Doutor" may be a surname.
_START_TITLE = (
    r"(?:professor[aª]?|prof[aª]?|doutor[a]?|dr[aª]?|mestre|m\.sc|msc|me|ms"
    r"|ph\.d|phd|d\.sc)"
)
_END_TITLE = r"(?:prof[aª]?|dr[aª]?|m\.sc|msc|ph\.d|phd|d\.sc)"
_JOIN = r"[\s:,;\-–?]*"

_TITLES_AT_START = re.compile(rf"^(?:{_START_TITLE}\b\.?{_JOIN})+", re.IGNORECASE)
_TITLES_AT_END = re.compile(
    rf"(?:[\s,;:\-–?(]+{_END_TITLE}\b\.?\)?)+\s*$", re.IGNORECASE
)
_TITLE_TOKEN = re.compile(rf"^{_START_TITLE}$", re.IGNORECASE)
_LINK = re.compile(r"javascript:|https?://|www\.", re.IGNORECASE)
_SEVERAL = re.compile(r"[/;]|\bco-?orientador", re.IGNORECASE)
_JOINED_BY_E = re.compile(r"\S\s+e\s+\S")
_FOOTNOTE = re.compile(r"^(.*[^\W\d_])\d+$", re.DOTALL)
_EDGE = " .,;:-–?"


@dataclass(frozen=True)
class CleanedName:
    """The name to store (``None``: not a name) and what was done to get it."""

    name: Optional[str]
    kinds: Tuple[str, ...]


def _is_initial(token: str) -> bool:
    """The token before a full stop that does not end the name: an initial
    ("Q"), an abbreviation that holds a full stop ("S.N") or a title ("Prof")."""
    letters = [char for char in token if char.isalpha()]
    return len(letters) <= 2 or "." in token or bool(_TITLE_TOKEN.match(token))


def _head_before_work_title(text: str) -> Optional[str]:
    """The text before the first full stop that may end the name, or None."""
    start = 0
    while True:
        stop = text.find(". ", start)
        if stop < 0:
            return None
        token = text[text.rfind(" ", 0, stop) + 1 : stop]
        if not _is_initial(token):
            return text[:stop].strip()
        start = stop + 2


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

    if _SEVERAL.search(text):
        return CleanedName(text, tuple(kinds + ["several"]))

    head = _head_before_work_title(text)
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
