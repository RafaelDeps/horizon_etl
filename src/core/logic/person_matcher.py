from typing import Dict, List, Optional

from eo_lib import Person, PersonController
from loguru import logger
from rapidfuzz import fuzz as rapid_fuzz
from rapidfuzz import process as rapid_process
from thefuzz import utils as fuzz_utils

from src.core.logic.horizon_identity import (
    FUZZY_MATCH_THRESHOLD,
    hash12,
    person_reference_key,
)
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
        self._invariant_cache: Dict[str, Person] = {}

        # Name index (spec 016), kept in step with _persons_cache by _cache_name.
        # match_or_create used to re-normalise every cached name (~17k) on each
        # lookup for the normalised exact step and again for the fuzzy step.
        self._first_by_norm: Dict[str, str] = {}
        self._last_by_norm: Dict[str, str] = {}
        self._fuzzy_keys: List[str] = []
        self._fuzzy_processed: List[str] = []
        self._stats = {
            "email": 0,
            "canonical": 0,
            "exact": 0,
            "normalised": 0,
            "invariant": 0,
            "fuzzy": 0,
            "strict_rejected": 0,
            "created": 0,
            "create_failed": 0,
            "fuzzy_ties": 0,
        }

    def _reset_name_index(self) -> None:
        self._first_by_norm = {}
        self._last_by_norm = {}
        self._fuzzy_keys = []
        self._fuzzy_processed = []

    def reset_cache(self) -> None:
        """Drops every cached person (spec 021): after a rolled-back document
        some of them no longer exist; the next lookup reloads the cache."""
        self._persons_cache.clear()
        self._emails_cache.clear()
        self._canonical_cache.clear()
        self._invariant_cache.clear()
        self._reset_name_index()

    def _cache_name(self, raw: str, person: Person) -> None:
        """The only writer of _persons_cache.

        A dict keeps a key's first insertion position, so only a NEW raw name
        changes the index: it may be the first name for its normalised key
        (normalised exact step) and is always the last one in iteration order
        (the fuzzy step maps each key to the last name, as the dict
        comprehension it replaces did). Re-assigning a known name changes
        nothing but the stored person.
        """
        if raw not in self._persons_cache:
            key = self.normalize_name(raw)
            self._first_by_norm.setdefault(key, raw)
            if key not in self._last_by_norm:
                self._fuzzy_keys.append(key)
                self._fuzzy_processed.append(
                    fuzz_utils.full_process(key, force_ascii=True)
                )
            self._last_by_norm[key] = raw
        self._persons_cache[raw] = person

    def log_match_summary(self, label: str) -> None:
        s = self._stats
        logger.info(
            f"Person matching [{label}]: email={s['email']} "
            f"canonical={s['canonical']} exact={s['exact']} "
            f"normalised={s['normalised']} invariant={s['invariant']} "
            f"fuzzy={s['fuzzy']} strict_rejected={s['strict_rejected']} "
            f"created={s['created']} create_failed={s['create_failed']} "
            f"fuzzy_ties={s['fuzzy_ties']}"
        )

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
            self._reset_name_index()
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
                    self._cache_name(name, p)
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

    def _break_fuzzy_tie(self, found, normalized_input: str):
        """Picks one of the candidates sharing the best fuzzy score by a fixed
        rule, not by cache order (spec 020, FR-023a): the richer record first
        (as the canonical step does), then the exact normalized name, then the
        smallest name hash. Counts the ties."""
        if not found:
            return None
        top = max(raw for _, raw, _ in found)
        tied = [item for item in found if item[1] == top]
        if len(tied) == 1:
            return tied[0]
        self._stats["fuzzy_ties"] += 1

        def rank(item):
            key = self._fuzzy_keys[item[2]]
            person = self._persons_cache[self._last_by_norm[key]]
            return (
                -self._person_quality_score(person),
                0 if key == normalized_input else 1,
                hash12(key),
            )

        return min(tied, key=rank)

    def match_or_create(
        self, name: str, email: Optional[str] = None, strict_match: bool = False
    ) -> Optional[Person]:
        """Resolves a person (see ``_match_or_create``) and, inside a source
        document (spec 021), records the resolution and the person it carries."""
        person = self._match_or_create(name, email=email, strict_match=strict_match)
        from src.core.logic.document_skip import carry, current, document_reference

        if current() is None:  # outside a document: nothing to record
            return person
        document_reference(
            "person_name",
            self.normalize_name(name or ""),
            person_reference_key(person.name) if person is not None else "not_found",
        )
        if person is not None and getattr(person, "id", None) is not None:
            carry("person", person.id)
        return person

    def _match_or_create(
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
                    self._stats["email"] += 1
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
            self._cache_name(name, person)
            self._stats["canonical"] += 1
            return person

        # 1.6 Exact raw-name match.
        if name in self._persons_cache:
            person = self._persons_cache[name]
            self._register_email(email, person)
            self._stats["exact"] += 1
            return person

        # 2. Exact Match in Cache (Normalized): the first cached name, in cache
        # order, with the same key — read from the index, not by re-normalising
        # every cached name.
        first_name = self._first_by_norm.get(normalized_input)
        if first_name is not None:
            person = self._persons_cache[first_name]
            self._cache_name(name, person)
            self._register_email(email, person)
            self._stats["normalised"] += 1
            return person

        # 2.5 Invariant exact match: particles omitted and the generational
        # suffix written canonically. Exact only — no fuzzy similarity.
        if invariant_input and invariant_input in self._invariant_cache:
            person = self._invariant_cache[invariant_input]
            self._cache_name(name, person)
            self._register_email(email, person)
            self._stats["invariant"] += 1
            return person

        # 3. Fuzzy Matching in Cache. Same decision as the former
        # thefuzz.process.extractOne(normalized_input, keys, token_sort_ratio):
        # candidates are pre-processed once (_fuzzy_processed) instead of on
        # every call; the query gets thefuzz's two processing passes; thefuzz
        # picked the winner on the unrounded score and rounded it afterwards, so
        # the 90 threshold becomes a cutoff of 89.5 on the raw score.
        best = None
        if self._fuzzy_keys and normalized_input:
            query = fuzz_utils.full_process(
                fuzz_utils.full_process(normalized_input), force_ascii=True
            )
            if query:
                found = rapid_process.extract(
                    query,
                    self._fuzzy_processed,
                    scorer=rapid_fuzz.token_sort_ratio,
                    processor=None,
                    score_cutoff=FUZZY_MATCH_THRESHOLD - 0.5,
                    limit=None,
                )
                best = self._break_fuzzy_tie(found, normalized_input)
        if best is not None:
            _, raw_score, index = best
            best_norm_match = self._fuzzy_keys[index]
            score = int(round(raw_score))

            # Threshold of 90%
            if score >= FUZZY_MATCH_THRESHOLD:
                # If strict match is enabled, we only accept 100% score (same tokens)
                if strict_match and score < 100:
                    logger.debug(
                        f"Fuzzy match '{best_norm_match}' ignored due to strict matching policy (score: {score})"
                    )
                    self._stats["strict_rejected"] += 1
                else:
                    original_name = self._last_by_norm[best_norm_match]
                    logger.info(
                        f"Fuzzy match found: '{name}' matches '{original_name}' (score: {score})"
                    )
                    person = self._persons_cache[original_name]
                    self._cache_name(name, person)
                    self._register_email(email, person)
                    self._stats["fuzzy"] += 1
                    return person

        # 4. Create new person (if no match found)
        try:
            emails = [email] if email else []
            person = self.person_controller.create_person(name=name, emails=emails)
            self._cache_name(name, person)
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
            self._stats["created"] += 1
            return person
        except Exception as e:
            self._stats["create_failed"] += 1
            logger.warning(f"Failed to create person '{name}': {e}")
            return None
