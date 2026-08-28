from typing import Dict, List, Optional

from eo_lib import Person, PersonController
from loguru import logger
from thefuzz import fuzz, process

from src.core.logic.person_identity import normalize_participant_name
from src.core.logic.pii_anonymizer import anonymize_email, is_anonymized_email


class PersonMatcher:
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
            self._register_email(email, person)
            logger.debug(f"Created person: {name} (emails: {emails})")
            return person
        except Exception as e:
            logger.warning(f"Failed to create person '{name}': {e}")
            return None
