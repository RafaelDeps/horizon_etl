"""Spec 029: the archive is built by its own phase, so ``export_canonical``
does not build it and ``zip_exports`` does."""

import sys
from unittest.mock import MagicMock, patch

import src.flows.exports.canonical_data as canonical_data


def _patch_all_but(stack, keep):
    """Replaces every task and flow of the module except ``keep``."""
    mocks = {}
    for name in dir(canonical_data):
        if name in keep or not name.endswith(("_task", "_flow")):
            continue
        mocks[name] = stack.enter_context(
            patch.object(canonical_data, name, MagicMock())
        )
    return mocks


def test_export_flow_zips_by_default(tmp_path):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = _patch_all_but(stack, {"export_canonical_data_flow"})
        canonical_data.export_canonical_data_flow.fn(output_dir=str(tmp_path))

    mocks["zip_exports_task"].assert_called_once_with(str(tmp_path))


def test_export_flow_does_not_zip_when_told_not_to(tmp_path):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = _patch_all_but(stack, {"export_canonical_data_flow"})
        canonical_data.export_canonical_data_flow.fn(
            output_dir=str(tmp_path), zip_exports=False
        )

    mocks["zip_exports_task"].assert_not_called()
    mocks["export_horizon_ids_task"].assert_called_once()


def test_zip_exports_flow_calls_only_the_zip_task(tmp_path):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = _patch_all_but(stack, {"zip_exports_flow"})
        canonical_data.zip_exports_flow.fn(output_dir=str(tmp_path))

    mocks["zip_exports_task"].assert_called_once_with(str(tmp_path))
    for name, mock in mocks.items():
        if name != "zip_exports_task":
            mock.assert_not_called()


def _run_app(monkeypatch, *argv):
    import app

    monkeypatch.setattr(sys, "argv", ["app.py", *argv])
    export_flow, zip_flow = MagicMock(), MagicMock()
    monkeypatch.setattr(app, "export_canonical_data_flow", export_flow)
    monkeypatch.setattr(app, "zip_exports_flow", zip_flow)
    app.main()
    return export_flow, zip_flow


def test_export_canonical_command_does_not_zip(monkeypatch):
    export_flow, zip_flow = _run_app(monkeypatch, "export_canonical", "out_dir")

    export_flow.assert_called_once()
    assert export_flow.call_args.kwargs["zip_exports"] is False
    assert export_flow.call_args.kwargs["output_dir"] == "out_dir"
    zip_flow.assert_not_called()


def test_zip_exports_command_runs_the_zip_flow(monkeypatch):
    export_flow, zip_flow = _run_app(monkeypatch, "zip_exports", "out_dir")

    zip_flow.assert_called_once_with(output_dir="out_dir")
    export_flow.assert_not_called()


def test_zip_exports_command_defaults_to_the_exports_folder(monkeypatch):
    _, zip_flow = _run_app(monkeypatch, "zip_exports")

    zip_flow.assert_called_once_with(output_dir="data/exports")


# Spec 038: the Parquet archive is built from the JSON archive, right after it.


def test_export_flow_builds_the_parquet_archive_after_the_json_archive(tmp_path):
    from contextlib import ExitStack

    order = []
    with ExitStack() as stack:
        mocks = _patch_all_but(stack, {"export_canonical_data_flow"})
        mocks["zip_exports_task"].side_effect = lambda d: order.append("zip")
        mocks["parquet_archive_task"].side_effect = lambda d: order.append("parquet")
        canonical_data.export_canonical_data_flow.fn(output_dir=str(tmp_path))

    mocks["parquet_archive_task"].assert_called_once_with(str(tmp_path))
    assert order == ["zip", "parquet"]


def test_export_flow_returns_when_the_parquet_archive_fails(tmp_path):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = _patch_all_but(stack, {"export_canonical_data_flow"})
        mocks["parquet_archive_task"].side_effect = RuntimeError("boom")
        canonical_data.export_canonical_data_flow.fn(output_dir=str(tmp_path))

    mocks["zip_exports_task"].assert_called_once_with(str(tmp_path))


def test_export_flow_without_zip_builds_no_parquet_archive(tmp_path):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = _patch_all_but(stack, {"export_canonical_data_flow"})
        canonical_data.export_canonical_data_flow.fn(
            output_dir=str(tmp_path), zip_exports=False
        )

    mocks["parquet_archive_task"].assert_not_called()


def _run_parquet_app(monkeypatch, *argv):
    import app

    monkeypatch.setattr(sys, "argv", ["app.py", "parquet_archive", *argv])
    flow = MagicMock()
    monkeypatch.setattr(app, "parquet_archive_flow", flow)
    app.main()
    return flow


def test_parquet_archive_command_runs_the_flow(monkeypatch):
    flow = _run_parquet_app(monkeypatch, "out_dir")
    flow.assert_called_once_with(output_dir="out_dir")


def test_parquet_archive_command_defaults_to_the_exports_folder(monkeypatch):
    flow = _run_parquet_app(monkeypatch)
    flow.assert_called_once_with(output_dir="data/exports")
