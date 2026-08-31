from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from src.core.logic.canonical_exporter import CanonicalDataExporter
from src.core.ports.export_sink import IExportSink
from src.tracking.entities import (
    AttributeAssertion,
    EntityChangeLog,
    EntityMatch,
    IngestionRun,
    SourceRecord,
)


def test_export_all_orchestrates_exports():
    # Arrange
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch(
            "src.core.logic.canonical_exporter.OrganizationController"
        ) as MockOrgCtrl,
        patch("src.core.logic.canonical_exporter.CampusController") as MockCampCtrl,
        patch(
            "src.core.logic.canonical_exporter.KnowledgeAreaController"
        ) as MockKaCtrl,
        patch(
            "src.core.logic.canonical_exporter.ResearcherController"
        ) as MockResearcherCtrl,
        patch("src.core.logic.canonical_exporter.PersonController") as MockPersonCtrl,
        patch("src.core.logic.canonical_exporter.InitiativeController") as MockInitCtrl,
        patch("src.core.logic.canonical_exporter.ArticleController") as MockArticleCtrl,
        patch(
            "src.core.logic.canonical_exporter.ResearchGroupController"
        ) as MockRGCtrl,
        patch("eo_lib.TeamController") as MockTeamCtrl,
    ):

        # Mock Instances
        mock_org_instance = MockOrgCtrl.return_value
        mock_camp_instance = MockCampCtrl.return_value
        mock_ka_instance = MockKaCtrl.return_value
        mock_researcher_instance = MockResearcherCtrl.return_value
        mock_person_instance = MockPersonCtrl.return_value
        mock_init_instance = MockInitCtrl.return_value
        mock_article_instance = MockArticleCtrl.return_value
        mock_rg_instance = MockRGCtrl.return_value
        mock_team_instance = MockTeamCtrl.return_value

        # Mock Data (Simple objects or dicts)
        # Using objects with to_dict for completeness
        mock_org = MagicMock()
        mock_org.to_dict.return_value = {"id": 1, "name": "Org1"}
        mock_org_instance.get_all.return_value = [mock_org]

        mock_camp = MagicMock()
        mock_camp.to_dict.return_value = {"id": 10, "name": "Campus1"}
        mock_camp_instance.get_all.return_value = [mock_camp]

        mock_ka = MagicMock()
        mock_ka.to_dict.return_value = {"id": 100, "name": "Area1"}
        mock_ka_instance.get_all.return_value = [mock_ka]

        mock_researcher = MagicMock()
        mock_researcher.to_dict.return_value = {"id": 1000, "name": "Researcher1"}
        mock_researcher_instance.get_all.return_value = [mock_researcher]
        mock_person_instance.get_all.return_value = []
        mock_article_instance.get_all.return_value = []

        # Mock Initiative Data
        mock_init = MagicMock()
        mock_init.id = 500
        mock_init.name = "Init1"
        # Need dates for isoformat call
        from datetime import datetime

        mock_init.start_date = datetime(2023, 1, 1)
        mock_init.end_date = datetime(2023, 12, 31)
        mock_init.initiative_type_id = 1
        mock_init.organization_id = 1
        mock_init.parent_id = None
        mock_init.status = "active"
        mock_init.status = "active"
        mock_init.description = "desc"
        mock_init.metadata = {
            "external_partner": "Partner A",
            "external_research_group": "Group B",
        }

        mock_init_instance.get_all.return_value = [mock_init]
        mock_init_instance.list_initiative_types.return_value = [
            {"id": 1, "name": "Type1"}
        ]
        mock_init_instance.get_teams.return_value = [{"id": 90}]

        # Mock Team
        mock_team_member = MagicMock()
        mock_team_member.person_id = 99
        mock_team_member.person.name = "Person1"
        mock_team_member.role.name = "Role1"
        mock_team_member.start_date = datetime(2023, 1, 1)
        mock_team_member.end_date = None
        mock_team_instance.get_members.return_value = [mock_team_member]

        # Mock RG
        mock_rg = MagicMock()
        mock_rg.id = 90
        mock_rg.name = "RG1"
        mock_rg_instance.get_all.return_value = [mock_rg]

        exporter = CanonicalDataExporter(sink=mock_sink)

        # Act
        with patch("os.makedirs") as mock_makedirs:
            exporter.export_all("data/exports")

            # Assert
            mock_makedirs.assert_called_once()

            # Verify Sink Calls
            # Includes canonical exports, tracking overlays, and tracking entities.
            # +6 Lattes-derived exports: awards, languages, proficiencies,
            # professional_activities, production_types, research_productions.
            assert mock_sink.export.call_count == 28

            # Check call args to verify content
            calls = mock_sink.export.call_args_list
            exported_by_path = {call[0][1]: call[0][0] for call in calls}

            # Organization export
            args, _ = calls[0]
            assert args[0] == [{"id": 1, "name": "Org1", "campus": None}]
            assert "organizations_canonical.json" in args[1]

            # Campus export
            args, _ = calls[1]
            assert args[0] == [
                {
                    "id": 10,
                    "name": "Campus1",
                    "campus": {"id": 10, "name": "Campus1"},
                }
            ]
            assert "campuses_canonical.json" in args[1]

            # Knowledge Area export
            args, _ = calls[2]
            assert args[0] == [{"id": 100, "name": "Area1", "campus": None}]
            assert "knowledge_areas_canonical.json" in args[1]

            # Researcher export
            assert exported_by_path["data/exports/researchers_canonical.json"] == [
                {
                    "id": 1000,
                    "name": "Researcher1",
                    "identification_id": None,
                    "birthday": None,
                    "cnpq_url": None,
                    "google_scholar_url": None,
                    "resume": None,
                    "citation_names": None,
                    "initiatives": [],
                    "research_groups": [],
                    "knowledge_areas": [],
                    "academic_education": [],
                    "articles": [],
                    "advisorships": [],
                    "classification": None,
                    "classification_confidence": "low",
                    "classification_note": None,
                    "role_evidence": {
                        "project_roles": [],
                        "research_group_roles": [],
                        "advisorship_roles": [],
                        "has_institutional_email": False,
                        "academic_reference_count": 0,
                    },
                    "was_student": False,
                    "was_staff": False,
                    "campus": None,
                }
            ]
            assert (
                exported_by_path["data/exports/researchers_only_canonical.json"] == []
            )
            assert exported_by_path["data/exports/students_canonical.json"] == []
            assert exported_by_path["data/exports/outside_ifes_canonical.json"] == []
            assert (
                exported_by_path["data/exports/null_researchers_canonical.json"]
                == exported_by_path["data/exports/researchers_canonical.json"]
            )

            # Researchers tracking export
            assert exported_by_path["data/exports/researchers_tracking.json"] == []

            exported_paths = [call[0][1] for call in calls]
            assert any(
                path.endswith("ingestion_runs_canonical.json")
                for path in exported_paths
            )
            assert any(
                path.endswith("source_records_canonical.json")
                for path in exported_paths
            )
            assert any(
                path.endswith("entity_matches_canonical.json")
                for path in exported_paths
            )
            assert any(
                path.endswith("attribute_assertions_canonical.json")
                for path in exported_paths
            )
            assert any(
                path.endswith("entity_change_logs_canonical.json")
                for path in exported_paths
            )


def test_export_researchers_tracking_builds_parallel_payload():
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            statement_text = getattr(statement, "text", str(statement))
            if (
                "FROM entity_matches" in statement_text
                and "JOIN source_records sr" not in statement_text
            ):
                return FakeResult([{"entity_id": 2981}])
            if "FROM entity_matches em" in statement_text:
                return FakeResult(
                    [
                        {
                            "entity_id": 2981,
                            "source_system": "lattes",
                            "source_entity_type": "researcher_profile",
                            "source_record_id": "8400407353673370",
                            "source_file": "data/lattes_json/00_Paulo.json",
                            "source_path": "$.dados_gerais",
                            "match_strategy": "lattes_id_exact",
                            "match_confidence": 1,
                            "matched_at": "2026-03-23T10:00:00",
                        }
                    ]
                )
            if "FROM attribute_assertions aa" in statement_text:
                return FakeResult(
                    [
                        {
                            "entity_id": 2981,
                            "attribute_name": "resume",
                            "value_json": {"text": "Resumo atualizado"},
                            "value_hash": "abc123",
                            "is_selected": 1,
                            "selection_reason": "preferred_lattes_resume",
                            "asserted_at": "2026-03-23T10:01:00",
                            "source_record_pk": 77,
                            "source_system": "lattes",
                            "source_entity_type": "researcher_profile",
                            "source_record_id": "8400407353673370",
                            "source_file": "data/lattes_json/00_Paulo.json",
                            "source_path": "$.resumo_cv",
                        }
                    ]
                )
            if "FROM entity_change_logs ecl" in statement_text:
                return FakeResult(
                    [
                        {
                            "entity_id": 2981,
                            "operation": "create",
                            "changed_fields_json": ["name", "resume"],
                            "before_json": None,
                            "after_json": {"id": 2981},
                            "reason": "lattes researcher import",
                            "changed_at": "2026-03-23T10:02:00",
                            "run_id": 12,
                            "run_source_system": "lattes",
                            "flow_name": "ingest_lattes_projects",
                            "run_status": "completed",
                            "source_record_pk": 77,
                            "source_record_system": "lattes",
                            "source_entity_type": "researcher_profile",
                            "source_record_id": "8400407353673370",
                            "source_file": "data/lattes_json/00_Paulo.json",
                            "source_path": "$.dados_gerais",
                        }
                    ]
                )
            return FakeResult([])

    exporter._has_tracking_schema = lambda: True
    exporter._get_session = lambda: FakeSession()

    exporter.export_researchers_tracking("output/researchers_tracking.json")

    mock_sink.export.assert_called_once()
    exported_data, output_path = mock_sink.export.call_args[0]

    assert output_path == "output/researchers_tracking.json"
    assert exported_data[0]["entity_type"] == "researcher"
    assert exported_data[0]["entity_id"] == 2981
    assert exported_data[0]["sources"] == ["lattes"]
    assert exported_data[0]["campus"] is None
    assert exported_data[0]["attributes"]["resume"]["selected_from"] == "lattes"
    assert exported_data[0]["created_by"]["operation"] == "create"
    assert exported_data[0]["last_updated_by"]["flow_name"] == "ingest_lattes_projects"


def test_export_tracking_entities_builds_canonical_files():
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)

    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def order_by(self, *_args, **_kwargs):
            return self

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self, rows_by_model):
            self._rows_by_model = rows_by_model

        def query(self, model):
            return FakeQuery(self._rows_by_model.get(model, []))

    rows_by_model = {
        IngestionRun: [
            IngestionRun(
                id=1,
                source_system="lattes",
                flow_name="ingest_lattes_projects",
                status="success",
            )
        ],
        SourceRecord: [
            SourceRecord(
                id=10,
                ingestion_run_id=1,
                source_system="lattes",
                source_entity_type="researcher_profile",
                source_record_id="8400407353673370",
                source_file="00_Paulo.json",
                source_path="data/lattes_json/00_Paulo.json",
                raw_payload_json={"nome": "Paulo"},
                payload_hash="payload-1",
            )
        ],
        EntityMatch: [
            EntityMatch(
                id=20,
                source_record_id=10,
                canonical_entity_type="researcher",
                canonical_entity_id=2981,
                match_strategy="lattes_id_exact",
                match_confidence=1,
            )
        ],
        AttributeAssertion: [
            AttributeAssertion(
                id=30,
                source_record_id=10,
                canonical_entity_type="researcher",
                canonical_entity_id=2981,
                attribute_name="resume",
                value_json={"text": "Resumo atualizado"},
                value_hash="resume-1",
                is_selected=True,
                selection_reason="preferred_lattes_resume",
            )
        ],
        EntityChangeLog: [
            EntityChangeLog(
                id=40,
                ingestion_run_id=1,
                source_record_id=10,
                canonical_entity_type="researcher",
                canonical_entity_id=2981,
                operation="update",
                changed_fields_json=["resume"],
                before_json={"resume": None},
                after_json={"resume": "Resumo atualizado"},
                reason="Updated from Lattes",
            )
        ],
    }

    exporter._has_tracking_schema = lambda: True
    exporter._get_session = lambda: FakeSession(rows_by_model)

    exporter.export_tracking_entities("output")

    exported = {
        call_args[0][1]: call_args[0][0]
        for call_args in mock_sink.export.call_args_list
    }

    assert len(exported) == 5
    assert (
        exported["output/ingestion_runs_canonical.json"][0]["source_system"] == "lattes"
    )
    assert (
        exported["output/source_records_canonical.json"][0]["source_file"]
        == "00_Paulo.json"
    )
    assert (
        exported["output/entity_matches_canonical.json"][0]["canonical_entity_type"]
        == "researcher"
    )
    assert (
        exported["output/attribute_assertions_canonical.json"][0]["attribute_name"]
        == "resume"
    )
    assert (
        exported["output/entity_change_logs_canonical.json"][0]["operation"] == "update"
    )


def test_export_advisorships_preserves_person_and_supervisor_fields_from_members():
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            statement_text = getattr(statement, "text", str(statement))
            if "entity_matches" in statement_text:
                return FakeResult([])
            assert "FROM advisorship_members" in statement_text
            assert params == {
                "student_role": "Student",
                "supervisor_role": "Supervisor",
            }
            return FakeResult(
                [
                    {
                        "id": 1,
                        "name": "Orientacao 1",
                        "status": "active",
                        "description": "desc",
                        "start_date": None,
                        "end_date": None,
                        "advisorship_type": "Scientific Initiation",
                        "advisorship_program": None,
                        "initiative_type_name": "Advisorship",
                        "person_id": 452,
                        "person_name": "Aluno A",
                        "supervisor_id": 2981,
                        "supervisor_name": "Paulo Sergio",
                        "fellowship_id": None,
                        "fellowship_name": None,
                        "fellowship_description": None,
                        "fellowship_value": None,
                        "sponsor_name": None,
                        "parent_id": None,
                        "parent_name": None,
                        "parent_status": None,
                        "parent_description": None,
                        "parent_start_date": None,
                        "parent_end_date": None,
                    }
                ]
            )

    exporter.initiative_ctrl._service._repository._session = FakeSession()

    exporter.export_advisorships("output/advisorships_canonical.json")

    mock_sink.export.assert_called_once()
    exported_data, output_path = mock_sink.export.call_args[0]

    assert output_path == "output/advisorships_canonical.json"
    assert exported_data[0]["name"] == "Sem Projeto Associado"
    assert exported_data[0]["campus"] is None
    assert exported_data[0]["advisorships"] == [
        {
            "id": 1,
            "name": "Orientacao 1",
            "status": "active",
            "description": "desc",
            "start_date": None,
            "end_date": None,
            "type": "Scientific Initiation",
            "initiative_type": "Advisorship",
            "person_id": 452,
            "person_name": "Aluno A",
            "supervisor_id": 2981,
            "supervisor_name": "Paulo Sergio",
            "campus": None,
            "year": None,
            "program": None,
            "provider": None,
            "fellowship": None,
        }
    ]


def test_export_advisorships_falls_back_to_legacy_person_and_supervisor_columns():
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def __init__(self):
            self.members_query_attempted = False

        def execute(self, statement, params=None):
            statement_text = getattr(statement, "text", str(statement))
            if "entity_matches" in statement_text:
                return FakeResult([])
            if "FROM advisorship_members" in statement_text:
                self.members_query_attempted = True
                raise RuntimeError("no such table: advisorship_members")

            assert "a.student_id" in statement_text
            assert "a.supervisor_id" in statement_text
            return FakeResult(
                [
                    {
                        "id": 2,
                        "name": "Orientacao Legada",
                        "status": "active",
                        "description": "legacy",
                        "start_date": None,
                        "end_date": None,
                        "advisorship_type": "Scientific Initiation",
                        "advisorship_program": None,
                        "initiative_type_name": "Advisorship",
                        "person_id": 88,
                        "person_name": "Aluno Legado",
                        "supervisor_id": 99,
                        "supervisor_name": "Supervisor Legado",
                        "fellowship_id": None,
                        "fellowship_name": None,
                        "fellowship_description": None,
                        "fellowship_value": None,
                        "sponsor_name": None,
                        "parent_id": None,
                        "parent_name": None,
                        "parent_status": None,
                        "parent_description": None,
                        "parent_start_date": None,
                        "parent_end_date": None,
                    }
                ]
            )

    fake_session = FakeSession()
    exporter.initiative_ctrl._service._repository._session = fake_session

    exporter.export_advisorships("output/advisorships_canonical.json")

    assert fake_session.members_query_attempted is True
    exported_data, _output_path = mock_sink.export.call_args[0]
    assert exported_data[0]["advisorships"][0]["person_name"] == "Aluno Legado"
    assert exported_data[0]["advisorships"][0]["supervisor_name"] == "Supervisor Legado"


def test_export_advisorships_populates_year_program_provider_from_source_report():
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            statement_text = getattr(statement, "text", str(statement))
            if "entity_matches" in statement_text:
                return FakeResult(
                    [
                        {
                            "advisorship_id": 1,
                            "source_record_id": 77,
                            "source_system": "sigpesq_advisorships",
                            "source_path": "data/sigpesq/advisorships/2023/planilha.xlsx",
                            "raw_payload_json": {
                                "Ano": "2023",
                                "Programa": "Pivic",
                                "AgFinanciadora": "FAPES",
                            },
                        }
                    ]
                )
            assert "FROM advisorship_members" in statement_text
            return FakeResult(
                [
                    {
                        "id": 1,
                        "name": "Orientacao 1",
                        "status": "active",
                        "description": "desc",
                        "start_date": None,
                        "end_date": None,
                        "advisorship_type": "Scientific Initiation",
                        "advisorship_program": None,
                        "initiative_type_name": "Advisorship",
                        "person_id": 452,
                        "person_name": "Aluno A",
                        "supervisor_id": 2981,
                        "supervisor_name": "Paulo Sergio",
                        "fellowship_id": None,
                        "fellowship_name": None,
                        "fellowship_description": None,
                        "fellowship_value": None,
                        "sponsor_name": None,
                        "parent_id": None,
                        "parent_name": None,
                        "parent_status": None,
                        "parent_description": None,
                        "parent_start_date": None,
                        "parent_end_date": None,
                    }
                ]
            )

    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)
    fake_session = FakeSession()
    exporter.initiative_ctrl._service._repository._session = fake_session

    exporter.export_advisorships("output/advisorships_canonical.json")

    exported_data, _output_path = mock_sink.export.call_args[0]
    advisor_1 = exported_data[0]["advisorships"][0]
    assert advisor_1["year"] == 2023
    assert advisor_1["program"] == "Pivic"
    assert advisor_1["provider"] == "FAPES"


def test_canonical_advisorship_fields_parity_with_source_report():
    from src.core.logic.advisorship_canonical_values import (
        AdvisorshipSourceInfo,
        report_year_from_path,
        resolve_advisorship_canonical_values,
    )

    source_path = "data/sigpesq/advisorships/2022/planilha.xlsx"
    payload = {
        "Ano": "2022",
        "Programa": "Fapes",
        "AgFinanciadora": "FUNDAÇÃO DE APOIO À PESQUISA",
    }
    values = resolve_advisorship_canonical_values(
        [
            AdvisorshipSourceInfo(
                advisorship_id=1,
                source_record_id=1,
                source_system="sigpesq_advisorships",
                source_path=source_path,
                payload=payload,
            )
        ]
    )

    assert values.year == report_year_from_path(source_path) == 2022
    assert values.year == int(payload["Ano"])
    assert values.program == payload["Programa"]
    assert values.provider == payload["AgFinanciadora"]


def test_advisorship_export_keeps_ids_unique_and_original_keys_unchanged():
    LEGACY_KEYS = [
        "id",
        "name",
        "status",
        "description",
        "start_date",
        "end_date",
        "type",
        "initiative_type",
        "person_id",
        "person_name",
        "supervisor_id",
        "supervisor_name",
        "campus",
        "fellowship",
    ]

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            statement_text = getattr(statement, "text", str(statement))
            if "entity_matches" in statement_text:
                return FakeResult(
                    [
                        {
                            "advisorship_id": 1,
                            "source_record_id": 800,
                            "source_system": "sigpesq_advisorships",
                            "source_path": (
                                "data/sigpesq/advisorships/2022/planilha.xlsx"
                            ),
                            "raw_payload_json": {
                                "Ano": "2022",
                                "Programa": "Fapes",
                                "AgFinanciadora": "FAPES",
                            },
                        }
                    ]
                )
            assert "FROM advisorship_members" in statement_text
            return FakeResult(
                [
                    {
                        "id": 1,
                        "name": "Orientacao 1",
                        "status": "active",
                        "description": "desc",
                        "start_date": None,
                        "end_date": None,
                        "advisorship_type": "Scientific Initiation",
                        "advisorship_program": None,
                        "initiative_type_name": "Advisorship",
                        "person_id": 452,
                        "person_name": "Aluno A",
                        "supervisor_id": 2981,
                        "supervisor_name": "Paulo Sergio",
                        "fellowship_id": None,
                        "fellowship_name": None,
                        "fellowship_description": None,
                        "fellowship_value": None,
                        "sponsor_name": None,
                        "parent_id": None,
                        "parent_name": None,
                        "parent_status": None,
                        "parent_description": None,
                        "parent_start_date": None,
                        "parent_end_date": None,
                    }
                ]
            )

    mock_sink = MagicMock(spec=IExportSink)
    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)
    exporter.initiative_ctrl._service._repository._session = FakeSession()

    exporter.export_advisorships("output/advisorships_canonical.json")

    exported_data, _output_path = mock_sink.export.call_args[0]
    advisories = exported_data[0]["advisorships"]
    ids = [adv["id"] for adv in advisories]
    assert len(ids) == len(set(ids)) == 1
    assert set(LEGACY_KEYS) <= set(advisories[0])
    assert {"year", "program", "provider"} <= set(advisories[0])


def test_cross_year_advisorship_export_counts_match_source_records_per_year():
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            statement_text = getattr(statement, "text", str(statement))
            if "entity_matches" in statement_text:
                return FakeResult(
                    [
                        {
                            "advisorship_id": 1,
                            "source_record_id": 701,
                            "source_system": "sigpesq_advisorships",
                            "source_path": (
                                "data/sigpesq/advisorships/2016/planilha.xlsx"
                            ),
                            "raw_payload_json": {
                                "Ano": "2016",
                                "Programa": "Pivic",
                                "AgFinanciadora": "FAPES",
                            },
                        },
                        {
                            "advisorship_id": 2,
                            "source_record_id": 702,
                            "source_system": "sigpesq_advisorships",
                            "source_path": (
                                "data/sigpesq/advisorships/2025/planilha.xlsx"
                            ),
                            "raw_payload_json": {
                                "Ano": "2025",
                                "Programa": "Pibic",
                                "AgFinanciadora": "FAPES",
                            },
                        },
                    ]
                )
            assert "FROM advisorship_members" in statement_text
            rows = []
            for idx in (1, 2):
                rows.append(
                    {
                        "id": idx,
                        "name": f"Orientacao {idx}",
                        "status": "active",
                        "description": "desc",
                        "start_date": None,
                        "end_date": None,
                        "advisorship_type": "Scientific Initiation",
                        "advisorship_program": None,
                        "initiative_type_name": "Advisorship",
                        "person_id": idx,
                        "person_name": f"Aluno {idx}",
                        "supervisor_id": 2981,
                        "supervisor_name": "Paulo Sergio",
                        "fellowship_id": None,
                        "fellowship_name": None,
                        "fellowship_description": None,
                        "fellowship_value": None,
                        "sponsor_name": None,
                        "parent_id": None,
                        "parent_name": None,
                        "parent_status": None,
                        "parent_description": None,
                        "parent_start_date": None,
                        "parent_end_date": None,
                    }
                )
            return FakeResult(rows)

    mock_sink = MagicMock(spec=IExportSink)
    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)
    exporter.initiative_ctrl._service._repository._session = FakeSession()

    exporter.export_advisorships("output/advisorships_canonical.json")

    exported_data, _output_path = mock_sink.export.call_args[0]
    advisories = exported_data[0]["advisorships"]
    counts_by_year = {}
    for adv in advisories:
        counts_by_year[adv["year"]] = counts_by_year.get(adv["year"], 0) + 1
    assert counts_by_year[2016] == 1
    assert counts_by_year[2025] == 1
    by_id = {adv["id"]: adv for adv in advisories}
    assert by_id[1]["year"] == 2016
    assert by_id[1]["program"] == "Pivic"
    assert by_id[2]["year"] == 2025
    assert by_id[2]["program"] == "Pibic"


def test_fetch_researcher_advisorship_rows_returns_person_id_from_members_query():
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def execute(self, statement, params=None):
            statement_text = getattr(statement, "text", str(statement))
            assert "am_std.student_id AS person_id" in statement_text
            assert params == {
                "student_role": "Student",
                "supervisor_role": "Supervisor",
            }
            return FakeResult(
                [
                    {
                        "supervisor_id": 2981,
                        "person_id": 452,
                        "id": 916,
                        "name": "Orientacao 1",
                        "status": "Concluded",
                        "start_date": None,
                        "end_date": None,
                        "type_name": "Research Project",
                        "advisorship_type": None,
                        "person_name": "Andre Porto",
                    }
                ]
            )

    rows = CanonicalDataExporter._fetch_researcher_advisorship_rows(FakeSession())

    assert rows[0]["person_id"] == 452
    assert rows[0]["person_name"] == "Andre Porto"


def test_export_researchers_includes_person_id_in_advisorships():
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.InitiativeController"),
        patch("src.core.logic.canonical_exporter.ArticleController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)

    mock_researcher = MagicMock()
    mock_researcher.to_dict.return_value = {"id": 2981, "name": "Paulo Sergio"}
    exporter.researcher_ctrl.get_all.return_value = [mock_researcher]
    exporter.initiative_ctrl.get_all.return_value = []
    exporter.initiative_ctrl.list_initiative_types.return_value = []
    exporter._get_session = lambda: None
    exporter._get_campus_resolver = lambda: MagicMock(
        get_campus=lambda *_args, **_kwargs: None
    )
    exporter._fetch_researcher_advisorship_rows = lambda _session: [
        {
            "supervisor_id": 2981,
            "person_id": 452,
            "id": 916,
            "name": "APRENDIZAGEM SIGNIFICATIVA",
            "status": "Concluded",
            "start_date": None,
            "end_date": None,
            "type_name": "Research Project",
            "advisorship_type": None,
            "person_name": "Andre Porto",
        }
    ]

    exporter.export_researchers("output/researchers_canonical.json")

    exported_by_path = {
        call_args[0][1]: call_args[0][0]
        for call_args in mock_sink.export.call_args_list
    }

    exported_data = exported_by_path["output/researchers_canonical.json"]
    assert exported_data[0]["advisorships"][0]["person_id"] == 452
    assert exported_data[0]["advisorships"][0]["person_name"] == "Andre Porto"
    assert exported_by_path["output/researchers_only_canonical.json"] == []
    assert exported_by_path["output/null_researchers_canonical.json"][0]["id"] == 2981


def test_export_researchers_backfills_participant_only_people_from_projects_and_advisorships():
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.PersonController") as MockPersonCtrl,
        patch("src.core.logic.canonical_exporter.InitiativeController"),
        patch("src.core.logic.canonical_exporter.ArticleController"),
        patch("eo_lib.TeamController") as MockTeamCtrl,
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)

        exporter.researcher_ctrl.get_all.return_value = []
        exporter.initiative_ctrl.list_initiative_types.return_value = [
            {"id": 1, "name": "Research Project"}
        ]

        mock_initiative = SimpleNamespace(
            id=916,
            name="Projeto Wilsiman",
            status="active",
            initiative_type_id=1,
            demandante=None,
        )
        exporter.initiative_ctrl.get_all.return_value = [mock_initiative]
        exporter.initiative_ctrl.get_teams.return_value = [{"id": 91}]

        team_member = SimpleNamespace(
            person_id=652,
            person=SimpleNamespace(name="Wilsiman Santos Evangelista Silva"),
            role=SimpleNamespace(name="Student"),
            start_date=None,
            end_date=None,
        )
        MockTeamCtrl.return_value.get_members.return_value = [team_member]

        MockPersonCtrl.return_value.get_all.return_value = [
            SimpleNamespace(
                id=652,
                name="Wilsiman Santos Evangelista Silva",
                identification_id="wilsiman@example.com",
                birthday=None,
            )
        ]

        exporter._get_session = lambda: None
        exporter._get_campus_resolver = lambda: MagicMock(
            get_campus=lambda *_args, **_kwargs: None
        )
        exporter._fetch_researcher_advisorship_rows = lambda _session: []
        exporter._fetch_person_project_roles = lambda _session: {652: ["Student"]}
        exporter._fetch_person_research_group_roles = lambda _session: {}
        exporter._fetch_person_advisorship_roles = lambda _session: {652: ["Student"]}
        exporter._fetch_person_institutional_email_flags = lambda _session: {}
        exporter._fetch_person_academic_reference_counts = lambda _session: {}

        exporter.export_researchers("output/researchers_canonical.json")

        exported_by_path = {
            call_args[0][1]: call_args[0][0]
            for call_args in mock_sink.export.call_args_list
        }

        assert exported_by_path["output/researchers_canonical.json"] == [
            {
                "id": 652,
                "name": "Wilsiman Santos Evangelista Silva",
                "identification_id": "1dade2367ac4@anon.lgpd",
                "birthday": None,
                "cnpq_url": None,
                "google_scholar_url": None,
                "resume": None,
                "citation_names": None,
                "initiatives": [
                    {
                        "id": 916,
                        "name": "Projeto Wilsiman",
                        "status": "active",
                        "initiative_type": {"id": 1, "name": "Research Project"},
                        "demandante": None,
                        "role": "Student",
                        "campus": None,
                    }
                ],
                "research_groups": [],
                "knowledge_areas": [],
                "academic_education": [],
                "articles": [],
                "advisorships": [],
                "classification": "student",
                "classification_confidence": "high",
                "classification_note": None,
                "role_evidence": {
                    "project_roles": ["Student"],
                    "research_group_roles": [],
                    "advisorship_roles": ["Student"],
                    "has_institutional_email": False,
                    "academic_reference_count": 0,
                },
                "was_student": True,
                "was_staff": False,
                "campus": None,
            }
        ]
        assert (
            exported_by_path["output/students_canonical.json"]
            == exported_by_path["output/researchers_canonical.json"]
        )
        assert exported_by_path["output/researchers_only_canonical.json"] == []
        assert exported_by_path["output/outside_ifes_canonical.json"] == []
        assert exported_by_path["output/null_researchers_canonical.json"] == []


def test_export_researchers_backfills_group_only_participants_from_people():
    mock_sink = MagicMock(spec=IExportSink)

    with (
        patch("src.core.logic.canonical_exporter.OrganizationController"),
        patch("src.core.logic.canonical_exporter.CampusController"),
        patch("src.core.logic.canonical_exporter.KnowledgeAreaController"),
        patch("src.core.logic.canonical_exporter.ResearcherController"),
        patch("src.core.logic.canonical_exporter.PersonController") as MockPersonCtrl,
        patch("src.core.logic.canonical_exporter.InitiativeController"),
        patch("src.core.logic.canonical_exporter.ArticleController"),
    ):
        exporter = CanonicalDataExporter(sink=mock_sink)

        class FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        class FakeSession:
            def execute(self, statement, params=None):
                statement_text = getattr(statement, "text", str(statement))
                if "SELECT tm.person_id, rg.id, t.name" in statement_text:
                    return FakeResult([(77, 501, "Grupo Integrado")])
                if (
                    "FROM research_groups rg" in statement_text
                    and "role_name" in statement_text
                ):
                    return FakeResult([{"person_id": 77, "role_name": "Leader"}])
                if (
                    "FROM persons p" in statement_text
                    and "person_emails" in statement_text
                ):
                    return FakeResult(
                        [{"person_id": 77, "identification_id": None, "email": None}]
                    )
                if "FROM academic_educations ae" in statement_text:
                    return FakeResult([])
                raise AssertionError(statement_text)

        exporter.researcher_ctrl.get_all.return_value = []
        exporter.initiative_ctrl.get_all.return_value = []
        exporter.initiative_ctrl.list_initiative_types.return_value = []
        MockPersonCtrl.return_value.get_all.return_value = [
            SimpleNamespace(
                id=77,
                name="Pesquisador de Grupo",
                identification_id=None,
                birthday=None,
            )
        ]

        exporter._get_session = lambda: FakeSession()
        exporter._get_campus_resolver = lambda: MagicMock(
            get_campus=lambda *_args, **_kwargs: None
        )
        exporter._fetch_researcher_advisorship_rows = lambda _session: []

        exporter.export_researchers("output/researchers_canonical.json")

        exported_by_path = {
            call_args[0][1]: call_args[0][0]
            for call_args in mock_sink.export.call_args_list
        }

        exported_data = exported_by_path["output/researchers_canonical.json"]
        assert exported_data[0]["id"] == 77
        assert exported_data[0]["name"] == "Pesquisador de Grupo"
        assert exported_data[0]["research_groups"] == [
            {"id": 501, "name": "Grupo Integrado", "campus": None}
        ]
        assert exported_data[0]["classification"] == "researcher"
        assert exported_data[0]["classification_confidence"] == "high"
        assert exported_data[0]["role_evidence"]["research_group_roles"] == ["Leader"]
        assert exported_data[0]["cnpq_url"] is None
        assert exported_data[0]["google_scholar_url"] is None
        assert exported_data[0]["resume"] is None
        assert exported_data[0]["citation_names"] is None
        assert (
            exported_by_path["output/researchers_only_canonical.json"]
            == exported_by_path["output/researchers_canonical.json"]
        )
        assert exported_by_path["output/students_canonical.json"] == []
        assert exported_by_path["output/outside_ifes_canonical.json"] == []
        assert exported_by_path["output/null_researchers_canonical.json"] == []


def test_build_classification_payload_marks_student_from_student_evidence_only():
    payload = CanonicalDataExporter._build_classification_payload(
        project_roles=["Student"],
        advisorship_roles=["Student"],
    )

    assert payload["classification"] == "student"
    assert payload["classification_confidence"] == "high"
    assert payload["classification_note"] is None
    assert payload["was_student"] is True
    assert payload["was_staff"] is False


def test_build_classification_payload_marks_researcher_from_supervisor_evidence():
    payload = CanonicalDataExporter._build_classification_payload(
        advisorship_roles=["Supervisor"],
    )

    assert payload["classification"] == "researcher"
    assert payload["classification_confidence"] == "high"
    assert payload["classification_note"] is None
    assert payload["was_student"] is False
    assert payload["was_staff"] is True


def test_build_classification_payload_marks_researcher_and_keeps_student_history():
    payload = CanonicalDataExporter._build_classification_payload(
        project_roles=["Student", "Researcher"],
        research_group_roles=["Pesquisador"],
        advisorship_roles=["Student"],
    )

    assert payload["classification"] == "researcher"
    assert payload["classification_note"] is None
    assert payload["was_student"] is True
    assert payload["was_staff"] is True


def test_build_classification_payload_marks_external_classification_for_project_only_staff():
    payload = CanonicalDataExporter._build_classification_payload(
        project_roles=["Coordinator"],
    )

    assert payload["classification"] == "outside_ifes"
    assert payload["classification_confidence"] == "medium"
    assert (
        payload["classification_note"]
        == "project_only_staff_without_institutional_signals"
    )
    assert payload["was_student"] is False
    assert payload["was_staff"] is False


def test_build_classification_payload_keeps_null_for_mixed_weak_evidence():
    payload = CanonicalDataExporter._build_classification_payload(
        project_roles=["Student", "Researcher"],
    )

    assert payload["classification"] is None
    assert payload["classification_confidence"] == "low"
    assert payload["classification_note"] is None
    assert payload["was_student"] is True
    assert payload["was_staff"] is False


def test_build_classification_payload_marks_student_for_mixed_project_roles_with_strong_student_signal():
    payload = CanonicalDataExporter._build_classification_payload(
        project_roles=["Student", "Researcher"],
        advisorship_roles=["Student"],
    )

    assert payload["classification"] == "student"
    assert payload["classification_confidence"] == "medium"
    assert (
        payload["classification_note"] == "student_signal_overrides_project_staff_role"
    )
    assert payload["was_student"] is True
    assert payload["was_staff"] is False


def test_build_classification_payload_marks_academic_reference_only_note():
    payload = CanonicalDataExporter._build_classification_payload(
        academic_reference_count=2,
    )

    assert payload["classification"] is None
    assert payload["classification_confidence"] == "low"
    assert payload["classification_note"] == "academic_advisor_reference_only"
    assert payload["role_evidence"]["academic_reference_count"] == 2
