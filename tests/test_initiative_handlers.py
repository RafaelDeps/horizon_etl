from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

from research_domain.domain.entities import Advisorship

from src.core.logic.initiative_handlers import AdvisorshipHandler


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_advisorship_handler_creates_members_with_base_persons(
    MockAdvisorshipController,
    MockFellowshipController,
):
    initiative_controller = MagicMock()
    person_matcher = MagicMock()
    entity_manager = MagicMock()

    student_role = MagicMock()
    student_role.id = 1
    student_role.name = "Student"

    supervisor_role = MagicMock()
    supervisor_role.id = 2
    supervisor_role.name = "Supervisor"

    entity_manager.role_controller.get_all.return_value = [
        student_role,
        supervisor_role,
    ]
    MockFellowshipController.return_value.get_all.return_value = []

    session = MagicMock()
    session.execute.return_value.scalar.return_value = None
    person_matcher.person_controller._service._repository._session = session
    initiative_controller._service._repository._session = session

    student_match = MagicMock()
    student_match.id = 11
    supervisor_match = MagicMock()
    supervisor_match.id = 12
    student_person = MagicMock()
    student_person.id = 11
    supervisor_person = MagicMock()
    supervisor_person.id = 12

    person_matcher.match_or_create.side_effect = [student_match, supervisor_match]
    session.get.side_effect = [student_person, supervisor_person]
    person_matcher.person_controller.get_by_id.side_effect = [
        student_person,
        supervisor_person,
    ]

    handler = AdvisorshipHandler(
        initiative_controller=initiative_controller,
        person_matcher=person_matcher,
        entity_manager=entity_manager,
    )

    project_data = {
        "title": "Test Advisorship",
        "student_names": ["Student A"],
        "student_emails": ["student@example.org"],
        "coordinator_name": "Supervisor B",
        "coordinator_email": "supervisor@example.org",
        "status": "active",
    }

    created = handler.create_or_update(
        project_data=project_data,
        existing_initiative=None,
        initiative_type_name="Advisorship",
        initiative_type_id=7,
        organization_id=9,
        parent_id=10,
    )

    assert isinstance(created, Advisorship)
    MockAdvisorshipController.return_value.create_advisorship.assert_not_called()
    MockAdvisorshipController.return_value.create.assert_called_once_with(created)
    assert [member.person for member in created.members] == [
        student_person,
        supervisor_person,
    ]
    assert [member.role_name for member in created.members] == [
        "Student",
        "Supervisor",
    ]
    assert created.initiative_type_id == 7
    assert created.organization_id == 9
    assert created.parent_id == 10


def _advisorship_handler(minimal=True):
    initiative_controller = MagicMock()
    person_matcher = MagicMock()
    entity_manager = MagicMock()
    entity_manager.role_controller.get_all.return_value = []
    session = MagicMock()
    session.execute.return_value.scalar.return_value = None
    initiative_controller._service._repository._session = session
    person_matcher.person_controller._service._repository._session = session
    return AdvisorshipHandler(
        initiative_controller=initiative_controller,
        person_matcher=person_matcher,
        entity_manager=entity_manager,
    )


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_advisorship_handler_persists_program_on_create(
    MockAdvisorshipController,
    MockFellowshipController,
):
    MockFellowshipController.return_value.get_all.return_value = []
    handler = _advisorship_handler()

    created = handler.create_or_update(
        project_data={
            "title": "Advisorship Com Programa",
            "status": "active",
            "program": "Pibic",
        },
        existing_initiative=None,
        initiative_type_name="Advisorship",
        initiative_type_id=7,
        organization_id=9,
    )

    assert isinstance(created, Advisorship)
    assert created.program == "Pibic"
    MockAdvisorshipController.return_value.create.assert_called_once_with(created)


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_advisorship_handler_persists_program_on_update(
    _MockAdvisorshipController,
    MockFellowshipController,
):
    MockFellowshipController.return_value.get_all.return_value = []
    handler = _advisorship_handler()

    created = handler.create_or_update(
        project_data={
            "title": "Advisorship Atualizada",
            "status": "active",
            "program": "Pibic",
        },
        existing_initiative=None,
        initiative_type_name="Advisorship",
        initiative_type_id=7,
        organization_id=9,
    )
    assert created.program == "Pibic"

    updated = handler.create_or_update(
        project_data={
            "title": "Advisorship Atualizada",
            "status": "concluded",
            "program": "Pivic",
        },
        existing_initiative=created,
        initiative_type_name="Advisorship",
        initiative_type_id=7,
        organization_id=9,
    )

    assert updated.program == "Pivic"


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_advisorship_handler_disambiguates_title_when_name_is_already_taken(
    _MockAdvisorshipController,
    MockFellowshipController,
):
    initiative_controller = MagicMock()
    person_matcher = MagicMock()
    entity_manager = MagicMock()

    MockFellowshipController.return_value.get_all.return_value = []
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 258
    initiative_controller._service._repository._session = session
    person_matcher.person_controller._service._repository._session = session

    handler = AdvisorshipHandler(
        initiative_controller=initiative_controller,
        person_matcher=person_matcher,
        entity_manager=entity_manager,
    )

    title = handler._resolve_persisted_title(
        "Desenvolvimento de uma Bancada Didática de Baixo Custo",
        {
            "student_names": ["Ana Estudante"],
            "start_date": datetime(2019, 8, 1),
            "metadata": {"sigpesq_id": 123},
        },
    )

    assert (
        title
        == "Desenvolvimento de uma Bancada Didática de Baixo Custo | Orientacao Ana Estudante | 2019 | sigpesq 123"
    )


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_advisorship_handler_supports_legacy_student_and_supervisor_fields(
    _MockAdvisorshipController,
    MockFellowshipController,
):
    initiative_controller = MagicMock()
    person_matcher = MagicMock()
    entity_manager = MagicMock()

    MockFellowshipController.return_value.get_all.return_value = []
    session = MagicMock()
    initiative_controller._service._repository._session = session
    person_matcher.person_controller._service._repository._session = session

    handler = AdvisorshipHandler(
        initiative_controller=initiative_controller,
        person_matcher=person_matcher,
        entity_manager=entity_manager,
    )

    class LegacyAdvisorship:
        student = None
        student_id = None
        supervisor = None
        supervisor_id = None

    initiative = LegacyAdvisorship()
    student = MagicMock()
    student.id = 11
    supervisor = MagicMock()
    supervisor.id = 12

    with patch.object(handler, "_coerce_to_person", side_effect=[student, supervisor]):
        handler._sync_advisorship_member(
            initiative,
            person=student,
            role_name="Student",
            start_date=None,
        )
        handler._sync_advisorship_member(
            initiative,
            person=supervisor,
            role_name="Supervisor",
            start_date=None,
        )

    assert initiative.student is student
    assert initiative.student_id == 11
    assert initiative.supervisor is supervisor
    assert initiative.supervisor_id == 12


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_advisorship_handler_reuses_fellowships_by_program_and_sponsor_across_workplans(
    _MockAdvisorshipController,
    MockFellowshipController,
):
    initiative_controller = MagicMock()
    person_matcher = MagicMock()
    entity_manager = MagicMock()

    MockFellowshipController.return_value.get_all.return_value = []
    entity_manager.ensure_organization.side_effect = [101, 102]
    session = MagicMock()
    initiative_controller._service._repository._session = session
    person_matcher.person_controller._service._repository._session = session

    handler = AdvisorshipHandler(
        initiative_controller=initiative_controller,
        person_matcher=person_matcher,
        entity_manager=entity_manager,
    )

    first = handler._ensure_fellowship(
        {
            "fellowship_data": {
                "name": "PIVIC",
                "sponsor_name": "Voluntario",
                "value": 700.0,
                "sigpesq_workplan_code": "17515",
                "sigpesq_project_code": "8748",
            }
        }
    )
    second = handler._ensure_fellowship(
        {
            "fellowship_data": {
                "name": "PIVIC",
                "sponsor_name": "Voluntario",
                "value": 700.0,
                "sigpesq_workplan_code": "17548",
                "sigpesq_project_code": "8752",
            }
        }
    )
    again_first = handler._ensure_fellowship(
        {
            "fellowship_data": {
                "name": "PIVIC",
                "sponsor_name": "Voluntario",
                "value": 700.0,
                "sigpesq_workplan_code": "17515",
                "sigpesq_project_code": "8748",
            }
        }
    )
    cnpq = handler._ensure_fellowship(
        {
            "fellowship_data": {
                "name": "PIVIC",
                "sponsor_name": "CNPq",
                "value": 700.0,
                "sigpesq_workplan_code": "17549",
                "sigpesq_project_code": "8753",
            }
        }
    )

    assert second is first
    assert again_first is first
    assert cnpq is not first
    assert first.sponsor_id == 101
    assert cnpq.sponsor_id == 102
    entity_manager.ensure_organization.assert_has_calls(
        [call(name="Voluntario"), call(name="CNPq")]
    )
    assert MockFellowshipController.return_value.create.call_count == 2


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_ensure_fellowship_updates_stale_value_on_existing_fellowship(
    MockAdvisorshipController,
    MockFellowshipController,
):
    MockFellowshipController.return_value.get_all.return_value = []
    initiative_controller = MagicMock()
    person_matcher = MagicMock()
    entity_manager = MagicMock()
    entity_manager.role_controller.get_all.return_value = []
    session = MagicMock()
    session.execute.return_value.scalar.return_value = None
    initiative_controller._service._repository._session = session
    person_matcher.person_controller._service._repository._session = session

    handler = AdvisorshipHandler(
        initiative_controller=initiative_controller,
        person_matcher=person_matcher,
        entity_manager=entity_manager,
    )

    first = handler._ensure_fellowship(
        {
            "fellowship_data": {
                "name": "PIBITI",
                "sponsor_name": "Fapes",
                "value": 400.0,
            }
        }
    )
    assert first.value == 400.0

    second = handler._ensure_fellowship(
        {
            "fellowship_data": {
                "name": "PIBITI",
                "sponsor_name": "Fapes",
                "value": 800.0,
            }
        }
    )
    assert second is first
    assert second.value == 800.0
    MockFellowshipController.return_value.update.assert_called_once()


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_advisorship_handler_sets_cancelled_on_created_advisorship(
    MockAdvisorshipController,
    MockFellowshipController,
):
    initiative_controller = MagicMock()
    person_matcher = MagicMock()
    entity_manager = MagicMock()

    MockFellowshipController.return_value.get_all.return_value = []
    session = MagicMock()
    session.execute.return_value.scalar.return_value = None
    initiative_controller._service._repository._session = session
    person_matcher.person_controller._service._repository._session = session

    handler = AdvisorshipHandler(
        initiative_controller=initiative_controller,
        person_matcher=person_matcher,
        entity_manager=entity_manager,
    )

    created = handler.create_or_update(
        project_data={
            "title": "Plano cancelado",
            "status": "Cancelled",
            "cancelled": True,
            "cancellation_date": None,
        },
        existing_initiative=None,
        initiative_type_name="Advisorship",
        initiative_type_id=7,
        organization_id=9,
        parent_id=10,
    )

    assert created.cancelled is True
    assert created.cancellation_date is None
    MockAdvisorshipController.return_value.create.assert_called_once_with(created)


# ---------------------------------------------------------------------------
# Substituição de aluno x continuação da mesma bolsa
# ---------------------------------------------------------------------------


def _orientacao_existente(
    *,
    person_id: int,
    start: datetime,
    end: datetime,
    workplan_code: str = "14293",
    parent_id: int = 574,
):
    orientacao = MagicMock()
    orientacao.parent_id = parent_id
    orientacao.start_date = start
    orientacao.end_date = end
    orientacao.metadata = {"sigpesq_workplan_code": workplan_code}

    membro = MagicMock()
    membro.person_id = person_id
    membro.role_name = "Student"
    membro.start_date = start.date()
    membro.end_date = end.date()
    orientacao.members = [membro]
    return orientacao


def test_find_continuous_reuses_same_student_across_year_boundary():
    handler = _advisorship_handler()
    existente = _orientacao_existente(
        person_id=1019,
        start=datetime(2024, 9, 1),
        end=datetime(2025, 2, 17),
    )
    handler._known_advisorships_cache = [existente]

    aluno = MagicMock()
    aluno.id = 1019
    handler._resolve_advisorship_people = MagicMock(return_value=(aluno, MagicMock()))

    encontrada = handler._find_continuous_advisorship(
        {
            "start_date": datetime(2025, 2, 18),
            "end_date": datetime(2025, 8, 31),
            "metadata": {"sigpesq_workplan_code": "14293"},
        },
        574,
    )

    assert encontrada is existente


def test_find_continuous_does_not_match_a_different_student():
    handler = _advisorship_handler()
    existente = _orientacao_existente(
        person_id=474,
        start=datetime(2024, 9, 1),
        end=datetime(2025, 2, 17),
    )
    handler._known_advisorships_cache = [existente]

    aluna = MagicMock()
    aluna.id = 1019
    handler._resolve_advisorship_people = MagicMock(return_value=(aluna, MagicMock()))

    encontrada = handler._find_continuous_advisorship(
        {
            "start_date": datetime(2025, 2, 18),
            "end_date": datetime(2025, 8, 31),
            "metadata": {"sigpesq_workplan_code": "14293"},
        },
        574,
    )

    assert (
        encontrada is None
    ), "a Julia foi tratada como continuação do Kauã: são bolsas diferentes"


def test_find_continuous_does_not_match_a_real_gap():
    handler = _advisorship_handler()
    existente = _orientacao_existente(
        person_id=900,
        start=datetime(2022, 1, 1),
        end=datetime(2022, 9, 27),
    )
    handler._known_advisorships_cache = [existente]

    aluno = MagicMock()
    aluno.id = 900
    handler._resolve_advisorship_people = MagicMock(return_value=(aluno, MagicMock()))

    encontrada = handler._find_continuous_advisorship(
        {
            "start_date": datetime(2023, 3, 9),
            "end_date": datetime(2023, 12, 31),
            "metadata": {"sigpesq_workplan_code": "14293"},
        },
        574,
    )

    assert encontrada is None


def test_extend_continuous_keeps_original_start_and_does_not_rename():
    handler = _advisorship_handler()
    existente = _orientacao_existente(
        person_id=1019,
        start=datetime(2024, 9, 1),
        end=datetime(2025, 2, 17),
    )
    existente.name = "Plano de Trabalho Compartilhado"
    existente.status = "Active"

    aluno = MagicMock()
    aluno.id = 1019
    supervisor = MagicMock()
    supervisor.id = 680
    handler._resolve_advisorship_people = MagicMock(return_value=(aluno, supervisor))
    handler._ensure_fellowship = MagicMock(return_value=None)
    handler._sync_advisorship_member = MagicMock()
    handler.adv_controller.update = MagicMock()

    resultado = handler._extend_continuous_advisorship(
        existente,
        {
            "start_date": datetime(2025, 2, 18),
            "end_date": datetime(2025, 8, 31),
            "status": "Concluded",
            "metadata": {"sigpesq_workplan_code": "14293"},
        },
    )

    assert resultado is existente
    assert existente.start_date == datetime(2024, 9, 1)
    assert existente.end_date == datetime(2025, 8, 31)
    assert existente.name == "Plano de Trabalho Compartilhado"
    assert existente.status == "Concluded"
    assert existente._reused_existing is True
    assert existente._aggregated_period is True


def test_repeated_segment_does_not_shrink_aggregated_period():
    handler = _advisorship_handler()
    existente = _orientacao_existente(
        person_id=1019,
        start=datetime(2023, 9, 1),
        end=datetime(2024, 8, 31),
        workplan_code="12191",
    )
    existente.name = "Plano Agregado"
    existente.status = "Concluded"
    existente._aggregated_period = True

    aluno = MagicMock()
    aluno.id = 1019
    supervisor = MagicMock()
    supervisor.id = 680
    handler._resolve_advisorship_people = MagicMock(return_value=(aluno, supervisor))
    handler._ensure_fellowship = MagicMock(return_value=None)
    handler._resolve_persisted_title = MagicMock(return_value="Plano Agregado")
    handler._coerce_to_person = MagicMock(side_effect=lambda person: person)
    handler.adv_controller.update = MagicMock()

    resultado = handler.create_or_update(
        project_data={
            "title": "Plano Agregado",
            "identity_key": "sigpesq_workplan|12191|7031",
            "start_date": datetime(2023, 9, 1),
            "end_date": datetime(2024, 3, 13),
            "status": "Cancelled",
            "metadata": {"sigpesq_workplan_code": "12191"},
        },
        existing_initiative=existente,
        initiative_type_name="Advisorship",
        initiative_type_id=7,
        organization_id=9,
        parent_id=574,
    )

    assert resultado is existente
    assert existente.start_date == datetime(2023, 9, 1)
    assert existente.end_date == datetime(2024, 8, 31)
    assert existente.name == "Plano Agregado"
    membro = existente.members[0]
    assert membro.start_date == date(2023, 9, 1)
    assert membro.end_date == date(2024, 8, 31)


def test_sync_member_updates_dates_without_duplicating():
    handler = _advisorship_handler()
    orientacao = MagicMock()
    membro = MagicMock()
    membro.person_id = 11
    membro.role_name = "Student"
    membro.start_date = date(2024, 9, 1)
    membro.end_date = None
    orientacao.members = [membro]

    aluno = MagicMock()
    aluno.id = 11

    with patch.object(handler, "_coerce_to_person", return_value=aluno):
        handler._sync_advisorship_member(
            orientacao,
            person=aluno,
            role_name="Student",
            start_date=datetime(2024, 9, 1),
            end_date=datetime(2025, 2, 17),
        )

    assert orientacao.members == [membro]
    assert membro.start_date == date(2024, 9, 1)
    assert membro.end_date == date(2025, 2, 17)
    orientacao.add_member.assert_not_called()


def test_sync_member_adds_end_date_on_created_member():
    handler = _advisorship_handler()
    orientacao = MagicMock()
    orientacao.members = []

    novo_membro = MagicMock()
    novo_membro.person_id = 12
    novo_membro.role_name = "Student"

    def adiciona(person, role, start_date):
        orientacao.members.append(novo_membro)

    orientacao.add_member.side_effect = adiciona

    aluno = MagicMock()
    aluno.id = 12

    with patch.object(handler, "_coerce_to_person", return_value=aluno):
        handler._sync_advisorship_member(
            orientacao,
            person=aluno,
            role_name="Student",
            start_date=datetime(2025, 2, 18),
            end_date=datetime(2025, 8, 31),
        )

    assert novo_membro.end_date == date(2025, 8, 31)
