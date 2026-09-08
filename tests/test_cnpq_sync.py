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
        researcher_index=[],
    )

    logic.res_ctrl.get_all.assert_not_called()
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


def test_researcher_created_by_one_group_is_found_by_the_next():
    """Regression guard for specs/011-cnpq-sync-index-reuse.

    The researcher index is built once per weekly run and shared across every
    group. If a researcher created while processing one group were not
    visible to the next, the same person would be created twice -- the exact
    duplication bug feature 008 already guards against for a different
    loader. This test proves the CNPq path shares that same guarantee.
    """
    logic = CnpqSyncLogic()

    session = MagicMock()
    exists_check = MagicMock()
    exists_check.scalar.return_value = True
    session.execute.return_value = exists_check

    logic.rg_ctrl = MagicMock()
    logic.rg_ctrl._service._repository._session = session
    logic.rg_ctrl._service.get_members.return_value = []
    logic.res_ctrl = MagicMock()
    logic.res_ctrl._service._repository._session = session
    logic.role_ctrl = MagicMock()
    logic.role_ctrl.get_all.return_value = []
    logic.role_ctrl.create_role.return_value = SimpleNamespace(id=7, name="Pesquisador")
    logic.ka_ctrl = MagicMock()

    created = MagicMock()
    created.id = 999
    created.name = "Bob Newly Created"
    logic.res_ctrl.create_researcher.return_value = created

    # A single index, shared across two calls to sync_members -- exactly as
    # sync_cnpq_groups_flow shares one `researcher_index` list across every
    # group in the real flow.
    shared_researcher_index = []

    member = {
        "name": "Bob Newly Created",
        "role": "Pesquisador",
        "data_inicio": None,
        "data_fim": None,
    }

    # First group: the researcher does not exist yet -> created.
    logic.sync_members(
        group_id=1,
        members_data=[member],
        researcher_index=shared_researcher_index,
    )

    # Second group, same shared index: the same name must be found, not
    # created again.
    logic.sync_members(
        group_id=2,
        members_data=[member],
        researcher_index=shared_researcher_index,
    )

    assert logic.res_ctrl.create_researcher.call_count == 1, (
        "the researcher was created more than once -- the index shared "
        "across groups did not pick up the researcher created by the first "
        "call, so the second call created a duplicate"
    )
    logic.res_ctrl.get_all.assert_not_called()


def test_role_registry_read_once_per_group():
    """Regression guard for the role-lookup half of specs/011-cnpq-sync-index-reuse.

    ``self.role_ctrl.get_all()`` must be called once per call to
    ``sync_members`` (i.e. once per group), not once per member.
    """
    logic = CnpqSyncLogic()

    session = MagicMock()
    exists_check = MagicMock()
    exists_check.scalar.return_value = True
    session.execute.return_value = exists_check

    logic.rg_ctrl = MagicMock()
    logic.rg_ctrl._service._repository._session = session
    logic.rg_ctrl._service.get_members.return_value = []
    logic.res_ctrl = MagicMock()
    logic.res_ctrl._service._repository._session = session

    existing_researcher = SimpleNamespace(id=1, name="Alice", identification_id=None)
    existing_role = SimpleNamespace(id=1, name="Pesquisador")
    logic.role_ctrl = MagicMock()
    logic.role_ctrl.get_all.return_value = [existing_role]
    logic.ka_ctrl = MagicMock()

    members = [
        {
            "name": "Alice",
            "role": "Pesquisador",
            "data_inicio": None,
            "data_fim": None,
        },
        {
            "name": "Alice",
            "role": "pesquisador",  # case-insensitive match, second member
            "data_inicio": None,
            "data_fim": None,
        },
    ]

    logic.sync_members(
        group_id=1,
        members_data=members,
        researcher_index=[existing_researcher],
    )

    assert logic.role_ctrl.get_all.call_count == 1, (
        "role registry was read more than once for a single group -- it "
        "must be read once per sync_members call, not once per member"
    )


def test_new_role_created_for_one_member_is_reused_by_the_next_in_same_group():
    """Guards the append-on-create fix that hoisting the role read requires.

    Two members in the same group need a role that does not exist yet. Since
    the role registry is now read once per group (not once per member), the
    role created for the first member must be appended to that in-memory
    snapshot so the second member finds it instead of creating a duplicate.
    """
    logic = CnpqSyncLogic()

    session = MagicMock()
    exists_check = MagicMock()
    exists_check.scalar.return_value = True
    session.execute.return_value = exists_check

    logic.rg_ctrl = MagicMock()
    logic.rg_ctrl._service._repository._session = session
    logic.rg_ctrl._service.get_members.return_value = []
    logic.res_ctrl = MagicMock()
    logic.res_ctrl._service._repository._session = session
    logic.res_ctrl.create_researcher.side_effect = [
        SimpleNamespace(id=1, name="Alice"),
        SimpleNamespace(id=2, name="Bob"),
    ]

    new_role = SimpleNamespace(id=42, name="Novo Cargo")
    logic.role_ctrl = MagicMock()
    logic.role_ctrl.get_all.return_value = []  # the new role does not exist yet
    logic.role_ctrl.create_role.return_value = new_role
    logic.ka_ctrl = MagicMock()

    members = [
        {"name": "Alice", "role": "Novo Cargo", "data_inicio": None, "data_fim": None},
        {"name": "Bob", "role": "Novo Cargo", "data_inicio": None, "data_fim": None},
    ]

    logic.sync_members(group_id=1, members_data=members, researcher_index=[])

    assert logic.role_ctrl.create_role.call_count == 1, (
        "the role was created twice in the same group -- the in-memory "
        "role snapshot was not updated after the first member created it"
    )
