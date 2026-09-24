import re
import unicodedata
from unittest.mock import MagicMock, patch

import pytest

from src.core.logic.entity_manager import EntityManager
from src.core.logic.project_loader import ProjectLoader


# Mock classes for controllers
class MockPerson:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class MockTeam:
    def __init__(self, id, name):
        self.id = id
        self.name = name


@pytest.fixture
def project_loader():
    with (
        patch("src.core.logic.entity_manager.PostgresClient"),
        patch("src.core.logic.entity_manager.OrganizationController"),
        patch("src.core.logic.project_loader.InitiativeController"),
        patch("src.core.logic.project_loader.TeamController"),
        patch("src.core.logic.project_loader.PersonController"),
        patch("research_domain.controllers.controllers.AdvisorshipController"),
        patch("research_domain.controllers.controllers.FellowshipController"),
        patch("src.core.logic.entity_manager.RoleController"),
        patch("src.core.logic.entity_manager.UniversityController"),
        patch("src.core.logic.initiative_linker.ResearchGroupController"),
    ):

        # Mock the mapping strategy
        mock_strategy = MagicMock()
        loader = ProjectLoader(mapping_strategy=mock_strategy)

        # Override controllers with our mocks if needed,
        # but the loader already instantiated them in __init__ using the patches.
        return loader


def test_create_initiative_team_idempotent(project_loader):
    """Test that team creation is idempotent based on name."""
    initiative = MagicMock()
    initiative.name = "Projeto Teste"
    initiative.id = 10

    existing_team = MockTeam(5, "Projeto Teste")
    # ProjectLoader.linker.team_synchronizer.ensure_team uses get_all()
    project_loader.team_controller.get_all.return_value = [existing_team]

    project_loader.linker.create_initiative_team(initiative, {"coordinator_name": None})

    # Should not call create_team if it exists
    project_loader.team_controller.create_team.assert_not_called()
    # Should still assign
    project_loader.controller.assign_team.assert_called_with(10, 5)


@patch("src.core.logic.entity_manager.PostgresClient")
@patch("src.core.logic.entity_manager.RoleController")
def test_ensure_roles_exist(mock_role_ctrl, mock_pg_client, project_loader):
    """Test that mandatory roles are ensured to exist."""
    session = MagicMock()
    mock_pg_client.return_value.get_session.return_value = session

    # Force failure in RoleController instance to trigger fallback
    project_loader.entity_manager.role_controller.get_all.side_effect = Exception(
        "DB Connection Failed"
    )

    # Mock no roles exist in fallback query
    session.query.return_value.filter_by.return_value.first.return_value = None

    project_loader.entity_manager.ensure_roles()

    assert session.add.call_count == len(EntityManager.ROLES)
    session.commit.assert_called()
