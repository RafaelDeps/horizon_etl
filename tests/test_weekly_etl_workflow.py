from pathlib import Path


def test_weekly_etl_workflow_runs_weekly_flows_with_notifications():
    workflow = Path(".github/workflows/weekly-etl.yml").read_text()

    assert 'cron: "0 2 * * 6"' in workflow
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
    # Spec 022 asked for data, db and cache in the upload; spec 029 moved them
    # into the sealed bundle that "Prepare artifact" stages in artifact_out.
    _workflow, steps = _steps()
    upload = _step(steps, "Upload ETL artifacts")["with"]
    assert upload["path"].strip() == "artifact_out"
    assert upload["retention-days"] == 90


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
    # GitHub raised the workflow_dispatch input limit from 10 to 25 on
    # 2025-12-04 (changelog); spec 025 takes the total to 11.
    assert len(inputs) <= 25
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


def test_the_second_try_of_access_check_pages_can_be_tuned_on_dispatch():
    # Spec 025: two inputs reach the weekly as environment; blank = defaults.
    workflow, steps = _steps()
    trigger = workflow.get("on") or workflow.get(True)
    inputs = trigger["workflow_dispatch"]["inputs"]
    for name in ("lattes_retry_workers", "lattes_retry_pause_min"):
        assert inputs[name]["type"] == "string" and inputs[name]["default"] == ""
    env = _step(steps, "Run weekly flows")["env"]
    assert env["HORIZON_LATTES_RETRY_WORKERS"] == (
        "${{ github.event.inputs.lattes_retry_workers }}"
    )
    assert env["HORIZON_LATTES_RETRY_PAUSE_MIN"] == (
        "${{ github.event.inputs.lattes_retry_pause_min }}"
    )


def test_makefile_forwards_the_second_try_settings_only_when_set():
    import subprocess

    def dry_run(*args):
        return subprocess.run(
            ["make", "-n", "weekly-flows", *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    forwarded = dry_run("LATTES_RETRY_WORKERS=0", "LATTES_RETRY_PAUSE_MIN=1")
    assert 'HORIZON_LATTES_RETRY_WORKERS="0"' in forwarded
    assert 'HORIZON_LATTES_RETRY_PAUSE_MIN="1"' in forwarded
    plain = dry_run()
    assert "HORIZON_LATTES_RETRY" not in plain


# --- Spec 029: the artifact is an allow-list and the state travels sealed ---


def test_large_exports_are_no_longer_compressed_into_the_artifact():
    _, steps = _steps()
    assert "Compress large export files" not in [s.get("name") for s in steps]


def test_prepare_artifact_seals_the_state_with_the_state_key():
    _, steps = _steps()
    names = [s.get("name") for s in steps]
    step = _step(steps, "Prepare artifact")
    assert step["if"] == "always()"
    assert step["continue-on-error"] is True
    assert step["run"] == "make seal-weekly"
    assert step["env"]["HORIZON_STATE_KEY"] == "${{ secrets.HORIZON_STATE_KEY }}"
    assert names.index("Prepare artifact") > names.index("Run weekly flows")
    assert names.index("Prepare artifact") < names.index("Upload ETL artifacts")


def test_the_state_key_reaches_only_restore_and_seal():
    workflow, steps = _steps()
    assert "HORIZON_STATE_KEY" not in str(workflow["jobs"]["run-etl"].get("env", {}))
    assert "HORIZON_STATE_KEY" not in str(workflow.get("env", {}))
    holders = {s.get("name") for s in steps if "HORIZON_STATE_KEY" in str(s)}
    assert holders == {"Restore previous weekly run", "Prepare artifact"}
    restore_env = _step(steps, "Restore previous weekly run")["env"]
    assert restore_env["HORIZON_STATE_KEY"] == "${{ secrets.HORIZON_STATE_KEY }}"
    assert (
        restore_env["HORIZON_STATE_KEY_PREVIOUS"]
        == "${{ secrets.HORIZON_STATE_KEY_PREVIOUS }}"
    )
    # The key is never an argument or echoed.
    for step in steps:
        assert "HORIZON_STATE_KEY" not in str(step.get("run", ""))


def test_upload_takes_the_staged_folder_only():
    _, steps = _steps()
    step = _step(steps, "Upload ETL artifacts")
    assert step["if"] == "always()"
    assert step["with"]["name"] == "weekly-etl-artifacts"
    assert step["with"]["path"].strip() == "artifact_out"


def test_the_weekly_workflow_has_no_pull_request_trigger():
    workflow, _ = _steps()
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers


def test_required_secrets_do_not_include_the_state_key():
    _, steps = _steps()
    validate = _step(steps, "Validate required secrets")["run"]
    assert "HORIZON_STATE_KEY" not in validate


# --- Spec 029: one official key; the archive gate in the weekly and in CI ---

ARCHIVE_CHECK = "python -m src.scripts.check_publishable_archive"


def test_the_weekly_checks_the_archive_before_committing_it():
    _, steps = _steps()
    run = _step(steps, "Commit exports_canonical.zip if changed")["run"]
    command = (
        f"{ARCHIVE_CHECK} data/exports/exports_canonical.zip --ref HEAD --warn-only"
    )
    assert command in run
    assert run.index(command) < run.index("git add")


def test_ci_refuses_a_changed_archive_that_fails_the_check():
    import yaml

    ci = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    steps = ci["jobs"]["test"]["steps"]
    check = next(s for s in steps if ARCHIVE_CHECK in s.get("run", ""))
    run = check["run"]
    assert "--warn-only" not in run
    assert "git diff --name-only" in run
    assert "data/exports/exports_canonical.zip" in run
    assert "--ref" in run
    # CI never holds a key.
    assert "HORIZON_STATE_KEY" not in str(ci)
    assert "HORIZON_PII_HMAC_KEY" not in str(ci)


def test_the_extraction_retry_can_be_tuned_on_dispatch():
    # Spec 031: four blank inputs reach the weekly as environment; blank means
    # the defaults, so scheduled runs use them.
    workflow, steps = _steps()
    trigger = workflow.get("on") or workflow.get(True)
    inputs = trigger["workflow_dispatch"]["inputs"]
    env = _step(steps, "Run weekly flows")["env"]
    for name, var in [
        ("extract_retries", "HORIZON_EXTRACT_RETRIES"),
        ("extract_pause_s", "HORIZON_EXTRACT_PAUSE_S"),
        ("extract_first_wait_s", "HORIZON_EXTRACT_FIRST_WAIT_S"),
        ("extract_wait_budget_min", "HORIZON_EXTRACT_WAIT_BUDGET_MIN"),
    ]:
        assert inputs[name]["type"] == "string"
        assert inputs[name]["default"] == ""
        assert env[var] == "${{ github.event.inputs.%s }}" % name
    # GitHub accepts at most 25 dispatch inputs.
    assert len(inputs) <= 25


def test_the_makefile_passes_the_extraction_settings_only_when_set():
    makefile = Path("Makefile").read_text()
    assert "EXTRACT_ENV = $(if $(EXTRACT_RETRIES)," in makefile
    assert "$(EXTRACT_ENV) \\\n\t\t$(FLOW_PYTHON) app.py weekly" in makefile
    assert "@$(EXTRACT_ENV) $(FLOW_PYTHON) app.py extract_project_files" in makefile
