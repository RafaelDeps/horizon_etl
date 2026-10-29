from pathlib import Path


def test_weekly_etl_workflow_runs_weekly_flows_with_notifications():
    workflow = Path(".github/workflows/weekly-etl.yml").read_text()

    assert 'cron: "0 6 * * 6"' in workflow
    assert "workflow_dispatch:" in workflow
    assert (
        "HORIZON_TELEGRAM_BOT_TOKEN: ${{ secrets.HORIZON_TELEGRAM_BOT_TOKEN }}"
        in workflow
    )
    assert (
        "HORIZON_TELEGRAM_CHAT_ID: ${{ secrets.HORIZON_TELEGRAM_CHAT_ID }}" in workflow
    )
    assert "make weekly-flows" in workflow
    assert "make full-refresh" not in workflow
    assert "timeout-minutes: 300" in workflow


def test_makefile_weekly_flows_runs_weekly_pipeline_entrypoint():
    makefile = Path("Makefile").read_text()

    # Isolate the weekly-flows recipe without assuming target ordering.
    start = makefile.index("weekly-flows:")
    rest = makefile[start:]
    end = rest.index("\n\n") if "\n\n" in rest else len(rest)
    target = rest[:end]

    # Spec 021: the weekly keeps the persistent database (db-ensure creates a
    # missing one); a rebuild is make full-refresh or db-reset.
    assert "weekly-flows: db-ensure prefect-server" in target
    assert 'app.py weekly "$(WEEKLY_CAMPUS)" "$(OUTPUT_DIR)"' in target
    assert "app.py all_sources" not in target
    assert "app.py export_canonical" not in target


def _steps():
    import yaml

    workflow = yaml.safe_load(Path(".github/workflows/weekly-etl.yml").read_text())
    return workflow, workflow["jobs"]["run-etl"]["steps"]


def _step(steps, name):
    return next(s for s in steps if s.get("name") == name)


def test_the_previous_run_is_restored_before_the_weekly_flows():
    # Spec 022: the restore runs first, never fails the run, uses the
    # workflow's own token, and can be skipped to force a rebuild.
    workflow, steps = _steps()
    names = [s.get("name") for s in steps]
    restore_at = names.index("Restore previous weekly run")
    assert restore_at < names.index("Run weekly flows")
    step = steps[restore_at]
    assert step["run"] == "make restore-weekly"
    assert step["continue-on-error"] is True
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert step["env"]["FRESH_DATABASE"] == "${{ github.event.inputs.fresh_database }}"
    trigger = workflow.get("on") or workflow.get(True)
    fresh = trigger["workflow_dispatch"]["inputs"]["fresh_database"]
    assert fresh["type"] == "boolean" and fresh["default"] is False


def test_the_artifact_carries_what_the_next_run_restores():
    _workflow, steps = _steps()
    upload = _step(steps, "Upload ETL artifacts")["with"]
    paths = upload["path"].split()
    assert {"data", "db/horizon.db", "cache"} <= set(paths)
    assert "!data/exports/exports_canonical.zip" in paths
    assert upload["retention-days"] == 90
    compress = _step(steps, "Compress large export files")["run"]
    assert "! -path 'data/raw/*'" in compress
