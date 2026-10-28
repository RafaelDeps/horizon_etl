import json
import os
from contextlib import ExitStack
from unittest.mock import patch

from src.flows.exports.canonical_data import export_canonical_data_flow


def test_export_canonical_data_flow_calls_tracking_exports_individually(tmp_path):
    output_dir = str(tmp_path / "exports")

    with ExitStack() as stack:
        organizations_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_organizations_task")
        )
        campuses_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_campuses_task")
        )
        knowledge_areas_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_knowledge_areas_task")
        )
        researchers_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_researchers_task")
        )
        researchers_tracking_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_researchers_tracking_task")
        )
        groups_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_groups_task")
        )
        initiatives_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_initiatives_task")
        )
        initiatives_tracking_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_initiatives_tracking_task")
        )
        initiative_types_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_initiative_types_task")
        )
        articles_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_articles_task")
        )
        awards_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_awards_task")
        )
        languages_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_languages_task")
        )
        professional_activities_task = stack.enter_context(
            patch(
                "src.flows.exports.canonical_data.export_professional_activities_task"
            )
        )
        research_productions_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_research_productions_task")
        )
        advisorships_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_advisorships_task")
        )
        advisorships_tracking_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_advisorships_tracking_task")
        )
        ingestion_runs_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_ingestion_runs_task")
        )
        source_records_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_source_records_task")
        )
        entity_matches_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_entity_matches_task")
        )
        attribute_assertions_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_attribute_assertions_task")
        )
        entity_change_logs_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_entity_change_logs_task")
        )
        fellowships_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_fellowships_task")
        )
        advisorship_analytics_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_advisorship_analytics_task")
        )
        people_relationship_graph_flow = stack.enter_context(
            patch(
                "src.flows.exports.canonical_data.export_people_relationship_graph_flow"
            )
        )
        for _graph_flow in (
            "export_people_collaboration_graph_flow",
            "export_researchers_collaboration_graph_flow",
            "export_students_collaboration_graph_flow",
            "export_outside_ifes_collaboration_graph_flow",
            "export_null_researchers_collaboration_graph_flow",
            "export_research_group_membership_graphs_manifest_flow",
        ):
            stack.enter_context(
                patch(f"src.flows.exports.canonical_data.{_graph_flow}")
            )
        horizon_ids_task = stack.enter_context(
            patch("src.flows.exports.canonical_data.export_horizon_ids_task")
        )
        stack.enter_context(patch("src.flows.exports.canonical_data.zip_exports_task"))
        makedirs = stack.enter_context(patch("os.makedirs"))
        export_canonical_data_flow.fn(output_dir=output_dir, campus="Serra")

    makedirs.assert_called_once_with(output_dir, exist_ok=True)
    organizations_task.assert_called_once_with(output_dir)
    campuses_task.assert_called_once_with(output_dir, "Serra")
    knowledge_areas_task.assert_called_once_with(output_dir)
    researchers_task.assert_called_once_with(output_dir)
    researchers_tracking_task.assert_called_once_with(output_dir)
    groups_task.assert_called_once_with(output_dir, "Serra")
    initiatives_task.assert_called_once_with(output_dir)
    initiatives_tracking_task.assert_called_once_with(output_dir)
    initiative_types_task.assert_called_once_with(output_dir)
    articles_task.assert_called_once_with(output_dir)
    awards_task.assert_called_once_with(output_dir)
    languages_task.assert_called_once_with(output_dir)
    professional_activities_task.assert_called_once_with(output_dir)
    research_productions_task.assert_called_once_with(output_dir)
    advisorships_task.assert_called_once_with(output_dir)
    advisorships_tracking_task.assert_called_once_with(output_dir)
    ingestion_runs_task.assert_called_once_with(output_dir)
    source_records_task.assert_called_once_with(output_dir)
    entity_matches_task.assert_called_once_with(output_dir)
    attribute_assertions_task.assert_called_once_with(output_dir)
    entity_change_logs_task.assert_called_once_with(output_dir)
    fellowships_task.assert_called_once_with(output_dir)
    advisorship_analytics_task.assert_called_once_with(output_dir)
    people_relationship_graph_flow.assert_called_once_with(output_dir=output_dir)
    horizon_ids_task.assert_called_once_with(output_dir)


def test_horizon_ids_file_is_written_stable_and_zipped(tmp_path, monkeypatch):
    """Spec 020: the id file has one row per entity, is identical across two
    exports apart from generated_at, and lands in the export zip."""
    import json
    import zipfile

    from src.flows.exports.canonical_data import (
        export_horizon_ids_task,
        zip_exports_task,
    )
    from tests.test_horizon_id_assigner import _assign, _build

    db = tmp_path / "ids.db"
    _build(db, order_seed=4)
    _, rows = _assign(db)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    out = tmp_path / "exports"
    out.mkdir()

    export_horizon_ids_task.fn(str(out))
    first = json.loads((out / "horizon_ids_canonical.json").read_text())
    export_horizon_ids_task.fn(str(out))
    second = json.loads((out / "horizon_ids_canonical.json").read_text())

    assert len(first["ids"]) == len(rows)
    assert set(first["ids"][0]) == {
        "entity_type",
        "id",
        "horizon_id",
        "rule",
        "natural_key",
        "parent_horizon_id",
    }
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second

    aliases = json.loads((out / "horizon_id_aliases_canonical.json").read_text())
    assert aliases["aliases"] == [] and aliases["rule_version"] == 1

    zip_exports_task.fn(str(out))
    with zipfile.ZipFile(out / "exports_canonical.zip") as zf:
        assert "horizon_ids_canonical.json" in zf.namelist()
        assert "horizon_id_aliases_canonical.json" in zf.namelist()


def test_horizon_ids_export_without_ids_writes_nothing(tmp_path, monkeypatch):
    from src.flows.exports.canonical_data import export_horizon_ids_task

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    export_horizon_ids_task.fn(str(tmp_path))
    assert not (tmp_path / "horizon_ids_canonical.json").exists()
    assert not (tmp_path / "horizon_id_aliases_canonical.json").exists()


def _key_sets(value, prefix=""):
    """Every key path of a JSON document: the record fields, nested ones too."""
    out = set()
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(prefix + key)
            out |= _key_sets(item, prefix + key + ".")
    elif isinstance(value, list):
        for item in value:
            out |= _key_sets(item, prefix + "[].")
    return out


def test_existing_exports_keep_their_fields_with_horizon_ids(tmp_path):
    """Spec 020 (FR-015): the same database exported before and after
    assign_horizon_ids gives the same fields in every existing file; only the
    two new files are added. Runs the real phases on two local CVs."""
    import glob
    import shutil
    import subprocess
    import sys

    import pytest

    from tests.test_idempotent_rerun import CVS, REPO, _env

    if len(CVS) < 2:
        pytest.skip("no local Lattes JSON")
    work = tmp_path / "work"
    (work / "data" / "lattes_json").mkdir(parents=True)
    for cv in sorted(CVS, key=os.path.getsize)[:2]:
        shutil.copy(cv, work / "data" / "lattes_json")
    env = _env(tmp_path / "fields.db")

    def run(*args):
        done = subprocess.run(
            [sys.executable, *args], cwd=work, env=env, capture_output=True, text=True
        )
        assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]

    def export(name):
        out = work / name
        run(os.path.join(REPO, "app.py"), "export_canonical", str(out))
        return {
            os.path.basename(p): _key_sets(json.load(open(p, encoding="utf-8")))
            for p in glob.glob(str(out / "*_canonical.json"))
        }

    run(os.path.join(REPO, "db", "create_db.py"))
    run(os.path.join(REPO, "app.py"), "ingest_lattes_projects")
    # The export also needs a research group, which the CVs do not create.
    import sqlite3

    con = sqlite3.connect(tmp_path / "fields.db")
    (team_id,) = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM teams").fetchone()
    con.execute("INSERT INTO teams (id, name) VALUES (?, 'Grupo Teste')", (team_id,))
    con.execute(
        "INSERT INTO research_groups (id, cnpq_url) VALUES "
        "(?, 'http://dgp.cnpq.br/dgp/espelhogrupo/123')",
        (team_id,),
    )
    con.commit()
    con.close()
    before = export("before")
    run(os.path.join(REPO, "app.py"), "assign_horizon_ids")
    after = export("after")

    new_files = {"horizon_ids_canonical.json", "horizon_id_aliases_canonical.json"}
    assert len(before) > 10  # the comparison covers the real export set
    assert set(after) - set(before) == new_files
    assert {name: after[name] for name in before} == before
