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
