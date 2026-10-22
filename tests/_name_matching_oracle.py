"""Frozen copies of the pre-016 name-matching algorithms (spec 016).

These are the equivalence reference for tests/test_person_matcher_index.py and
tests/test_researcher_resolution_cache.py. They are verbatim copies of the code
as it stood before spec 016 and must NEVER be edited: if production behaviour
changes on purpose, the tests and this oracle are revisited together in a new
spec.
"""

import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from thefuzz import fuzz, process

# --- src/core/logic/person_identity.py (pre-016) ---------------------------

_PARTICLES = frozenset(
    {"DA", "DE", "DI", "DO", "DOS", "DAS", "DU", "DEL", "DELA", "E", "Y"}
)

_GENERATIONAL_ABBREVIATIONS = {"JR": "JUNIOR"}


def oracle_normalize_participant_name(
    name: Any,
    canonical_particles: bool = True,
    canonical_suffixes: bool = False,
    drop_particles: bool = False,
) -> str:
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


def oracle_normalize_name(name: str) -> str:
    """PersonMatcher.normalize_name (pre-016)."""
    return oracle_normalize_participant_name(name, canonical_particles=False)


# --- src/core/logic/person_matcher.py, match_or_create steps 2 and 3 --------


def oracle_normalised_exact(
    persons_cache: Dict[str, Any], normalized_input: str
) -> Optional[Tuple[str, Any]]:
    """Step 2: first cached raw name (iteration order) with the same key."""
    for cached_name, person in persons_cache.items():
        norm_cached = oracle_normalize_name(cached_name)
        if norm_cached == normalized_input:
            return cached_name, person
    return None


def oracle_fuzzy(
    persons_cache: Dict[str, Any], normalized_input: str, strict_match: bool
) -> Tuple[Optional[str], bool]:
    """Step 3. Returns (matched original name or None, strict_rejected)."""
    names_in_cache = list(persons_cache.keys())
    if names_in_cache and normalized_input:
        normalized_to_original = {oracle_normalize_name(n): n for n in names_in_cache}
        normalized_list = list(normalized_to_original.keys())

        best_norm_match, score = process.extractOne(
            normalized_input, normalized_list, scorer=fuzz.token_sort_ratio
        )

        if score >= 90:
            if strict_match and score < 100:
                return None, True
            return normalized_to_original[best_norm_match], False
    return None, False


# --- src/core/logic/researcher_resolution.py (pre-016) ----------------------


def oracle_resolve_researcher_by_name(
    all_researchers: Iterable[Any],
    *,
    name: Optional[str],
    identification_id: Optional[str] = None,
) -> Optional[Any]:
    normalize_participant_name = oracle_normalize_participant_name
    if not name:
        return None

    target_norm = normalize_participant_name(name)

    best = None
    best_score = float("-inf")
    for researcher in all_researchers:
        score = 0
        res_name = getattr(researcher, "name", None) or ""
        res_identification = getattr(researcher, "identification_id", None) or ""

        if (
            identification_id
            and res_identification
            and str(res_identification).casefold() == str(identification_id).casefold()
        ):
            score += 200
        if res_name and res_name.casefold() == name.casefold():
            score += 150
        elif normalize_participant_name(res_name) == target_norm:
            score += 100
        elif normalize_participant_name(
            res_name, canonical_suffixes=True, drop_particles=True
        ) == normalize_participant_name(
            name, canonical_suffixes=True, drop_particles=True
        ):
            score += 90

        if score > best_score:
            best = researcher
            best_score = score

    return best if best_score > 0 else None


# --- src/core/logic/person_matcher.py (pre-016), whole class, verbatim ---------
# Only the class name changed; imports are local to keep this module self-contained.

from eo_lib import Person, PersonController  # noqa: E402
from loguru import logger  # noqa: E402

# Bound to the frozen copy above, so the oracle never sees production changes.
normalize_participant_name = oracle_normalize_participant_name
from src.core.logic.pii_anonymizer import (  # noqa: E402
    anonymize_email,
    is_anonymized_email,
)


class OraclePersonMatcher:
    """
    Service responsible for matching incoming names with existing Person records.

    This class handles name normalization, fuzzy matching, and caching to ensure
    idempotency and efficiency when identifying or creating persons during ingestion.
    """

    def __init__(self, person_controller: PersonController):
        """
        Initializes the PersonMatcher.

        Args:
            person_controller (PersonController): Controller used to interact with Person records.
        """
        self.person_controller = person_controller
        self._persons_cache: Dict[str, Person] = {}
        self._emails_cache: Dict[str, Person] = {}
        self._canonical_cache: Dict[str, Person] = {}
        self._invariant_cache: Dict[str, Person] = {}

    def preload_cache(self):
        """
        Preloads the internal persons cache from the database.

        Fetches all persons and populates _persons_cache using their names
        and _emails_cache using their emails.
        """
        logger.info("Pre-loading persons cache...")
        try:
            all_persons = self.person_controller.get_all()
            self._persons_cache = {}
            self._emails_cache = {}
            self._canonical_cache = {}
            self._invariant_cache = {}
            for p in all_persons:
                if isinstance(p, dict):
                    name = p.get("name")
                    emails = p.get("emails") or ([p["email"]] if p.get("email") else [])
                else:
                    name = getattr(p, "name", None)
                    # Person has an `emails` relationship (PersonEmail rows), not an `email` column.
                    emails = [
                        e.email if hasattr(e, "email") else e
                        for e in (getattr(p, "emails", None) or [])
                    ]
                if name:
                    self._persons_cache[name] = p
                    canonical_name = self.canonicalize_name(name)
                    if canonical_name:
                        current = self._canonical_cache.get(canonical_name)
                        if current is None or self._person_quality_score(
                            p
                        ) > self._person_quality_score(current):
                            self._canonical_cache[canonical_name] = p
                    invariant_name = self.invariant_canonicalize_name(name)
                    if invariant_name:
                        current = self._invariant_cache.get(invariant_name)
                        if current is None or self._person_quality_score(
                            p
                        ) > self._person_quality_score(current):
                            self._invariant_cache[invariant_name] = p
                for email in emails:
                    if email:
                        self._emails_cache[email.strip().lower()] = p
            logger.info(
                f"Loaded {len(self._persons_cache)} persons and {len(self._emails_cache)} emails into cache"
            )
        except Exception as e:
            logger.warning(f"Failed to preload persons cache: {e}")

    def normalize_name(self, name: str) -> str:
        """Normalizes a name for consistent comparison.

        Delegates to the shared participant-name key function so every
        comparison path agrees on one normal form.
        """
        return normalize_participant_name(name, canonical_particles=False)

    def canonicalize_name(self, name: str) -> str:
        """Builds a stable comparison key for names."""
        return normalize_participant_name(name, canonical_particles=True)

    def invariant_canonicalize_name(self, name: str) -> str:
        """Builds the particle- and suffix-omission-invariant name key.

        ``Paulo Sérgio Dos Santos Júnior``, ``Paulo Sérgio Santos Júnior`` and
        ``Paulo Sérgio Santos Jr.`` all yield ``PAULO SERGIO SANTOS JUNIOR``.
        This is an exact-match key (never fuzzy), so it is safe to use when
        consolidating groups or resolving participants by name.
        """
        return normalize_participant_name(
            name, canonical_suffixes=True, drop_particles=True
        )

    def _email_keys(self, email: str) -> List[str]:
        """Candidate cache keys for an email.

        Stored emails are LGPD-anonymized by the session hook, so an incoming
        raw email must also be looked up by its anonymized forms (hashed
        as-written and lowercased, since the hook does not normalize case).
        """
        stripped = email.strip()
        keys = [stripped.lower()]
        if not is_anonymized_email(stripped):
            for candidate in (
                anonymize_email(stripped),
                anonymize_email(stripped.lower()),
            ):
                if candidate and candidate not in keys:
                    keys.append(candidate)
        return keys

    def _register_email(self, email: Optional[str], person: Person) -> None:
        if not email:
            return
        for key in self._email_keys(email):
            self._emails_cache[key] = person

    def _person_quality_score(self, person: Person) -> int:
        """Prefers the richer record when duplicates share the same canonical name."""
        score = 0
        for attr in (
            "identification_id",
            "emails",
            "resume",
            "citation_names",
            "cnpq_url",
        ):
            value = (
                person.get(attr)
                if isinstance(person, dict)
                else getattr(person, attr, None)
            )
            if value:
                score += 10
        return score

    def match_or_create(
        self, name: str, email: Optional[str] = None, strict_match: bool = False
    ) -> Optional[Person]:
        """
        Finds a person by email or name.
        Uses normalization and (optionally) fuzzy matching for names.
        Creates a new Person if no match is found.

        Args:
            name (str): The name of the person to match or create.
            email (Optional[str]): The email of the person to match.
            strict_match (bool): If True, only exact normalized matches (score 100) are accepted for name.

        Returns:
            Optional[Person]: The matched or newly created Person object, or None if creation fails.
        """
        if not name or not name.strip():
            # If name is missing but email is provided, maybe we can find by email anyway?
            # User requirement says Student and Supervisor are people and we should use name OR email.
            if not email:
                return None

        # 1. Match by Email first (highest priority)
        if email:
            for email_key in self._email_keys(email):
                if email_key in self._emails_cache:
                    logger.debug(f"Match found by email: {email_key}")
                    return self._emails_cache[email_key]

        name = name.strip() if name else ""
        normalized_input = self.normalize_name(name)
        canonical_input = self.canonicalize_name(name)
        invariant_input = self.invariant_canonicalize_name(name)

        # 1.5 Canonical exact match.
        # This collapses duplicates such as "De"/"de" and accent-only variants.
        if canonical_input and canonical_input in self._canonical_cache:
            person = self._canonical_cache[canonical_input]
            self._register_email(email, person)
            self._persons_cache[name] = person
            return person

        # 1.6 Exact raw-name match.
        if name in self._persons_cache:
            person = self._persons_cache[name]
            self._register_email(email, person)
            return person

        # 2. Exact Match in Cache (Normalized)
        for cached_name, person in self._persons_cache.items():
            norm_cached = self.normalize_name(cached_name)
            if norm_cached == normalized_input:
                self._persons_cache[name] = person
                self._register_email(email, person)
                return person

        # 2.5 Invariant exact match: particles omitted and the generational
        # suffix written canonically. Exact only — no fuzzy similarity.
        if invariant_input and invariant_input in self._invariant_cache:
            person = self._invariant_cache[invariant_input]
            self._persons_cache[name] = person
            self._register_email(email, person)
            return person

        # 3. Fuzzy Matching in Cache
        names_in_cache = list(self._persons_cache.keys())
        if names_in_cache and normalized_input:
            normalized_to_original = {self.normalize_name(n): n for n in names_in_cache}
            normalized_list = list(normalized_to_original.keys())

            best_norm_match, score = process.extractOne(
                normalized_input, normalized_list, scorer=fuzz.token_sort_ratio
            )

            # Threshold of 90%
            if score >= 90:
                # If strict match is enabled, we only accept 100% score (same tokens)
                if strict_match and score < 100:
                    logger.debug(
                        f"Fuzzy match '{best_norm_match}' ignored due to strict matching policy (score: {score})"
                    )
                else:
                    original_name = normalized_to_original[best_norm_match]
                    logger.info(
                        f"Fuzzy match found: '{name}' matches '{original_name}' (score: {score})"
                    )
                    person = self._persons_cache[original_name]
                    self._persons_cache[name] = person
                    self._register_email(email, person)
                    return person

        # 4. Create new person (if no match found)
        try:
            emails = [email] if email else []
            person = self.person_controller.create_person(name=name, emails=emails)
            self._persons_cache[name] = person
            if canonical_input:
                current = self._canonical_cache.get(canonical_input)
                if current is None or self._person_quality_score(
                    person
                ) > self._person_quality_score(current):
                    self._canonical_cache[canonical_input] = person
            if invariant_input:
                current = self._invariant_cache.get(invariant_input)
                if current is None or self._person_quality_score(
                    person
                ) > self._person_quality_score(current):
                    self._invariant_cache[invariant_input] = person
            self._register_email(email, person)
            logger.debug(f"Created person: {name} (emails: {emails})")
            return person
        except Exception as e:
            logger.warning(f"Failed to create person '{name}': {e}")
            return None
