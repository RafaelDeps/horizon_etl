import hashlib
import re
from typing import Any

SALT = b":horizon-lgpd-v1"
PHONE_SALT = b":horizon-lgpd-phone-v1"

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


def anonymize_cpf(value: str | None) -> str | None:
    if not value:
        return None
    if is_anonymized_cpf(value):
        # Idempotent: re-hashing an already-anonymized value on every ORM
        # flush makes the stored identity drift (hash-of-hash chains).
        return value
    digest = hashlib.sha256(value.encode("utf-8") + SALT).hexdigest()
    return f"LGPD-{digest[:16]}"


def anonymize_email(value: str | None) -> str | None:
    if not value:
        return None
    if is_anonymized_email(value):
        return value
    digest = hashlib.sha256(value.encode("utf-8") + SALT).hexdigest()
    return f"{digest[:12]}@anon.lgpd"


def anonymize_phone(value: str | None) -> str | None:
    if not value:
        return None
    if is_anonymized_phone(value):
        return value
    digest = hashlib.sha256(value.encode("utf-8") + PHONE_SALT).hexdigest()
    return f"LGPD-PHONE-{digest[:16]}"


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
