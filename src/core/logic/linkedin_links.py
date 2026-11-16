"""LinkedIn profile links from a local list (spec 037).

The maintainer keeps a local, unversioned list, one person per line: the
address of the person's public LinkedIn profile, a comma, the full name. No
source the ETL collects carries this link, so the list is its only source.

This module is the rule, with no file and no database access: it reads the
lines, puts a link in one normal form, and plans which links to store on which
persons. A name is used only when it equals the name of exactly one stored
person (ignoring case, accents and spaces); everything else is reported and
nothing is guessed.

Contract: specs/037-alumni-linkedin-links/contracts/linkedin-links.md.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from src.core.logic.initiative_identity import normalize_text

PROFILE_PREFIX = "https://www.linkedin.com/in/"

# Outcomes of a line.
STORED = "stored"
NOT_FOUND = "not_found"
SEVERAL_PERSONS = "several_persons"
CONFLICT = "conflict"
INVALID = "invalid"

Row = Tuple[int, str, str]  # person id, link, name as written in the list

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


@dataclass(frozen=True)
class ListLine:
    """One line of the list: its position in the file, the link in the normal
    form (``None`` when it is not a profile address), the name as written and
    ``"invalid"`` when the line cannot be used."""

    number: int
    link: Optional[str]
    name: str
    problem: Optional[str]


def normalize_profile_link(text) -> Optional[str]:
    """``https://www.linkedin.com/in/<profile>`` for a LinkedIn profile
    address written in any usual way, or ``None`` for anything else."""
    value = str(text).strip() if text is not None else ""
    if not value or any(char.isspace() for char in value):
        return None
    if not _SCHEME.match(value):
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2 or segments[0].lower() != "in":
        return None
    return PROFILE_PREFIX + segments[1]


def parse_list(lines: Iterable[str]) -> List[ListLine]:
    """One ``ListLine`` per line that is neither empty nor a comment."""
    parsed = []
    for number, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        link_text, comma, name = text.partition(",")
        name = name.strip()
        link = normalize_profile_link(link_text)
        usable = bool(comma) and bool(name) and link is not None
        parsed.append(ListLine(number, link, name, None if usable else INVALID))
    return parsed


@dataclass(frozen=True)
class LineOutcome:
    """What happened to one line of the list."""

    number: int
    name: str
    outcome: str


@dataclass(frozen=True)
class Plan:
    """The rows to add, change and remove so the stored links equal the
    usable lines of the list, and the outcome of every line."""

    add: List[Row]
    change: List[Row]
    remove: List[int]
    outcomes: List[LineOutcome]


def plan(
    lines: Iterable[ListLine],
    persons: Iterable[Tuple[int, str]],
    stored: Dict[int, Tuple[str, str]],
) -> Plan:
    """Decides, from the list and the stored state alone, what to write.

    ``persons`` are ``(person id, name)`` pairs; ``stored`` maps a person id
    to its ``(link, name as written)``. Nothing is written here.
    """
    persons_by_name: Dict[str, List[int]] = defaultdict(list)
    for person_id, name in persons:
        key = normalize_text(name)
        if key:
            persons_by_name[key].append(person_id)

    # Lines that contradict each other are not used: a name written with two
    # different links, or a link written under two different names. The same
    # name with the same link on several lines is one line.
    links_of_name: Dict[str, set] = defaultdict(set)
    names_of_link: Dict[str, set] = defaultdict(set)
    valid = [line for line in lines if not line.problem]
    for line in valid:
        key = normalize_text(line.name)
        links_of_name[key].add(line.link)
        names_of_link[line.link].add(key)

    add: List[Row] = []
    change: List[Row] = []
    outcomes: List[LineOutcome] = []
    planned: Dict[int, str] = {}
    for line in lines:
        outcome = _outcome_of(line, persons_by_name, links_of_name, names_of_link)
        outcomes.append(LineOutcome(line.number, line.name, outcome))
        if outcome != STORED:
            continue
        person_id = persons_by_name[normalize_text(line.name)][0]
        if person_id in planned:
            continue  # the same line again
        planned[person_id] = line.link
        row = (person_id, line.link, line.name)
        if person_id not in stored:
            add.append(row)
        elif stored[person_id][0] != line.link:
            change.append(row)
    # The list is the source of truth: a stored link whose person has no
    # usable line any more (line gone, no longer usable, or person gone) goes.
    # A list with no usable line is taken for a mistake (an empty or wrong
    # file), not for a wish to clear every link: nothing is removed.
    if not planned:
        return Plan(add=[], change=[], remove=[], outcomes=outcomes)
    remove = sorted(person_id for person_id in stored if person_id not in planned)
    return Plan(add=add, change=change, remove=remove, outcomes=outcomes)


def _outcome_of(line, persons_by_name, links_of_name, names_of_link) -> str:
    if line.problem:
        return INVALID
    key = normalize_text(line.name)
    if len(links_of_name[key]) > 1 or len(names_of_link[line.link]) > 1:
        return CONFLICT
    matches = persons_by_name.get(key, [])
    if not matches:
        return NOT_FOUND
    if len(matches) > 1:
        return SEVERAL_PERSONS
    return STORED
