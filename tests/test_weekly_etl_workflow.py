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


def test_the_raw_download_rotation_can_be_tuned_on_dispatch():
    # Spec 023: share and full refresh reach the weekly as environment.
    workflow, steps = _steps()
    trigger = workflow.get("on") or workflow.get(True)
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["refresh_share"]["type"] == "string"
    assert inputs["refresh_share"]["default"] == ""
    assert inputs["full_refresh"]["type"] == "boolean"
    assert inputs["full_refresh"]["default"] is False
    env = _step(steps, "Run weekly flows")["env"]
    assert env["HORIZON_REFRESH_SHARE"] == "${{ github.event.inputs.refresh_share }}"
    assert env["HORIZON_FULL_REFRESH"] == "${{ github.event.inputs.full_refresh }}"


def test_the_portal_early_stop_can_be_tuned_on_dispatch():
    # Spec 024: four inputs reach the weekly as environment; scheduled runs
    # pass none, so every variable is blank and the defaults apply.
    workflow, steps = _steps()
    trigger = workflow.get("on") or workflow.get(True)
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["early_stop"]["type"] == "boolean"
    assert inputs["early_stop"]["default"] is True
    for name in ("cnpq_stop_after", "cnpq_budget_min", "lattes_stop_after"):
        assert inputs[name]["type"] == "string" and inputs[name]["default"] == ""
    assert len(inputs) <= 10
    env = _step(steps, "Run weekly flows")["env"]
    for variable, name in (
        ("HORIZON_PORTAL_EARLY_STOP", "early_stop"),
        ("HORIZON_CNPQ_STOP_AFTER_FAILURES", "cnpq_stop_after"),
        ("HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN", "cnpq_budget_min"),
        ("HORIZON_LATTES_STOP_AFTER_FAILURES", "lattes_stop_after"),
    ):
        assert env[variable] == "${{ github.event.inputs.%s }}" % name


def test_makefile_forwards_the_portal_early_stop_settings():
    makefile = Path("Makefile").read_text()
    for variable in (
        'HORIZON_PORTAL_EARLY_STOP="$(EARLY_STOP)"',
        'HORIZON_CNPQ_STOP_AFTER_FAILURES="$(CNPQ_STOP_AFTER)"',
        'HORIZON_CNPQ_DOWNLOAD_BUDGET_MIN="$(CNPQ_BUDGET_MIN)"',
        'HORIZON_LATTES_STOP_AFTER_FAILURES="$(LATTES_STOP_AFTER)"',
    ):
        assert variable in makefile
    for target in ("weekly-flows:", "sync-cnpq:", "ingest-lattes-download:"):
        start = makefile.index(target)
        recipe = makefile[start : makefile.index("\n\n", start)]
        assert "$(PORTAL_STOP_ENV)" in recipe
