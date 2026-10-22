from unittest.mock import MagicMock

from src.core.logic.team_synchronizer import TeamRef, TeamSynchronizer


class MockTeam:
    def __init__(self, team_id, name):
        self.id = team_id
        self.name = name


class MockPerson:
    def __init__(self, person_id):
        self.id = person_id


class MockMember:
    def __init__(self, member_id, person_id, role_id, start_date=None):
        self.id = member_id
        self.person_id = person_id
        self.role_id = role_id
        self.start_date = start_date


class MockRole:
    def __init__(self, role_id):
        self.id = role_id


class FakeTeamController:
    def __init__(self, members):
        self.members = list(members)
        self.next_id = 1000
        self.removed_ids = []

    def get_members(self, team_id):
        return list(self.members)

    def add_member(self, team_id, person_id, role=None, start_date=None):
        role_id = getattr(role, "id", None)
        self.members.append(MockMember(self.next_id, person_id, role_id, start_date))
        self.next_id += 1

    def remove_member(self, member_id):
        self.members = [m for m in self.members if m.id != member_id]
        self.removed_ids.append(member_id)


def test_ensure_team_matches_canonical_name():
    team_controller = MagicMock()
    team_controller.get_all.return_value = [MockTeam(1, "Conecta FAPES")]
    synchronizer = TeamSynchronizer(team_controller, roles_cache={})

    team = synchronizer.ensure_team("Conecta Fapes", "desc")

    assert team.id == 1
    team_controller.create_team.assert_not_called()


def _roles_cache():
    return {
        "Coordinator": MockRole(1),
        "Researcher": MockRole(2),
        "Student": MockRole(3),
    }


def test_sync_preserves_students_when_source_does_not_claim_student_role():
    # A project team loaded by SigPesq carries a full roster (coordinators,
    # researchers and students). A later Lattes-CV sync only lists
    # coordinator + researcher. The student membership must survive.
    team_controller = FakeTeamController(
        [
            MockMember(1, 30, 1),  # coordinator
            MockMember(2, 20, 2),  # obsolete researcher
            MockMember(3, 10, 3),  # student
        ]
    )
    synchronizer = TeamSynchronizer(team_controller, _roles_cache())

    synchronizer.synchronize_members(
        366,
        [
            (MockPerson(30), "Coordinator", None),
            (MockPerson(40), "Researcher", None),
        ],
    )

    remaining = {(m.person_id, m.role_id) for m in team_controller.members}
    assert (10, 3) in remaining  # student preserved
    assert (30, 1) in remaining  # coordinator kept
    assert (40, 2) in remaining  # new researcher added
    assert (20, 2) not in remaining  # obsolete researcher of claimed role removed
    assert 2 in team_controller.removed_ids


def test_sync_with_empty_member_list_removes_nothing():
    team_controller = FakeTeamController(
        [
            MockMember(1, 30, 1),
            MockMember(2, 20, 2),
            MockMember(3, 10, 3),
        ]
    )
    synchronizer = TeamSynchronizer(team_controller, _roles_cache())

    synchronizer.synchronize_members(366, [])

    remaining = {(m.person_id, m.role_id) for m in team_controller.members}
    assert remaining == {(30, 1), (20, 2), (10, 3)}
    assert team_controller.removed_ids == []


# --- Team lookup (spec 015): controller mode, i.e. no real SQLAlchemy session ---


class LookupTeamController:
    """Controller double without a SQLAlchemy session: forces controller mode."""

    def __init__(self, teams, fail_on_create=False):
        self.teams = list(teams)
        self.fail_on_create = fail_on_create
        self.get_all_calls = 0
        self.created = []
        self.next_id = 100

    def get_all(self):
        self.get_all_calls += 1
        return list(self.teams)

    def create_team(self, name, description):
        if self.fail_on_create:
            raise RuntimeError("db is down")
        team = MockTeam(self.next_id, name)
        self.next_id += 1
        self.created.append((name, description))
        self.teams.append(team)
        return team


def test_ensure_team_exact_hit_returns_team_ref_without_creating():
    controller = LookupTeamController([MockTeam(1, "Projeto Alfa")])
    synchronizer = TeamSynchronizer(controller, roles_cache={})

    team = synchronizer.ensure_team("Projeto Alfa", "desc")

    assert isinstance(team, TeamRef)
    assert (team.id, team.name) == (1, "Projeto Alfa")
    assert controller.created == []


def test_ensure_team_normalised_hit():
    controller = LookupTeamController([MockTeam(1, "Conecta FAPES")])
    synchronizer = TeamSynchronizer(controller, roles_cache={})

    assert synchronizer.ensure_team("Conecta Fapes", "desc").id == 1
    assert synchronizer.ensure_team("conecta   fapes!", "desc").id == 1
    assert controller.created == []


def test_ensure_team_ties_resolve_to_lowest_id():
    controller = LookupTeamController(
        [MockTeam(7, "Projeto X"), MockTeam(3, "PROJETO X")]
    )
    synchronizer = TeamSynchronizer(controller, roles_cache={})

    assert synchronizer.ensure_team("projeto x", "desc").id == 3
    assert synchronizer.ensure_team("Projeto X", "desc").id == 3


def test_ensure_team_creates_on_miss_and_finds_it_afterwards():
    controller = LookupTeamController([MockTeam(1, "Outro")])
    synchronizer = TeamSynchronizer(controller, roles_cache={})

    created = synchronizer.ensure_team(
        "Projeto Novo", "Equipe do projeto: Projeto Novo"
    )
    again = synchronizer.ensure_team("PROJETO NOVO", "Equipe do projeto: PROJETO NOVO")

    assert controller.created == [("Projeto Novo", "Equipe do projeto: Projeto Novo")]
    assert created.id == again.id == 100


def test_ensure_team_failed_creation_leaves_lookup_unchanged():
    controller = LookupTeamController([], fail_on_create=True)
    synchronizer = TeamSynchronizer(controller, roles_cache={})

    assert synchronizer.ensure_team("Projeto Z", "desc") is None

    controller.fail_on_create = False
    team = synchronizer.ensure_team("Projeto Z", "desc")
    assert team is not None and team.id == 100
    assert controller.created == [("Projeto Z", "desc")]


def test_ensure_team_reads_the_register_once():
    controller = LookupTeamController(
        [MockTeam(i, f"Equipe {i}") for i in range(1, 30)]
    )
    synchronizer = TeamSynchronizer(controller, roles_cache={})

    for i in range(50):
        synchronizer.ensure_team(f"Equipe {i % 40}", "desc")

    assert controller.get_all_calls == 1
