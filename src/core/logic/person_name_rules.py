"""Rules for person names read from Lattes free text (branch 041).

* ``is_name_fragment``: a text that is a title or a piece of a name ("Dr",
  "Prof", "Ph", a single letter, digits, "-"), never a person. Lattes project
  members and degree advisors produced such "people".
* ``advisor_name``: the advisor (or co-advisor) of an academic degree, read
  from the degree description. The old capture stopped at the first full stop,
  so "Orientador: Prof. Dr. José Antônio da Silva." stored the person "Prof".
* ``head_before_work_title``: the text before the first full stop that ends a
  name (an initial such as "C." does not), shared with the student rule.

Every rule depends on the text alone, so an incremental run and a rebuild
agree. Contract: specs/041-dashboard-visible-fixes/contracts/dashboard-fixes.md,
sections 1 and 2.
"""

import re
import unicodedata
from typing import Optional

# Whole-word academic titles that can open a name (also used by the student
# rule of branch 036).
START_TITLE = (
    r"(?:professor[aª]?|prof[aª]?|doutor[a]?|dr[aª]?|mestre|m\.sc|msc|me|ms"
    r"|ph\.d|phd|d\.sc)"
)
_TITLE_TOKEN = re.compile(rf"^{START_TITLE}$", re.IGNORECASE)

# Titles dropped before an advisor's name. Each must be followed by a full
# stop, a space or the end, so "Maria" or "Mendes" are never cut.
_ADVISOR_TITLE = re.compile(
    r"^(?:professor[aª]?|prof[aª]?|pro|doutor[a]?|dr[aª]?|mestre|m\.?\s?sc|msc"
    r"|d\.?\s?sc|dsc|ph\.?\s?d|phd|me|ma|esp|eng|ing)(?=[.\s:]|$)\.?:?\s*",
    re.IGNORECASE,
)
_ENUMERATION = re.compile(r"^\d+\s*[.)\-]\s*")
_ADVISOR_LABEL = re.compile(r"(?<![A-Za-z\-])orientador[a]?\s*:\s*", re.IGNORECASE)
_CO_ADVISOR_LABEL = re.compile(r"co-?orientador[a]?\s*:\s*", re.IGNORECASE)
_END_OF_FIELD = re.compile(
    r"(?:co-?orientador[a]?|orientador[a]?|bolsista|palavras-chave|grande [áa]rea"
    r"|t[íi]tulo|[áa]rea|ano de [^:\s]+)\b[^:]{0,8}:|[;)]|https?://|www\.",
    re.IGNORECASE,
)
_SECOND_PERSON = re.compile(rf",|\s+e\s+(?={START_TITLE}\b)", re.IGNORECASE)
_NOT_DEFINED = {"nao definido", "nao definida", "nao ha", "nenhum"}
_EDGE = " .,;:-–"

_FRAGMENT_WORDS = {
    "dr",
    "dra",
    "prof",
    "profa",
    "pro",
    "ph",
    "phd",
    "msc",
    "me",
    "ma",
    "m",
    "d",
    "dsc",
    "xxx",
    "licenciatura",
    "esp",
    "eng",
    "ing",
}


def _plain(text: str) -> str:
    """Lower case, without accents (ª and º become a and o)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def is_name_fragment(text) -> bool:
    """True when the text is a title or a piece of a name, never a person."""
    if text is None:
        return True
    core = _plain(str(text)).strip(" .-–,;:")
    if not core:
        return True
    if len(core) == 1 or core.isdigit():
        return True
    return core in _FRAGMENT_WORDS


def is_initial(token: str) -> bool:
    """The token before a full stop that does not end the name: an initial
    ("Q"), an abbreviation that holds a full stop ("S.N") or a title ("Prof")."""
    letters = [char for char in token if char.isalpha()]
    return len(letters) <= 2 or "." in token or bool(_TITLE_TOKEN.match(token))


def head_before_work_title(text: str) -> Optional[str]:
    """The text before the first full stop that may end the name, or None."""
    start = 0
    while True:
        stop = text.find(". ", start)
        if stop < 0:
            return None
        token = text[text.rfind(" ", 0, stop) + 1 : stop]
        if not is_initial(token):
            return text[:stop].strip()
        start = stop + 2


def _drop_titles(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _ENUMERATION.sub("", text)
        text = _ADVISOR_TITLE.sub("", text).lstrip(" .,:-–")
    return text


def advisor_name(description, co: bool = False) -> Optional[str]:
    """The advisor (``co=True``: the co-advisor) named in a degree description,
    without academic titles, or None when there is no name."""
    if not description:
        return None
    text = " ".join(str(description).split())
    label = (_CO_ADVISOR_LABEL if co else _ADVISOR_LABEL).search(text)
    if label is None:
        return None
    rest = text[label.end() :]
    end = _END_OF_FIELD.search(rest)
    field = rest[: end.start()] if end else rest

    field = _drop_titles(field.strip())
    second = _SECOND_PERSON.search(field)
    if second:
        field = field[: second.start()]
    head = head_before_work_title(field)
    if head is not None:
        field = head
    name = field.strip(_EDGE)

    if is_name_fragment(name) or _plain(name) in _NOT_DEFINED:
        return None
    return name
