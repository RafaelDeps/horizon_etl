from datetime import datetime

from src.core.logic.initiative_identity import build_identity_key
from src.core.logic.strategies.sigpesq_advisorships import (
    SigPesqAdvisorshipMappingStrategy,
)


def test_sigpesq_advisorship_mapping():
    strategy = SigPesqAdvisorshipMappingStrategy()
    from research_domain.domain.entities import Advisorship

    # Sample row with final requested columns
    row = {
        "Orientado": "Fulano de Tal",
        "OrientadoEmail": "fulano@example.com",
        "Orientador": "Dr. Beltrano",
        "OrientadorEmail": "beltrano@example.com",
        "TituloPT": "Desenvolvimento de IA",
        "Inicio": "01/01/2026",
        "Fim": "31/12/2026",
        "Situacao": "Active",
        "Programa": "PIBIC",
        "Valor": 400.0,
        "agFinanciadora": "FAPES",
    }

    mapped = strategy.map_row(row)

    assert mapped["title"] == "Desenvolvimento de IA"
    assert mapped["coordinator_name"] == "Dr. Beltrano"
    assert mapped["coordinator_email"] == "beltrano@example.com"
    assert mapped["student_names"] == ["Fulano de Tal"]
    assert mapped["student_emails"] == ["fulano@example.com"]
    assert isinstance(mapped["start_date"], datetime)
    assert mapped["start_date"].year == 2026
    assert mapped["model_class"] == Advisorship
    assert mapped["fellowship_data"]["name"] == "PIBIC"
    assert mapped["fellowship_data"]["value"] == 400.0
    assert mapped["fellowship_data"]["sponsor_name"] == "FAPES"


def test_person_matcher_email_matching():
    from unittest.mock import MagicMock

    from eo_lib import Person

    person_ctrl = MagicMock()
    # Mocking person objects
    p1 = MagicMock(spec=Person)
    p1.name = "John Doe"
    p1.email = "john@example.com"
    p1.id = 1

    person_ctrl.get_all.return_value = [p1]

    from src.core.logic.person_matcher import PersonMatcher

    matcher = PersonMatcher(person_ctrl)
    matcher.preload_cache()

    # 1. Match by exact email
    matched = matcher.match_or_create("John Doe", email="JOHN@example.com")
    assert matched == p1
    assert person_ctrl.create_person.call_count == 0

    # 2. Match by name when email is different but name matches (exact normalized)
    matched_name = matcher.match_or_create("John Doe", email="other@example.com")
    assert matched_name == p1
    assert person_ctrl.create_person.call_count == 0

    # 3. Create new person when no match
    p2 = MagicMock(spec=Person)
    person_ctrl.create_person.return_value = p2
    new_person = matcher.match_or_create("Jane Doe", email="jane@example.com")
    # Should create new person with email
    person_ctrl.create_person.assert_called_once_with(
        name="Jane Doe", emails=["jane@example.com"]
    )


def test_sigpesq_advisorship_mapping_fellowship_flowship():
    strategy = SigPesqAdvisorshipMappingStrategy()

    # Verify that flowship fields are correctly mapped
    row = {
        "Orientado": "Student 1",
        "Orientador": "Sup 1",
        "TituloPT": "Proj 1",
        "Programa": "PIBITI",
        "Valor": 500.0,
    }
    mapped = strategy.map_row(row)
    assert mapped["fellowship_data"]["name"] == "PIBITI"
    assert mapped["fellowship_data"]["value"] == 500.0


def test_sigpesq_advisorship_mapping_uses_cancelado_as_advisorship_cancelled():
    strategy = SigPesqAdvisorshipMappingStrategy()

    row = {
        "Id": 10702,
        "CodPT": "PT     17516",
        "TituloPT": "Plano cancelado no SigPesq",
        "CodPJ": "PJ      8748",
        "TituloPJ": "Projeto pai",
        "Orientado": "Aluno Cancelado",
        "Orientador": "Docente Orientador",
        "Inicio": "01/08/2026",
        "Fim": "31/07/2027",
        "Programa": "PIVIC",
        "Valor": "0,00",
        "AgFinanciadora": "Voluntário",
        "Cancelado": True,
        "CanceladoPor": "Coordenacao",
    }

    mapped = strategy.map_row(row)

    assert mapped["cancelled"] is True
    assert mapped["cancellation_date"] is None
    assert mapped["status"] == "Cancelled"
    assert mapped["metadata"]["cancelled"] is True
    assert mapped["metadata"]["cancelled_by"] == "Coordenacao"


def test_sigpesq_advisorship_mapping_uses_sigpesq_codes_for_pt_pj_and_fellowship():
    strategy = SigPesqAdvisorshipMappingStrategy()

    row = {
        "Id": 10701,
        "CodPT": "PT     17515",
        "TituloPT": "Projeto estrutural de um modulo hidroponico",
        "CodPJ": "PJ      8748",
        "TituloPJ": "Desenvolvimento de um Modulo de Hidroponia Autonomo",
        "Orientado": "Aluno Bolsista",
        "OrientadoEmail": "aluno@example.org",
        "Orientador": "Docente Orientador",
        "OrientadorEmail": "docente@example.org",
        "Inicio": "01-08-26",
        "Programa": "Pibic",
        "Valor": "700,00",
        "AgFinanciadora": "FAPES",
    }

    mapped = strategy.map_row(row)

    assert mapped["title"] == "Projeto estrutural de um modulo hidroponico"
    assert (
        mapped["parent_title"] == "Desenvolvimento de um Modulo de Hidroponia Autonomo"
    )
    # A identidade inclui o Id da bolsa, e não só o código do plano de trabalho:
    # um mesmo CodPT pode ter bolsas consecutivas, com bolsistas e períodos
    # diferentes. Com a chave só do plano, duas bolsas colapsavam na mesma
    # identidade e a segunda tentava renomear a linha da primeira, batendo na
    # restrição de unicidade de `initiatives.name` e sendo descartada.
    assert mapped["identity_key"] == build_identity_key(
        ["sigpesq_workplan", "17515", "10701"]
    )
    assert mapped["parent_identity_key"] == build_identity_key(
        ["sigpesq_project", "8748"]
    )
    assert mapped["metadata"]["sigpesq_workplan_code"] == "17515"
    assert mapped["metadata"]["sigpesq_project_code"] == "8748"
    assert mapped["fellowship_data"]["sigpesq_workplan_code"] == "17515"
    assert mapped["fellowship_data"]["sigpesq_project_code"] == "8748"
    assert mapped["fellowship_data"]["sigpesq_id"] == 10701


def test_advisorship_and_fellowship_controllers():
    """Test that Advisorship and Fellowship controllers can be imported and instantiated."""
    from research_domain.controllers.controllers import (
        AdvisorshipController,
        FellowshipController,
    )

    adv_ctrl = AdvisorshipController()
    fel_ctrl = FellowshipController()

    assert adv_ctrl is not None
    assert fel_ctrl is not None
    assert hasattr(adv_ctrl, "create")
    assert hasattr(fel_ctrl, "create")
