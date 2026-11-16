import hashlib
import hmac
import json
import os
import re

import pytest

from src.core.logic.pii_anonymizer import (
    PII_COLUMN_REGISTRY,
    _hmac_hex,
    anonymize_cpf,
    anonymize_email,
    anonymize_field,
    anonymize_person_data,
    anonymize_phone,
    is_anonymized_cpf,
    is_anonymized_email,
    is_anonymized_phone,
    is_anonymized_text,
    key_fingerprint,
    keyed_export_hash,
    scan_text,
    scrub_emails_from_text,
    scrub_phones_from_text,
    scrub_pii_deep,
    scrub_pii_text,
    scrub_source_record_payload,
    scrub_source_record_phones,
)

TEST_KEY = "test-only-horizon-pii-hmac-key"

# Force a deterministic key so expected-token assertions stay stable
# regardless of machine-local .env values.
os.environ["HORIZON_PII_HMAC_KEY"] = TEST_KEY


def _expected_hmac(domain: str, value: str) -> str:
    """Independent RFC 5869 HKDF-SHA256 + HMAC-SHA256 oracle for tests.

    Deliberately re-implements the keyed derivation here instead of reusing
    module internals, so the test verifies the wiring (domain label, key
    loading, truncation) rather than trusting the implementation under test.
    """
    prk = hmac.new(b"\x00" * 32, TEST_KEY.encode("utf-8"), hashlib.sha256).digest()
    subkey = hmac.new(prk, domain.encode("utf-8") + b"\x01", hashlib.sha256).digest()
    return hmac.new(subkey, value.encode("utf-8"), hashlib.sha256).hexdigest()


# --- anonymize_cpf ---


def test_anonymize_cpf_returns_lgpd_prefix():
    result = anonymize_cpf("12345678901")
    assert result.startswith("LGPD-")


def test_anonymize_cpf_deterministic():
    assert anonymize_cpf("12345678901") == anonymize_cpf("12345678901")


def test_anonymize_cpf_different_inputs_produce_different_hashes():
    assert anonymize_cpf("11111111111") != anonymize_cpf("22222222222")


def test_anonymize_cpf_correct_format():
    value = "12345678901"
    expected = f"LGPD-{_expected_hmac('cpf', value)[:16]}"
    assert anonymize_cpf(value) == expected


def test_anonymize_cpf_none_returns_none():
    assert anonymize_cpf(None) is None


def test_anonymize_cpf_empty_string_returns_none():
    assert anonymize_cpf("") is None


def test_anonymize_cpf_invalid_cpf_still_anonymized():
    result = anonymize_cpf("000.000.000-00")
    assert result is not None
    assert result.startswith("LGPD-")


# --- anonymize_email ---


def test_anonymize_email_returns_anon_lgpd_suffix():
    result = anonymize_email("user@example.com")
    assert result.endswith("@anon.lgpd")


def test_anonymize_email_deterministic():
    assert anonymize_email("user@example.com") == anonymize_email("user@example.com")


def test_anonymize_email_different_inputs_differ():
    assert anonymize_email("a@b.com") != anonymize_email("c@d.com")


def test_anonymize_email_correct_format():
    value = "user@example.com"
    expected = f"{_expected_hmac('email', value)[:12]}@anon.lgpd"
    assert anonymize_email(value) == expected


def test_anonymize_email_none_returns_none():
    assert anonymize_email(None) is None


def test_anonymize_email_empty_string_returns_none():
    assert anonymize_email("") is None


# --- anonymize_field ---


def test_anonymize_field_cpf():
    result = anonymize_field("12345678901", "cpf")
    assert result.startswith("LGPD-")


def test_anonymize_field_email():
    result = anonymize_field("user@example.com", "email")
    assert result.endswith("@anon.lgpd")


def test_anonymize_field_unknown_type_passthrough():
    assert anonymize_field("anything", "whatever") == "anything"


def test_anonymize_field_phone_masks_value():
    result = anonymize_field("(27) 99959-5708", "phone")
    assert result.startswith("LGPD-PHONE-")


def test_anonymize_field_free_text_scrubs_emails_and_phones():
    result = anonymize_field("C x@y.com (27) 99999-0000", "free_text")
    assert "@anon.lgpd" in result
    assert "LGPD-PHONE-" in result


# --- anonymize_person_data ---


def test_anonymize_person_data_masks_identification_id():
    result = anonymize_person_data(
        {"identification_id": "12345678901", "name": "Alice"}
    )
    assert result["identification_id"].startswith("LGPD-")
    assert result["name"] == "Alice"


def test_anonymize_person_data_masks_email():
    result = anonymize_person_data({"email": "alice@example.com"})
    assert result["email"].endswith("@anon.lgpd")


def test_anonymize_person_data_masks_contact_email():
    result = anonymize_person_data({"contact_email": "boss@example.com"})
    assert result["contact_email"].endswith("@anon.lgpd")


def test_anonymize_person_data_leaves_non_pii_keys_unchanged():
    data = {"name": "Alice", "campus": "Serra"}
    assert anonymize_person_data(data) == data


def test_anonymize_person_data_handles_none_pii_values():
    result = anonymize_person_data({"identification_id": None, "email": None})
    assert result["identification_id"] is None
    assert result["email"] is None


def test_anonymize_person_data_returns_new_dict():
    original = {"identification_id": "123"}
    result = anonymize_person_data(original)
    assert result is not original


def test_anonymize_person_data_all_registry_keys_masked():
    data = {col: "test-value" for col in PII_COLUMN_REGISTRY}
    result = anonymize_person_data(data)
    for col, field_type in PII_COLUMN_REGISTRY.items():
        if field_type == "cpf":
            assert result[col].startswith("LGPD-")
        elif field_type == "email":
            assert result[col].endswith("@anon.lgpd")


# --- is_anonymized_cpf ---


def test_is_anonymized_cpf_true_for_lgpd_prefix():
    assert is_anonymized_cpf("LGPD-abc123")


def test_is_anonymized_cpf_false_for_raw():
    assert not is_anonymized_cpf("12345678901")


def test_is_anonymized_cpf_false_for_none():
    assert not is_anonymized_cpf(None)


# --- is_anonymized_email ---


def test_is_anonymized_email_true_for_anon_lgpd():
    assert is_anonymized_email("abc123@anon.lgpd")


def test_is_anonymized_email_false_for_raw():
    assert not is_anonymized_email("user@example.com")


def test_is_anonymized_email_false_for_none():
    assert not is_anonymized_email(None)


# --- anonymize_phone ---


def test_anonymize_phone_returns_lgpd_phone_prefix():
    result = anonymize_phone("(27) 99959-5708")
    assert result.startswith("LGPD-PHONE-")


def test_anonymize_phone_deterministic():
    assert anonymize_phone("27999595708") == anonymize_phone("27999595708")


def test_anonymize_phone_uses_distinct_salt_from_cpf():
    value = "27999595708"
    assert anonymize_phone(value) != anonymize_cpf(value)


def test_anonymize_phone_double_is_idempotent():
    first = anonymize_phone("(27) 99959-5708")
    assert anonymize_phone(first) == first
    assert is_anonymized_phone(first)


def test_anonymize_phone_none_returns_none():
    assert anonymize_phone(None) is None


# --- is_anonymized_phone ---


def test_is_anonymized_phone_true_for_lgpd_phone_prefix():
    assert is_anonymized_phone("LGPD-PHONE-abc")


def test_is_anonymized_phone_false_for_raw():
    assert not is_anonymized_phone("(27) 99959-5708")


def test_is_anonymized_phone_false_for_cpf_token():
    assert not is_anonymized_phone("LGPD-abc")


# --- scrub_phones_from_text ---


def test_scrub_phones_from_text_masks_area_code_number():
    text = "Contato: (27) 99959-5708 ou (27)3182-9200"
    result = scrub_phones_from_text(text)
    assert "(27) 99959-5708" not in result
    assert "(27)3182-9200" not in result
    assert result.count("LGPD-PHONE-") == 2


def test_scrub_phones_from_text_masks_plus55_number():
    result = scrub_phones_from_text("WhatsApp +55 27 99959 5708")
    assert "99959 5708" not in result
    assert "LGPD-PHONE-" in result


def test_scrub_phones_from_text_ignores_page_ranges_and_years():
    text = "pages 1601-1625 e ano 2020-2024"
    assert scrub_phones_from_text(text) == text


def test_scrub_phones_from_text_ignores_patent_number():
    text = "depósito de patente: INPI BR 10 20170091872"
    assert scrub_phones_from_text(text) == text


def test_scrub_phones_from_text_preserves_already_anonymized():
    text = "fone LGPD-PHONE-abc123 anon"
    assert scrub_phones_from_text(text) == text


def test_scrub_phones_from_text_none_returns_none():
    assert scrub_phones_from_text(None) is None


# --- scrub_pii_text ---


def test_scrub_pii_text_masks_email_and_phone():
    text = "E-mail: thebas@ifes.edu.br (27) 99959-5708 (Texto informado pelo autor)"
    result = scrub_pii_text(text)
    assert "thebas@ifes.edu.br" not in result
    assert "(27) 99959-5708" not in result
    assert "@anon.lgpd" in result
    assert "LGPD-PHONE-" in result


def test_scrub_pii_text_is_idempotent():
    text = "thebas@ifes.edu.br (27) 99959-5708"
    once = scrub_pii_text(text)
    assert scrub_pii_text(once) == once


# --- is_anonymized_text ---


def test_is_anonymized_text_false_with_raw_email():
    assert not is_anonymized_text("contact thebas@ifes.edu.br now")


def test_is_anonymized_text_false_with_raw_phone():
    assert not is_anonymized_text("phone (27) 99959-5708")


def test_is_anonymized_text_true_when_clean():
    assert is_anonymized_text("bio texto sem pii")


def test_is_anonymized_text_true_when_already_anonymized():
    text = "e9a7de842471@anon.lgpd LGPD-PHONE-abc123"
    assert is_anonymized_text(text)


def test_is_anonymized_text_none_or_empty_is_true():
    assert is_anonymized_text(None)
    assert is_anonymized_text("")


# --- is_anonymized_email ---


# --- idempotency ---


def test_double_anonymize_cpf_is_idempotent():
    first = anonymize_cpf("12345678901")
    second = anonymize_cpf(first)
    assert first == second
    assert is_anonymized_cpf(first)


def test_double_anonymize_email_is_idempotent():
    first = anonymize_email("user@example.com")
    second = anonymize_email(first)
    assert first == second


def test_anonymize_person_data_already_anonymized_cpf_is_stable():
    anon = anonymize_cpf("12345678901")
    result = anonymize_person_data({"identification_id": anon})
    assert result["identification_id"] == anon


# --- scrub_emails_from_text ---


def test_scrub_emails_from_text_replaces_email():
    result = scrub_emails_from_text("Contact: user@example.com for details.")
    assert "user@example.com" not in result
    assert "@anon.lgpd" in result


def test_scrub_emails_from_text_replaces_multiple_emails():
    text = "a@b.com and c@d.com"
    result = scrub_emails_from_text(text)
    assert "a@b.com" not in result
    assert "c@d.com" not in result
    assert result.count("@anon.lgpd") == 2


def test_scrub_emails_from_text_preserves_anon_lgpd():
    text = "already abc123456789@anon.lgpd done"
    assert scrub_emails_from_text(text) == text


def test_scrub_emails_from_text_no_email_unchanged():
    text = "nothing to scrub here"
    assert scrub_emails_from_text(text) == text


def test_scrub_emails_from_text_none_returns_none():
    assert scrub_emails_from_text(None) is None


def test_scrub_emails_from_text_lideres_pattern():
    text = " Carlos Campos (carlosr@ifes.edu.br), Maria Alice (mariaalice@ifes.edu.br)"
    result = scrub_emails_from_text(text)
    assert "carlosr@ifes.edu.br" not in result
    assert "mariaalice@ifes.edu.br" not in result
    assert "Carlos Campos" in result
    assert "Maria Alice" in result


# --- scrub_pii_deep ---


def test_scrub_pii_deep_string():
    result = scrub_pii_deep("email: foo@bar.com")
    assert "foo@bar.com" not in result
    assert "@anon.lgpd" in result


def test_scrub_pii_deep_dict():
    data = {"OrientadorEmail": "prof@ifes.edu.br", "name": "João"}
    result = scrub_pii_deep(data)
    assert "prof@ifes.edu.br" not in result["OrientadorEmail"]
    assert result["OrientadorEmail"].endswith("@anon.lgpd")
    assert result["name"] == "João"


def test_scrub_pii_deep_nested_dict():
    data = {"changes": [{"after": '{"resume": "bio text user@x.com end"}'}]}
    result = scrub_pii_deep(data)
    assert "user@x.com" not in result["changes"][0]["after"]
    assert "@anon.lgpd" in result["changes"][0]["after"]


def test_scrub_pii_deep_list():
    data = ["a@b.com", "no email", "c@d.com"]
    result = scrub_pii_deep(data)
    assert all("@anon.lgpd" in r or r == "no email" for r in result)


def test_scrub_pii_deep_non_string_passthrough():
    assert scrub_pii_deep(42) == 42
    assert scrub_pii_deep(None) is None
    assert scrub_pii_deep(3.14) == 3.14


def test_scrub_pii_deep_preserves_anon_lgpd():
    data = {"email": "abc123456789@anon.lgpd"}
    assert scrub_pii_deep(data) == data


# --- scrub_source_record_phones ---


def test_scrub_source_record_phones_nulls_celular_orientador():
    payload = {"CelularOrientador": "27988281460", "name": "Test"}
    result = scrub_source_record_phones(payload)
    assert result["CelularOrientador"] is None
    assert result["name"] == "Test"


def test_scrub_source_record_phones_nulls_celular_orientado():
    payload = {"CelularOrientado": "27999215433"}
    result = scrub_source_record_phones(payload)
    assert result["CelularOrientado"] is None


def test_scrub_source_record_phones_missing_fields_safe():
    payload = {"OrientadorEmail": "x@anon.lgpd"}
    result = scrub_source_record_phones(payload)
    assert result == payload


def test_scrub_source_record_phones_returns_new_dict():
    payload = {"CelularOrientador": "123"}
    result = scrub_source_record_phones(payload)
    assert result is not payload


def test_scrub_source_record_phones_nulls_nested_endereco_contato():
    payload = {
        "endereco_contato": {
            "logradouro": "Avenida Sabiás",
            "numero": "330",
            "cep": "29166630",
            "telefone": "(27) 3182-9200",
            "fax": "(27) 3182-9201",
        }
    }
    result = scrub_source_record_phones(payload)
    endereco = result["endereco_contato"]
    assert endereco["telefone"] is None
    assert endereco["fax"] is None
    assert endereco["logradouro"] == "Avenida Sabiás"
    assert endereco["numero"] == "330"
    assert endereco["cep"] == "29166630"


def test_scrub_source_record_phones_recurses_into_lists():
    payload = {
        "contatos": [{"telefone": "(27) 99959-5708"}, {"nome": "A"}],
        "fax": "123",
    }
    result = scrub_source_record_phones(payload)
    assert result["contatos"][0]["telefone"] is None
    assert result["contatos"][1]["nome"] == "A"
    assert result["fax"] is None


# --- scrub_source_record_payload ---


def test_scrub_source_record_payload_anonymizes_numeric_cpf():
    payload = {"OrientadoCpf": 13601552795, "Orientado": "Fulano"}
    result = scrub_source_record_payload(payload)
    assert result["OrientadoCpf"] == anonymize_cpf("13601552795")
    assert result["Orientado"] == "Fulano"


def test_scrub_source_record_payload_nulls_phones_and_scrubs_emails():
    payload = {
        "CelularOrientado": "27 99999-0000",
        "OrientadoEmail": "aluno@ifes.edu.br",
    }
    result = scrub_source_record_payload(payload)
    assert result["CelularOrientado"] is None
    assert result["OrientadoEmail"].endswith("@anon.lgpd")


def test_scrub_source_record_payload_is_idempotent():
    payload = {"OrientadoCpf": 13601552795, "OrientadoEmail": "aluno@ifes.edu.br"}
    once = scrub_source_record_payload(payload)
    twice = scrub_source_record_payload(once)
    assert once == twice


def test_scrub_source_record_payload_sanitizes_cnpq_endereco_contato():
    payload = {
        "endereco_contato": {
            "bairro": "Morada de Laranjeiras",
            "cep": "29166630",
            "logradouro": "Avenida Sabiás",
            "telefone": "(27) 99959-5708",
            "fax": "(27) 3182-9201",
        },
        "email": "grupo@ifes.edu.br",
    }
    result = scrub_source_record_payload(payload)
    endereco = result["endereco_contato"]
    assert endereco["telefone"] is None
    assert endereco["fax"] is None
    assert endereco["logradouro"] == "Avenida Sabiás"
    assert result["email"].endswith("@anon.lgpd")


def test_scrub_pii_deep_masks_phone_in_text():
    result = scrub_pii_deep("tel (27) 99959-5708 e page 1601-1625")
    assert "(27) 99959-5708" not in result
    assert "1601-1625" in result


def test_scrub_source_record_payload_non_dict_passthrough():
    assert scrub_source_record_payload(["a@b.com"]) == [anonymize_email("a@b.com")]
    assert scrub_source_record_payload(None) is None


# --- keyed HMAC security properties (2026-09-21 security review) ---


def test_hkdf_matches_rfc5869_test_case_3():
    """HKDF-SHA256 against the official RFC 5869 Test Case 3 vector.

    TC3 uses zero-length salt/info: "salt not provided" defaults to HashLen
    zero octets — exactly the salt our implementation uses. L=32 <= HashLen,
    so a single-block expand suffices.
    """
    from src.core.logic.pii_anonymizer import _hkdf_sha256

    ikm = b"\x0b" * 22
    okm = _hkdf_sha256(ikm, b"", length=32)
    assert okm.hex() == (
        "8da4e775a563c18f715f802a063c5a31" "b8a11f5c5ee1879ec3454e5f3c738d2d"
    )


def test_anonymize_cpf_known_answer():
    """Pins the full keyed pipeline (key → HKDF → HMAC → truncation)."""
    assert anonymize_cpf("12345678901") == "LGPD-f3315dc948810753"


def test_anonymize_email_known_answer():
    assert anonymize_email("user@example.com") == "8ee2d0066628@anon.lgpd"


def test_anonymize_phone_correct_format():
    value = "(27) 99959-5708"
    expected = f"LGPD-PHONE-{_expected_hmac('phone', value)[:16]}"
    assert anonymize_phone(value) == expected


def test_anonymize_phone_known_answer():
    assert anonymize_phone("(27) 99959-5708") == "LGPD-PHONE-50b7964c71b98d59"


def test_domain_separation_same_value_different_fields():
    """The same string must not tokenize identically across PII field types."""
    value = "27999595708"
    assert _hmac_hex("cpf", value) != _hmac_hex("email", value)
    assert _hmac_hex("cpf", value) != _hmac_hex("phone", value)
    assert _hmac_hex("email", value) != _hmac_hex("phone", value)


def test_missing_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("HORIZON_PII_HMAC_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HORIZON_PII_HMAC_KEY"):
        anonymize_cpf("12345678901")


def test_blank_key_raises_runtime_error(monkeypatch):
    monkeypatch.setenv("HORIZON_PII_HMAC_KEY", "   ")
    with pytest.raises(RuntimeError):
        anonymize_email("user@example.com")


def test_different_key_produces_different_tokens(monkeypatch):
    first = anonymize_cpf("12345678901")
    monkeypatch.setenv("HORIZON_PII_HMAC_KEY", "another-test-key")
    second = anonymize_cpf("12345678901")
    assert first != second
    assert second.startswith("LGPD-")


# --- Spec 029: CPF in text, scan_text, keyed export hash, key fingerprint ---

_FAKE_CPF = "000.000.000-00"


def test_scrub_pii_text_replaces_formatted_cpf_only():
    hex_hash = "a" * 20 + "12345678901" + "b" * 1
    text = f"CPF {_FAKE_CPF} ok; hash {hex_hash}; bare 12345678901."

    result = scrub_pii_text(text)

    assert _FAKE_CPF not in result
    assert "LGPD-" in result
    assert hex_hash in result
    assert "bare 12345678901." in result


def test_scan_text_replaces_email_phone_and_cpf_with_counts():
    text = f"mail person@example.test fone +55 00 00000-0000 cpf {_FAKE_CPF}"

    cleaned, counts = scan_text(text)

    assert "person@example.test" not in cleaned
    assert "+55 00 00000-0000" not in cleaned
    assert _FAKE_CPF not in cleaned
    assert set(counts) == {"email", "phone", "cpf", "known_field"}
    assert counts["email"] == 1
    assert counts["phone"] == 1
    assert counts["cpf"] == 1
    assert counts["known_field"] == 0


def test_scan_text_tokenizes_known_json_fields_string_and_number():
    text = (
        '{"OrientadoEmail": "not-an-address", "OrientadorEmail": "x", '
        '"email": "bad", "contact_email": "bad2", '
        '"OrientadoCpf": 12345678901, "OrientadorCpf": "12345678901", '
        '"identification_id": "abc", "telefone": "12 3456", "celular": 99000000000}'
    )

    cleaned, counts = scan_text(text)
    data = json.loads(cleaned)

    assert counts["known_field"] == 9
    assert data["OrientadoEmail"].endswith("@anon.lgpd")
    assert data["email"].endswith("@anon.lgpd")
    assert data["contact_email"].endswith("@anon.lgpd")
    assert data["OrientadoCpf"].startswith("LGPD-")
    assert data["identification_id"].startswith("LGPD-")
    assert data["telefone"].startswith("LGPD-PHONE-")
    assert data["celular"].startswith("LGPD-PHONE-")


def test_scan_text_leaves_tokens_and_null_alone():
    text = (
        '{"email": "abcdef012345@anon.lgpd", "OrientadoCpf": "LGPD-0123456789abcdef",'
        ' "telefone": "LGPD-PHONE-0123456789abcdef", "fax": null, "phone": null}'
    )

    cleaned, counts = scan_text(text)

    assert cleaned == text
    assert sum(counts.values()) == 0


def test_scan_text_is_idempotent():
    text = f'{{"email": "bad", "note": "person@example.test {_FAKE_CPF}"}}'

    once, _ = scan_text(text)
    twice, counts = scan_text(once)

    assert twice == once
    assert sum(counts.values()) == 0


def test_scan_text_never_alters_hash_values():
    text = (
        '{"payload_hash": "12345678901234567890123456789012", '
        '"value_hash": "00000000000000000000000000000000", '
        '"content_hash": "11111111111111111111111111111111"}'
    )

    cleaned, counts = scan_text(text)

    assert cleaned == text
    assert sum(counts.values()) == 0


def test_scan_text_keeps_at_sign_in_journal_names():
    text = "J. Chem. @ 2020"

    zero = {"email": 0, "phone": 0, "cpf": 0, "known_field": 0}
    assert scan_text(text) == (text, zero)


def test_keyed_export_hash_is_deterministic_and_keyed(monkeypatch):
    first = keyed_export_hash("abc")

    assert first == keyed_export_hash("abc")
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first != "abc"
    assert first != hashlib.sha256(b"abc").hexdigest()

    monkeypatch.setenv("HORIZON_PII_HMAC_KEY", "another-key-for-the-test")
    assert keyed_export_hash("abc") != first


def test_key_fingerprint_is_short_stable_and_keyed(monkeypatch):
    first = key_fingerprint()

    assert re.fullmatch(r"[0-9a-f]{16}", first)
    assert first == key_fingerprint()
    assert TEST_KEY not in first

    monkeypatch.setenv("HORIZON_PII_HMAC_KEY", "another-key-for-the-test")
    assert key_fingerprint() != first


def test_scan_text_leaves_short_numbers_in_known_fields_alone():
    """Our own reports hold counts under keys such as "email"."""
    text = '{"file_bytes_hits": {"email": 0, "phone": 2, "cpf": 1}, "email": 12}'

    cleaned, counts = scan_text(text)

    assert cleaned == text
    assert sum(counts.values()) == 0
