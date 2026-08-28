import unicodedata
from typing import Any

_PARTICLES = frozenset(
    {"DA", "DE", "DI", "DO", "DOS", "DAS", "DU", "DEL", "DELA", "E", "Y"}
)

_HONORIFICS = frozenset(
    {"DR", "DRA", "PROF", "MSC", "PHD", "ME", "MA", "BEL", "ESP", "ENG", "SR", "SRA"}
)


def normalize_participant_name(name: Any, canonical_particles: bool = True) -> str:
    """Builds the shared participant-name identity key (contract R7).

    The function is the single normal form every participant comparison path
    must use: case-insensitive, diacritics stripped (NFD), punctuation and
    hyphens turned into separators, whitespace collapsed, and surname particles
    canonicalized to one lower-case form. Any two spellings that differ only in
    those dimensions produce the same key.
    """
    if name is None:
        return ""
    text = unicodedata.normalize("NFD", str(name))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    tokens = text.upper().split()
    if canonical_particles:
        tokens = [
            token if token not in _PARTICLES else token.lower() for token in tokens
        ]
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
