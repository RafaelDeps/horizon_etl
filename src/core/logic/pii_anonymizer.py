import hashlib
import hmac
import os
import re
from typing import Any

# Secret key for PII pseudonymization — private-key/public-key pattern.
# The private key is a secret environment variable (never committed); the
# algorithm, token formats and domain labels are public (Kerckhoffs).
HMAC_KEY_ENV = "HORIZON_PII_HMAC_KEY"

# Per-field domain labels — HKDF-derived subkeys keep the same string value
# from tokenizing identically across different PII field types.
_DOMAIN_CPF = "cpf"
_DOMAIN_EMAIL = "email"
_DOMAIN_PHONE = "phone"

PII_COLUMN_REGISTRY: dict[str, str] = {
    "identification_id": "cpf",
    "email": "email",
    "contact_email": "email",
    # Free text such as Lattes resumes can embed real e-mails and phone
    # numbers; mask them on write instead of hashing the whole field.
    "resume": "free_text",
}

# Structured phone fields in source-record payloads (top-level or nested,
# e.g. CNPq's ``endereco_contato.telefone``/``.fax``) — nulled on export.
_PAYLOAD_PHONE_FIELDS = frozenset(
    {"CelularOrientador", "CelularOrientado", "telefone", "fax", "phone", "celular"}
)

# Structured CPF fields in SigPesq advisorship payloads — values may be int.
_PAYLOAD_CPF_FIELDS = frozenset({"OrientadoCpf", "OrientadorCpf"})

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@(?!anon\.lgpd)[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Brazilian phone numbers in free text. An area code ("(27 …)") or an
# explicit "+55" country code is required so unambiguous patterns like a
# page range ("1601-1625") or a patent number ("BR 10 20170091872") are not
# treated as phone numbers.
_PHONE_RE = re.compile(
    r"\+55[\s-]?\(?\d{2}\)?[\s-]?\d{4,5}[\s-]?\d{4}"
    r"|\(\d{2,3}\)[\s-]?\d{4,5}[\s-]?\d{4}"
)


def _load_hmac_key() -> bytes:
    """Load the secret HMAC key from the environment.

    Hard-fails when the key is absent — silently falling back to an
    unkeyed/public hash would defeat the anonymization guarantees.
    """
    value = os.environ.get(HMAC_KEY_ENV)
    if value is None or not value.strip():
        raise RuntimeError(
            f"Missing required environment variable {HMAC_KEY_ENV!r}. "
            "Generate a secret with: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))" '
            "and store it in .env or a secret manager (never commit it)."
        )
    return value.strip().encode("utf-8")


def _hkdf_sha256(ikm: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-SHA256 (RFC 5869) for domain-separated subkeys.

    Single-block expand (length <= 32 bytes) is sufficient for HMAC keys.
    """
    prk = hmac.new(b"\x00" * 32, ikm, hashlib.sha256).digest()
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    return okm[:length]


_SUBKEY_CACHE: dict[tuple[bytes, str], bytes] = {}


def _domain_subkey(domain: str) -> bytes:
    """Derive (and cache) the per-field-type subkey from the master secret."""
    key = _load_hmac_key()
    cache_key = (key, domain)
    subkey = _SUBKEY_CACHE.get(cache_key)
    if subkey is None:
        subkey = _hkdf_sha256(key, domain.encode("utf-8"))
        _SUBKEY_CACHE[cache_key] = subkey
    return subkey


def _hmac_hex(domain: str, value: str) -> str:
    """Deterministic keyed digest: HMAC-SHA256(domain subkey, value)."""
    return hmac.new(
        _domain_subkey(domain), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def anonymize_cpf(value: str | None) -> str | None:
    if not value:
        return None
    if is_anonymized_cpf(value):
        # Idempotent: re-hashing an already-anonymized value on every ORM
        # flush makes the stored identity drift (hash-of-hash chains).
        return value
    return f"LGPD-{_hmac_hex(_DOMAIN_CPF, value)[:16]}"


def anonymize_email(value: str | None) -> str | None:
    if not value:
        return None
    if is_anonymized_email(value):
        return value
    return f"{_hmac_hex(_DOMAIN_EMAIL, value)[:12]}@anon.lgpd"


def anonymize_phone(value: str | None) -> str | None:
    if not value:
        return None
    if is_anonymized_phone(value):
        return value
    return f"LGPD-PHONE-{_hmac_hex(_DOMAIN_PHONE, value)[:16]}"


def anonymize_field(value: str | None, field_type: str) -> str | None:
    if field_type == "cpf":
        return anonymize_cpf(value)
    if field_type == "email":
        return anonymize_email(value)
    if field_type == "phone":
        return anonymize_phone(value)
    if field_type == "free_text":
        return scrub_pii_text(value)
    return value


def anonymize_person_data(data: dict) -> dict:
    result = dict(data)
    for column, field_type in PII_COLUMN_REGISTRY.items():
        if column in result:
            result[column] = anonymize_field(result[column], field_type)
    return result


def scrub_emails_from_text(text: str | None) -> str | None:
    """Replace every real email address in a free-text string with its anonymized hash."""
    if not text:
        return text
    return _EMAIL_RE.sub(lambda m: anonymize_email(m.group(0)), text)


def scrub_phones_from_text(text: str | None) -> str | None:
    """Replace unambiguous phone numbers (area code or +55) in free text."""
    if not text:
        return text
    return _PHONE_RE.sub(lambda m: anonymize_phone(m.group(0)), text)


def scrub_pii_text(text: str | None) -> str | None:
    """Scrub e-mails and phone numbers from a free-text string."""
    return scrub_phones_from_text(scrub_emails_from_text(text))


def scrub_pii_deep(value: Any) -> Any:
    """Recursively anonymize e-mails and phone numbers in any JSON-serializable value."""
    if isinstance(value, str):
        return scrub_pii_text(value)
    if isinstance(value, dict):
        return {k: scrub_pii_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_pii_deep(v) for v in value]
    return value


def scrub_source_record_phones(payload: dict) -> dict:
    """Null out phone number fields anywhere in a source-record payload dict.

    Handles both top-level SigPesq advisorship fields (``CelularOrientador``,
    ``CelularOrientado``) and nested phone keys such as the CNPq group
    ``endereco_contato`` ``telefone``/``fax``.
    """

    def _null_phones(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: (None if k in _PAYLOAD_PHONE_FIELDS else _null_phones(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_null_phones(v) for v in node]
        return node

    return _null_phones(payload)


def scrub_source_record_payload(payload: Any) -> Any:
    """Full PII scrub for a source-record payload: phones nulled, structured
    CPF fields anonymized (values may be numeric), emails inside any string
    anonymized. Safe on non-dict payloads."""
    if not isinstance(payload, dict):
        return scrub_pii_deep(payload)
    result = scrub_source_record_phones(payload)
    for field in _PAYLOAD_CPF_FIELDS:
        if result.get(field) is not None:
            result[field] = anonymize_cpf(str(result[field]))
    return scrub_pii_deep(result)


def is_anonymized_cpf(value: str | None) -> bool:
    return bool(value and value.startswith("LGPD-"))


def is_anonymized_phone(value: str | None) -> bool:
    return bool(value and value.startswith("LGPD-PHONE-"))


def is_anonymized_email(value: str | None) -> bool:
    return bool(value and value.endswith("@anon.lgpd"))


def is_anonymized_text(value: str | None) -> bool:
    """True when free text carries no raw e-mail or phone number."""
    if not value:
        return True
    return not _EMAIL_RE.search(value) and not _PHONE_RE.search(value)
