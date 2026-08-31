"""Tests for advisorship canonical program/provider/year resolution."""

from src.core.logic.advisorship_canonical_values import (
    SIGPESQ_SYSTEM,
    AdvisorshipCanonicalValues,
    AdvisorshipSourceInfo,
    load_advisorship_source_values,
    report_year_from_path,
    resolve_advisorship_canonical_values,
)
import json


def _sigpesq_record(
    adv_id,
    rec_id,
    programa=None,
    ag_financiadora=None,
    ano=None,
    year_dir=None,
):
    payload = {}
    if programa is not None:
        payload["Programa"] = programa
    if ag_financiadora is not None:
        payload["AgFinanciadora"] = ag_financiadora
    if ano is not None:
        payload["Ano"] = ano
    path = (
        f"data/raw/sigpesq/advisorships/{year_dir}/Relatorio_29_08_2026.xlsx"
        if year_dir is not None
        else None
    )
    return AdvisorshipSourceInfo(
        advisorship_id=adv_id,
        source_record_id=rec_id,
        source_system=SIGPESQ_SYSTEM,
        source_path=path,
        payload=payload,
    )


def _lattes_record(adv_id, rec_id, year=None):
    payload = {}
    if year is not None:
        payload["year"] = year
    return AdvisorshipSourceInfo(
        advisorship_id=adv_id,
        source_record_id=rec_id,
        source_system="lattes_advisorships",
        source_path="/data/lattes_json/01_X.json",
        payload=payload,
    )


# --------------------------------------------------------------------------
# report_year_from_path
# --------------------------------------------------------------------------


def test_report_year_from_path_extracts_report_directory_year():
    assert (
        report_year_from_path(
            "data/raw/sigpesq/advisorships/2016/Relatorio_29_08_2026.xlsx"
        )
        == 2016
    )
    assert (
        report_year_from_path("data/raw/sigpesq/advisorships/2025/relatorio.xlsx")
        == 2025
    )


def test_report_year_from_path_returns_none_without_matching_directory():
    assert report_year_from_path("data/lattes_json/01_pessoa.json") is None
    assert report_year_from_path(None) is None
    assert report_year_from_path("") is None


# --------------------------------------------------------------------------
# load_advisorship_source_values
# --------------------------------------------------------------------------


class _Row:
    def __init__(self, mapping):
        self._mapping = mapping


def test_load_advisorship_source_values_groups_records_by_advisorship_id():
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            assert "entity_matches" in getattr(statement, "text", "")
            assert "canonical_entity_type = 'advisorship'" in getattr(
                statement, "text", ""
            )
            return FakeResult(
                [
                    _Row(
                        {
                            "advisorship_id": 86,
                            "source_record_id": 5,
                            "source_system": SIGPESQ_SYSTEM,
                            "source_path": "data/raw/sigpesq/advisorships/2016/R.xlsx",
                            "raw_payload_json": json.dumps(
                                {
                                    "Programa": "Pivic",
                                    "AgFinanciadora": "Voluntário",
                                    "Ano": 2016,
                                }
                            ),
                        }
                    ),
                    _Row(
                        {
                            "advisorship_id": 86,
                            "source_record_id": 9,
                            "source_system": "lattes_advisorships",
                            "source_path": "data/lattes_json/01_X.json",
                            "raw_payload_json": json.dumps({"year": 2015}),
                        }
                    ),
                ]
            )

    grouped = load_advisorship_source_values(FakeSession())

    assert list(grouped.keys()) == [86]
    assert [r.source_record_id for r in grouped[86]] == [5, 9]
    assert grouped[86][0].payload["Programa"] == "Pivic"
    assert grouped[86][1].payload["year"] == 2015


def test_load_advisorship_source_values_handles_blank_payload():
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            return FakeResult(
                [
                    _Row(
                        {
                            "advisorship_id": 3,
                            "source_record_id": 1,
                            "source_system": SIGPESQ_SYSTEM,
                            "source_path": "data/raw/sigpesq/advisorships/2020/R.xlsx",
                            "raw_payload_json": None,
                        }
                    )
                ]
            )

    grouped = load_advisorship_source_values(FakeSession())
    assert grouped[3][0].payload == {}


# --------------------------------------------------------------------------
# resolve_advisorship_canonical_values — program/provider/year
# --------------------------------------------------------------------------


def test_resolve_uses_report_spelled_program_and_provider_from_sigpesq_row():
    values = resolve_advisorship_canonical_values(
        [
            _sigpesq_record(
                86,
                1,
                programa="Pivic",
                ag_financiadora="Voluntário",
                ano=2016,
                year_dir=2016,
            )
        ]
    )
    assert isinstance(values, AdvisorshipCanonicalValues)
    assert values.year == 2016
    assert values.program == "Pivic"
    assert values.provider == "Voluntário"


def test_resolve_uses_report_directory_year_over_inicio_fim_span():
    values = resolve_advisorship_canonical_values(
        [
            _sigpesq_record(
                1,
                1,
                programa="Pibic",
                ag_financiadora="Fapes",
                ano=2016,
                year_dir=2016,
            )
        ]
    )
    assert values.year == 2016


def test_resolve_trims_whitespace_and_returns_none_for_blanks():
    values = resolve_advisorship_canonical_values(
        [
            _sigpesq_record(
                1,
                1,
                programa="  Pibic  ",
                ag_financiadora="   ",
                ano=2016,
                year_dir=2016,
            )
        ]
    )
    assert values.program == "Pibic"
    assert values.provider is None


def test_resolve_year_uses_ano_to_break_ties_across_report_directories():
    records = [
        _sigpesq_record(
            4882, 10, programa="Pibic", ag_financiadora="Fapes", ano=2021, year_dir=2021
        ),
        _sigpesq_record(
            4882, 11, programa="Pibic", ag_financiadora="Fapes", ano=2021, year_dir=2022
        ),
    ]
    values = resolve_advisorship_canonical_values(records)
    assert values.year == 2021


def test_resolve_year_falls_back_to_most_recent_directory_year():
    records = [
        _sigpesq_record(
            7, 20, programa="Pibic", ag_financiadora="Ifes", ano=2019, year_dir=2021
        ),
        _sigpesq_record(
            7, 21, programa="Pibic", ag_financiadora="Ifes", ano=2019, year_dir=2022
        ),
    ]
    values = resolve_advisorship_canonical_values(records)
    assert values.year == 2022


def test_resolve_year_prefers_exact_dir_year_when_no_ano_match():
    records = [
        _sigpesq_record(
            8, 30, programa="Pibic", ag_financiadora="Fapes", ano=2020, year_dir=2021
        ),
        _sigpesq_record(
            8, 31, programa="Pibic", ag_financiadora="Fapes", ano=2020, year_dir=2020
        ),
    ]
    values = resolve_advisorship_canonical_values(records)
    assert values.year == 2020


def test_resolve_same_workplan_across_report_dirs_yields_per_row_years():
    values_2016 = resolve_advisorship_canonical_values(
        [_sigpesq_record(5, 1, programa="Pivic", ano=2016, year_dir=2016)]
    )
    values_2025 = resolve_advisorship_canonical_values(
        [_sigpesq_record(6, 1, programa="Pivic", ano=2025, year_dir=2025)]
    )
    assert values_2016.year == 2016
    assert values_2025.year == 2025


def test_resolve_dir_year_wins_when_payload_has_only_inicio_fim_span():
    record = _sigpesq_record(
        4, 5, programa="Pibic", ag_financiadora="Fapes", year_dir=2016
    )
    record.payload["Inicio"] = "2016-09-26"
    record.payload["Fim"] = "2017-07-31"
    values = resolve_advisorship_canonical_values([record])
    assert values.year == 2016


def test_resolve_ties_break_deterministically_by_lowest_source_record_id():
    records = [
        _sigpesq_record(
            3, 11, programa="Pivic", ag_financiadora="Fapes", ano=2021, year_dir=2021
        ),
        _sigpesq_record(
            3, 10, programa="Pibic", ag_financiadora="Fapes", ano=2021, year_dir=2021
        ),
    ]
    values = resolve_advisorship_canonical_values(records)
    assert values.program == "Pibic"
    assert values.year == 2021


def test_resolve_lattes_rows_yield_null_program_provider_and_cv_year():
    values = resolve_advisorship_canonical_values([_lattes_record(3, 40, year=2015)])
    assert values.year == 2015
    assert values.program is None
    assert values.provider is None


def test_non_null_category_traces_to_sigpesq_record_with_report_path():
    import re

    records = [
        _sigpesq_record(
            14,
            60,
            programa="Pivic",
            ag_financiadora="FAPES",
            ano=2023,
            year_dir=2023,
        ),
        _lattes_record(14, 61, year=2015),
    ]
    values = resolve_advisorship_canonical_values(records)
    assert values.program == "Pivic"
    assert values.provider == "FAPES"

    for record in records:
        if record.source_system == SIGPESQ_SYSTEM and record.payload.get("Ano"):
            assert re.match(
                r"^data/raw/sigpesq/advisorships/\d{4}/", record.source_path
            )
            assert record.source_record_id == 60
            assert record.source_path.startswith(
                f"data/raw/sigpesq/advisorships/{values.year}/"
            )
    assert all(
        r.source_system != SIGPESQ_SYSTEM or r.payload.get("Ano") for r in records
    )


def test_category_resolution_is_only_backed_by_sigpesq_report_rows():
    values = resolve_advisorship_canonical_values(
        [
            _lattes_record(15, 70, year=2019),
            _sigpesq_record(
                15,
                71,
                programa="Pivic",
                ag_financiadora="FAPES",
                ano=2019,
                year_dir=2019,
            ),
        ]
    )
    assert values.program is not None
    assert values.source_record_id == 71


def test_resolve_empty_records_yields_all_null():
    values = resolve_advisorship_canonical_values([])
    assert values.year is None
    assert values.program is None
    assert values.provider is None


# --------------------------------------------------------------------------
# US2/Edge cases — cancelled/volunteer rows, same person multiple categories
# --------------------------------------------------------------------------


def test_resolve_cancelled_volunteer_row_still_carries_category():
    values = resolve_advisorship_canonical_values(
        [
            _sigpesq_record(
                9,
                50,
                programa="Pivic",
                ag_financiadora="Voluntário",
                ano=2016,
                year_dir=2016,
            )
        ]
    )
    assert values.program == "Pivic"
    assert values.provider == "Voluntário"
    assert values.year == 2016


def test_resolve_same_person_two_categorised_rows_stays_distinct():
    first = resolve_advisorship_canonical_values(
        [
            _sigpesq_record(
                100,
                60,
                programa="Pivic",
                ag_financiadora="Voluntário",
                ano=2016,
                year_dir=2016,
            )
        ]
    )
    second = resolve_advisorship_canonical_values(
        [
            _sigpesq_record(
                101,
                61,
                programa="Pibic",
                ag_financiadora="Fapes",
                ano=2020,
                year_dir=2020,
            )
        ]
    )
    assert first.program == "Pivic"
    assert first.provider == "Voluntário"
    assert second.program == "Pibic"
    assert second.provider == "Fapes"
    assert (first.year, second.year) == (2016, 2020)
