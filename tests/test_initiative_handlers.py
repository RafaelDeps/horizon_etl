from datetime import datetime
from types import SimpleNamespace
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
    # One update writes the sponsor of the new row (branch 036), the other
    # the changed value.
    assert MockFellowshipController.return_value.update.call_count == 2


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


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_unchanged_advisorship_member_is_kept_not_reinserted(
    _MockAdvisorshipController,
    MockFellowshipController,
):
    """Spec 020 (FR-022): the same person, role and day keeps its row."""
    from datetime import date

    from research_domain.domain.entities.advisorship import AdvisorshipMember

    MockFellowshipController.return_value.get_all.return_value = []
    handler = _advisorship_handler()
    person = MagicMock(id=42)
    advisorship = Advisorship(name="Orientacao")
    kept = AdvisorshipMember(
        person_id=42, role_name="Student", start_date=date(2019, 1, 1)
    )
    advisorship.members = [kept]

    with patch.object(handler, "_coerce_to_person", return_value=person):
        handler._sync_advisorship_member(
            advisorship,
            person=person,
            role_name="Student",
            start_date=datetime(2019, 1, 1),
        )
        assert advisorship.members == [kept]

        # A different start day still replaces the member.
        handler._sync_advisorship_member(
            advisorship,
            person=person,
            role_name="Student",
            start_date=datetime(2020, 1, 1),
        )
    assert kept not in advisorship.members


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_deferred_members_are_written_once_with_the_last_value(
    MockAdvisorshipController,
    MockFellowshipController,
):
    """Spec 020 (FR-022): two rows on one existing advisorship in a phase."""
    from datetime import date

    from research_domain.domain.entities.advisorship import AdvisorshipMember

    MockFellowshipController.return_value.get_all.return_value = []
    handler = _advisorship_handler()
    handler.defer_members = True
    person = MagicMock(id=42)
    advisorship = Advisorship(name="Orientacao")
    advisorship.id = 136
    kept = AdvisorshipMember(
        person_id=42, role_name="Student", start_date=date(2015, 1, 1)
    )
    advisorship.members = [kept]

    with patch.object(handler, "_coerce_to_person", return_value=person):
        for year in (2017, 2015):  # the same work listed twice in one CV
            handler._sync_advisorship_member(
                advisorship,
                person=person,
                role_name="Student",
                start_date=datetime(year, 1, 1),
            )
        assert advisorship.members == [kept]  # nothing written yet
        assert handler.flush_members() == 1

    assert advisorship.members == [kept]  # the last value equals the stored one
    assert handler.defer_members is True


# --- Spec 035: a matched advisorship keeps its stored name ------------------


def _update_name(handler, stored_name, project_data):
    """The name passed to update_initiative when an item is written over a
    matched advisorship named ``stored_name``."""
    existing = Advisorship(name=stored_name, status="active")
    existing.id = 41
    handler.create_or_update(
        project_data=project_data,
        existing_initiative=existing,
        initiative_type_name="Advisorship",
        initiative_type_id=7,
        organization_id=9,
    )
    return handler.initiative_controller.update_initiative.call_args.kwargs["name"]


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_matched_advisorship_keeps_its_distinct_name(
    _MockAdvisorshipController, MockFellowshipController
):
    MockFellowshipController.return_value.get_all.return_value = []
    handler = _advisorship_handler()
    # The bare title is held by another row.
    session = handler.initiative_controller._service._repository._session
    session.execute.return_value.scalar.return_value = 258

    name = _update_name(
        handler,
        "T | Orientacao Ana | 2019",
        {
            "title": "T",
            "status": "active",
            "student_names": ["Ana Estudante"],
            "start_date": datetime(2020, 8, 1),
            "metadata": {"sigpesq_id": 123},
        },
    )

    assert name == "T | Orientacao Ana | 2019"


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_matched_advisorship_keeps_its_bare_title(
    _MockAdvisorshipController, MockFellowshipController
):
    MockFellowshipController.return_value.get_all.return_value = []
    handler = _advisorship_handler()

    name = _update_name(handler, "T", {"title": "T", "status": "active"})

    assert name == "T"


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_matched_advisorship_with_a_new_title_is_renamed_as_before(
    _MockAdvisorshipController, MockFellowshipController
):
    MockFellowshipController.return_value.get_all.return_value = []
    handler = _advisorship_handler()
    data = {
        "title": "T",
        "status": "active",
        "student_names": ["Ana Estudante"],
        "start_date": datetime(2020, 8, 1),
    }

    # The new title is free: the row takes it.
    assert _update_name(handler, "Old", dict(data)) == "T"

    # The new title is held by another row: the distinct name, as before.
    session = handler.initiative_controller._service._repository._session
    session.execute.return_value.scalar.return_value = 258
    assert (
        _update_name(handler, "Old", dict(data))
        == "T | Orientacao Ana Estudante | 2020"
    )


# --- Spec 036: an item whose student text is not a name has no student ---


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_an_item_without_a_student_resolves_to_no_person(
    _MockAdvisorshipController, MockFellowshipController
):
    MockFellowshipController.return_value.get_all.return_value = []
    person_matcher = MagicMock()
    handler = AdvisorshipHandler(
        initiative_controller=MagicMock(),
        person_matcher=person_matcher,
        entity_manager=MagicMock(),
    )

    assert handler._student_person({"student_names": []}) is None
    assert handler.item_student({"student_names": []}) == (None, "")
    person_matcher.match_or_create.assert_not_called()


# --- Spec 036: a new fellowship is stored with its sponsor ---


def _fellowship_handler(MockFellowshipController, stored=(), sponsor_id=3):
    MockFellowshipController.return_value.get_all.return_value = list(stored)
    entity_manager = MagicMock()
    entity_manager.ensure_organization.return_value = sponsor_id
    handler = AdvisorshipHandler(
        initiative_controller=MagicMock(),
        person_matcher=MagicMock(),
        entity_manager=entity_manager,
    )
    return handler, MockFellowshipController.return_value


def _fellowship_row(sponsor_name="CNPq"):
    return {
        "fellowship_data": {
            "name": "JTC",
            "sponsor_name": sponsor_name,
            "value": 0.0,
            "description": "Programa: JTC",
        }
    }


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_a_new_fellowship_gets_its_sponsor_written_after_it_is_created(
    _MockAdvisorshipController, MockFellowshipController
):
    handler, controller = _fellowship_handler(MockFellowshipController)
    order = MagicMock()
    order.attach_mock(controller.create, "create")
    order.attach_mock(controller.update, "update")

    fellowship = handler._ensure_fellowship(_fellowship_row())

    # The library's constructor clears the sponsor of a new row; the handler
    # writes it again once the row exists.
    assert order.mock_calls == [call.create(fellowship), call.update(fellowship)]
    assert fellowship.sponsor_id == 3


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_a_fellowship_stored_with_its_sponsor_is_found_in_the_next_run(
    _MockAdvisorshipController, MockFellowshipController
):
    stored = SimpleNamespace(
        id=15,
        name="JTC",
        value=0.0,
        sponsor_id=3,
        sponsor=SimpleNamespace(name="CNPq"),
    )
    handler, controller = _fellowship_handler(MockFellowshipController, [stored])

    assert handler._ensure_fellowship(_fellowship_row()) is stored
    assert handler._ensure_fellowship(_fellowship_row(" cnpq ")) is stored
    controller.create.assert_not_called()
    controller.update.assert_not_called()


@patch("src.core.logic.initiative_handlers.FellowshipController")
@patch("src.core.logic.initiative_handlers.AdvisorshipController")
def test_a_fellowship_without_a_sponsor_is_created_once_and_found_again(
    _MockAdvisorshipController, MockFellowshipController
):
    handler, controller = _fellowship_handler(MockFellowshipController)

    first = handler._ensure_fellowship(_fellowship_row(sponsor_name=""))

    controller.create.assert_called_once_with(first)
    controller.update.assert_not_called()
    assert first.sponsor_id is None

    stored = SimpleNamespace(
        id=19, name="JTC", value=0.0, sponsor_id=None, sponsor=None
    )
    later, later_controller = _fellowship_handler(MockFellowshipController, [stored])
    later_controller.create.reset_mock()

    assert later._ensure_fellowship(_fellowship_row(sponsor_name="")) is stored
    later_controller.create.assert_not_called()
