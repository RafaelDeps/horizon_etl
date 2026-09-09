import unicodedata
from typing import Any

_PARTICLES = frozenset(
    {"DA", "DE", "DI", "DO", "DOS", "DAS", "DU", "DEL", "DELA", "E", "Y"}
)

_HONORIFICS = frozenset(
    {"DR", "DRA", "PROF", "MSC", "PHD", "ME", "MA", "BEL", "ESP", "ENG", "SR", "SRA"}
)

_GENERATIONAL_ABBREVIATIONS = {"JR": "JUNIOR"}


def normalize_participant_name(
    name: Any,
    canonical_particles: bool = True,
    canonical_suffixes: bool = False,
    drop_particles: bool = False,
) -> str:
    """Builds the shared participant-name identity key (contract R7).

    The function is the single normal form every participant comparison path
    must use: case-insensitive, diacritics stripped (NFD), punctuation and
    hyphens turned into separators, whitespace collapsed, and surname particles
    canonicalized to one lower-case form. Any two spellings that differ only in
    those dimensions produce the same key.

    ``canonical_suffixes`` folds the ``Jr.`` abbreviation into ``JUNIOR`` so the
    two spellings of the same generational suffix produce one key. ``FILHO``,
    ``NETO`` and ``SOBRINHO`` are deliberately left distinct: they separate
    generations (father/son, grandfather/grandson) and folding them together
    would create the false-merge class the dedup guards refuse. The default
    keeps ``Jr.`` spelled as ``JR`` to preserve contract R7's pinned output.

    ``drop_particles`` removes the surname particles entirely from the key, so a
    spelling with or without ``dos``/``da``/``de`` yields one key. Exact-match
    paths and consolidation grouping use this invariant form because they never
    rely on fuzzy similarity (contract R7 and R15).
    """
    if name is None:
        return ""
    text = unicodedata.normalize("NFD", str(name))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    tokens = text.upper().split()
    if drop_particles:
        tokens = [token for token in tokens if token not in _PARTICLES]
    elif canonical_particles:
        tokens = [
            token if token not in _PARTICLES else token.lower() for token in tokens
        ]
    if canonical_suffixes:
        tokens = [_GENERATIONAL_ABBREVIATIONS.get(token, token) for token in tokens]
    return " ".join(tokens)


def is_junk_name(name: Any) -> bool:
    """True when the name is not plausibly a person's name (contract R13).

    Honorific-only and single-token names ("Dr", "Prof Dr", "") must never be
    merged with anything. A name remains plausible when at least two non-titular
    tokens survive after the honorific tokens are removed.
    """
    tokens = normalize_participant_name(name, canonical_particles=False).split()
    if len(tokens) < 2:
        return True
    name_tokens = [token for token in tokens if token not in _HONORIFICS]
    return len(name_tokens) < 2
