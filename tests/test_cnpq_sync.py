from types import SimpleNamespace
from unittest.mock import MagicMock

import src.core.logic.strategies.cnpq_sync as cnpq_sync_module
from src.core.logic.strategies.cnpq_sync import CnpqSyncLogic


def test_sync_members_uses_resume_fallback_for_new_researcher():
    logic = CnpqSyncLogic()

    session = MagicMock()
    researcher_check = MagicMock()
    researcher_check.scalar.return_value = True
    session.execute.return_value = researcher_check

    logic.rg_ctrl = MagicMock()
    logic.rg_ctrl._service._repository._session = session
    logic.rg_ctrl._service.get_members.return_value = []
    logic.res_ctrl = MagicMock()
    logic.res_ctrl.get_all.return_value = []
    logic.role_ctrl = MagicMock()
    logic.role_ctrl.get_all.return_value = []
    logic.role_ctrl.create_role.return_value = SimpleNamespace(id=7, name="Pesquisador")
    logic.ka_ctrl = MagicMock()

    logic.res_ctrl.create_researcher.side_effect = TypeError(
        "create_with_details() got an unexpected keyword argument 'resume'"
    )
    created = MagicMock()
    created.id = 123
    logic.res_ctrl._service.create_with_details.return_value = created
    researcher_check_exists = MagicMock()
    researcher_check_exists.scalar.return_value = True
    logic.res_ctrl._service._repository._session.execute.return_value = (
        researcher_check_exists
    )
    logic.res_ctrl.get_by_id.return_value = created

    logic.sync_members(
        group_id=10,
        members_data=[
            {
                "name": "Alice",
                "role": "Pesquisador",
                "data_inicio": None,
                "data_fim": None,
            }
        ],
    )

    logic.res_ctrl.create_researcher.assert_called_once_with(
        name="Alice",
        identification_id=None,
        emails=None,
    )
    logic.res_ctrl._service.create_with_details.assert_called_once_with(
        name="Alice",
        identification_id=None,
        emails=None,
    )
    assert session.commit.called
    logic.rg_ctrl._service.add_member.assert_called_once_with(
        team_id=10,
        person_id=123,
        role_id=7,
        start_date=None,
        end_date=None,
    )


def test_sync_group_coerces_dict_description_before_update():
    logic = CnpqSyncLogic()

    session = MagicMock()
    current_row = MagicMock()
    current_row.fetchone.return_value = ("Grupo Atual", None)
    session.execute.side_effect = [current_row, MagicMock()]

    logic.rg_ctrl = MagicMock()
    logic.rg_ctrl._service._repository._session = session

    logic.sync_group(
        group_id=87,
        cnpq_data={
            "nome_grupo": "Grupo Atual",
            "repercussoes": {"descricao": "Descricao normalizada do grupo"},
        },
    )

    update_params = session.execute.call_args_list[1].args[1]
    assert update_params["description"] == "Descricao normalizada do grupo"
    assert update_params["gid"] == 87
    session.commit.assert_called()


def test_sync_knowledge_areas_tracks_associations_after_commit(monkeypatch):
    logic = CnpqSyncLogic()

    session = MagicMock()
    existence_check = MagicMock()
    existence_check.fetchone.return_value = None
    session.execute.side_effect = [existence_check, MagicMock()]

    events = []
    session.commit.side_effect = lambda: events.append("commit")

    logic.rg_ctrl = MagicMock()
    logic.rg_ctrl._service._repository._session = session
    logic.ka_ctrl = MagicMock()
    logic.ka_ctrl.get_all.return_value = [SimpleNamespace(id=55, name="Linha A")]

    tracker = MagicMock()
    tracker.record_source_record.return_value = SimpleNamespace(id=91)
    tracker.record_entity_match.side_effect = lambda **kwargs: events.append("match")
    tracker.record_attribute_assertions.side_effect = lambda **kwargs: events.append(
        "assert"
    )
    tracker.record_change.side_effect = lambda **kwargs: events.append("change")
    monkeypatch.setattr(cnpq_sync_module, "tracking_recorder", tracker)

    logic.sync_knowledge_areas(
        group_id=10,
        lines_data=[{"nome_da_linha_de_pesquisa": "Linha A"}],
        source_file="grupo.json",
    )

    assert events == ["commit", "match", "assert", "change"]


# --- Researcher index once per phase (spec 017, TD-008) ----------------------


def _logic_with_mocks(created_id=900):
    from src.core.logic.strategies.cnpq_sync import CnpqSyncLogic

    logic = CnpqSyncLogic()
    session = MagicMock()
    exists = MagicMock()
    exists.scalar.return_value = True
    session.execute.return_value = exists
    logic.rg_ctrl = MagicMock()
    logic.rg_ctrl._service._repository._session = session
    logic.rg_ctrl._service.get_members.return_value = []
    logic.res_ctrl = MagicMock()
    logic.res_ctrl.get_all.return_value = []
    logic.res_ctrl.create_researcher.return_value = SimpleNamespace(
        id=created_id, name="Novo Pesquisador", identification_id=None
    )
    logic.role_ctrl = MagicMock()
    logic.role_ctrl.get_all.return_value = []
    logic.role_ctrl.create_role.return_value = SimpleNamespace(id=7, name="Pesquisador")
    logic.ka_ctrl = MagicMock()
    return logic


def _member(name):
    return {"name": name, "role": "Pesquisador", "data_inicio": None, "data_fim": None}


def test_sync_members_with_index_never_reads_the_register():
    from src.core.logic.researcher_resolution import ResearcherRef

    CnpqSyncLogic.reset_researcher_counters()
    logic = _logic_with_mocks()
    index = [ResearcherRef(id=5, name="Ana Lima")]

    logic.sync_members(10, [_member("Ana Lima")], researcher_index=index)

    logic.res_ctrl.get_all.assert_not_called()
    logic.res_ctrl.create_researcher.assert_not_called()
    assert logic.rg_ctrl._service.add_member.call_args.kwargs["person_id"] == 5
    assert CnpqSyncLogic.researcher_counters == {"hits": 1, "created": 0}


def test_researcher_created_by_one_group_is_found_by_the_next():
    from src.core.logic.researcher_resolution import ResearcherRef

    CnpqSyncLogic.reset_researcher_counters()
    index = [ResearcherRef(id=5, name="Ana Lima")]

    group_a = _logic_with_mocks(created_id=900)
    group_a.sync_members(10, [_member("Novo Pesquisador")], researcher_index=index)
    group_b = _logic_with_mocks(created_id=901)
    group_b.sync_members(11, [_member("Novo Pesquisador")], researcher_index=index)

    group_a.res_ctrl.create_researcher.assert_called_once()
    group_b.res_ctrl.create_researcher.assert_not_called()
    assert group_b.rg_ctrl._service.add_member.call_args.kwargs["person_id"] == 900
    assert [r.id for r in index] == [5, 900]
    assert isinstance(index[-1], ResearcherRef)
    assert CnpqSyncLogic.researcher_counters == {"hits": 1, "created": 1}


def test_sync_members_without_index_keeps_reading_the_register_once():
    logic = _logic_with_mocks()

    logic.sync_members(10, [_member("Ana Lima"), _member("Bruno Alves")])

    logic.res_ctrl.get_all.assert_called_once()


# --- Member end dates: last period per resolved person (spec 020, FR-022) ----


def _logic_with_member(stored_end_date):
    """One existing member (person 5) whose stored end date is given."""
    from sqlalchemy.sql.elements import TextClause

    logic = _logic_with_mocks()
    session = logic.rg_ctrl._service._repository._session
    updates = []

    def execute(statement, params=None):
        sql = str(statement) if isinstance(statement, TextClause) else ""
        result = MagicMock()
        if sql.startswith("SELECT end_date"):
            result.scalar.return_value = stored_end_date
        elif sql.startswith("UPDATE team_members"):
            updates.append(params)
        else:
            result.scalar.return_value = True
        return result

    session.execute.side_effect = execute
    logic.rg_ctrl._service.get_members.return_value = [
        SimpleNamespace(person_id=5, end_date=stored_end_date)
    ]
    return logic, updates


def _period(name, start, end):
    return {
        "name": name,
        "role": "Estudante (Egresso)",
        "data_inicio": start,
        "data_fim": end,
    }


def test_spellings_of_one_person_write_only_the_last_period():
    from src.core.logic.researcher_resolution import ResearcherRef

    members = [
        _period("Ricardo Vieira da silva", "02/09/2015", "25/08/2016"),
        _period("Ricardo Vieira da Silva", "25/08/2016", "25/08/2024"),
    ]
    logic, updates = _logic_with_member("2016-08-25")
    index = [ResearcherRef(id=5, name="Ricardo Vieira da Silva")]
    logic.sync_members(10, members, researcher_index=index)

    assert [str(u["end_dt"])[:10] for u in updates] == ["2024-08-25"]
    assert updates[0]["pid"] == 5


def test_member_end_date_already_stored_is_not_rewritten():
    from src.core.logic.researcher_resolution import ResearcherRef

    members = [
        _period("Ricardo Vieira da silva", "02/09/2015", "25/08/2016"),
        _period("Ricardo Vieira da Silva", "25/08/2016", "25/08/2024"),
    ]
    logic, updates = _logic_with_member("2024-08-25")
    index = [ResearcherRef(id=5, name="Ricardo Vieira da Silva")]
    logic.sync_members(10, members, researcher_index=index)

    assert updates == []
