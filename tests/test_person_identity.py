"""Contract tests for the shared participant-name key function.

Pins contract R7 (single shared normalization) and R13 (junk names). The
spelling table is Scenario B of data-model.md.
"""

from src.core.logic.person_identity import is_junk_name, normalize_participant_name

SPELLING_PAIRS = [
    ("Israel Magalhães do Carmo", "ISRAEL MAGALHAES do CARMO"),
    ("ISRAEL MAGALHÃES DO CARMO", "ISRAEL MAGALHAES do CARMO"),
    ("Gustavo Maia De Almeida", "GUSTAVO MAIA de ALMEIDA"),
    ("Gustavo Maia de Almeida", "GUSTAVO MAIA de ALMEIDA"),
    ("Maria-Aparecida Santos!", "MARIA APARECIDA SANTOS"),
    ("Maria Aparecida Santos", "MARIA APARECIDA SANTOS"),
    ("Paulo Sérgio Dos Santos Júnior", "PAULO SERGIO dos SANTOS JUNIOR"),
    ("PAULO SERGIO dos SANTOS JUNIOR", "PAULO SERGIO dos SANTOS JUNIOR"),
]


def test_spelling_variants_map_to_single_key():
    for raw, expected in SPELLING_PAIRS:
        assert normalize_participant_name(raw) == expected, raw


def test_equal_keys_for_case_whitespace_punctuation():
    assert normalize_participant_name("  Maria   Aparecida ") == "MARIA APARECIDA"
    assert normalize_participant_name("Roberto, Carlos Jr.") == "ROBERTO CARLOS JR"
    assert normalize_participant_name("roberto carlos jr") == "ROBERTO CARLOS JR"


def test_particles_e_and_y_are_canonicalized():
    assert (
        normalize_participant_name("Maria E Souza Y Cominho")
        == "MARIA e SOUZA y COMINHO"
    )


def test_jr_and_junior_share_one_key_under_suffix_canonicalization():
    jr = normalize_participant_name("Roberto Carlos Jr.", canonical_suffixes=True)
    junior = normalize_participant_name(
        "roberto carlos júnior", canonical_suffixes=True
    )
    full = normalize_participant_name("ROBERTO CARLOS JUNIOR", canonical_suffixes=True)
    assert jr == junior == full == "ROBERTO CARLOS JUNIOR"


def test_default_key_preserves_jr_spelling():
    assert normalize_participant_name("Roberto Carlos Jr.") == "ROBERTO CARLOS JR"


def test_particles_are_invisible_under_drop_particles():
    key = normalize_participant_name(
        "Paulo Sérgio Dos Santos", canonical_suffixes=True, drop_particles=True
    )
    assert (
        key
        == normalize_participant_name(
            "Paulo Sérgio Santos", canonical_suffixes=True, drop_particles=True
        )
        == "PAULO SERGIO SANTOS"
    )


def test_name_variant_trio_shares_one_invariant_key():
    trio = (
        "Paulo Sérgio Dos Santos Júnior",
        "Paulo Sérgio Santos Júnior",
        "Paulo Sérgio Santos Jr.",
    )
    keys = {
        normalize_participant_name(name, canonical_suffixes=True, drop_particles=True)
        for name in trio
    }
    assert keys == {"PAULO SERGIO SANTOS JUNIOR"}


def test_filho_and_junior_remain_distinct_generational_suffixes():
    assert normalize_participant_name(
        "José Alves Filho", canonical_suffixes=True
    ) != normalize_participant_name("José Alves Júnior", canonical_suffixes=True)


def test_drop_particles_removes_e_and_y_too():
    assert (
        normalize_participant_name("Maria E Souza Y Cominho", drop_particles=True)
        == "MARIA SOUZA COMINHO"
    )


def test_empty_and_none_produce_empty_key():
    assert normalize_participant_name("") == ""
    assert normalize_participant_name(None) == ""


def test_junk_names_are_flagged():
    for junk in ("Dr", "PROF", "Prof Dr", ""):
        assert is_junk_name(junk), junk


def test_real_names_are_not_junk():
    for name in (
        "Israel Magalhães do Carmo",
        "Maria E Souza",
        "Dr José da Silva",
        "Paulo Sérgio Dos Santos Júnior",
    ):
        assert not is_junk_name(name), name
