import os

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.flows.lattes.download import (
    ScriptLattesRuntimeError,
    clean_lattes_json_output,
    collect_lattes_ids_from_list,
    download_lattes_flow,
    patch_script_lattes_runtime,
    prefetch_lattes_cache,
    validate_script_lattes_runtime,
)


def test_clean_lattes_json_output_removes_only_json_files(tmp_path):
    output_dir = tmp_path / "lattes_json"
    output_dir.mkdir()
    stale_json = output_dir / "old.json"
    keep_text = output_dir / "notes.txt"
    nested_dir = output_dir / "nested"
    nested_dir.mkdir()
    nested_json = nested_dir / "nested.json"

    stale_json.write_text("{}")
    keep_text.write_text("keep")
    nested_json.write_text("{}")

    removed = clean_lattes_json_output(str(output_dir))

    assert removed == 1
    assert not stale_json.exists()
    assert keep_text.exists()
    assert nested_json.exists()


def test_collect_lattes_ids_from_list_reads_16_digit_ids(tmp_path):
    list_path = tmp_path / "lattes.list"
    list_path.write_text(
        "\n".join(
            [
                "8400407353673370 , Paulo Sergio dos Santos Junior",
                "http://lattes.cnpq.br/9583314331960942 Daniel Cruz Cavalieri",
                "invalid line",
            ]
        )
    )

    assert collect_lattes_ids_from_list(str(list_path)) == [
        "8400407353673370",
        "9583314331960942",
    ]


def test_prefetch_lattes_cache_downloads_only_missing_ids(tmp_path):
    cache_dir = tmp_path / "cache"
    cached_id = "8400407353673370"
    missing_ids = ["9583314331960942", "8826584877205264"]
    downloaded = []

    cache_dir.mkdir()
    (cache_dir / cached_id).write_text("cached")

    def fake_downloader(lattes_id, target_cache_dir):
        downloaded.append((lattes_id, target_cache_dir))
        # A curriculum page names its owner in the title (spec 023 checks it).
        (cache_dir / lattes_id).write_text(
            "<title>Currículo do Sistema de Currículos Lattes (Nome)</title>"
        )

    result = prefetch_lattes_cache(
        [cached_id, *missing_ids],
        str(cache_dir),
        max_workers=2,
        downloader=fake_downloader,
    )

    assert result == missing_ids
    assert sorted(downloaded) == sorted(
        (lattes_id, str(cache_dir)) for lattes_id in missing_ids
    )


def test_validate_script_lattes_runtime_accepts_playwright_chromium(monkeypatch):
    monkeypatch.setattr(
        "src.flows.lattes.download._check_playwright_chromium", lambda: True
    )

    assert validate_script_lattes_runtime() == "playwright-chromium"


def test_validate_script_lattes_runtime_rejects_missing_chromium(monkeypatch):
    monkeypatch.setattr(
        "src.flows.lattes.download._check_playwright_chromium", lambda: False
    )

    with pytest.raises(ScriptLattesRuntimeError, match="playwright install chromium"):
        validate_script_lattes_runtime()


def test_download_lattes_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    list_dir = tmp_path / "data" / "lattes_run"
    list_dir.mkdir(parents=True)
    (list_dir / "lattes.list").write_text(
        "\n".join(
            [
                "8400407353673370 , Paulo Sergio dos Santos Junior",
                "9583314331960942 , Daniel Cruz Cavalieri",
            ]
        )
    )

    rotate_calls = []

    def fake_rotate(lattes_ids, cache_dir, manifest, share, full, max_workers):
        rotate_calls.append((lattes_ids, cache_dir, max_workers))
        for lattes_id in lattes_ids:
            (tmp_path / "cache" / lattes_id).write_text("cached")
        return {}

    def fake_run_script_lattes(config_path):
        output_dir = tmp_path / "data" / "lattes_json"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "00_Paulo_8400407353673370.json").write_text("{}")
        (output_dir / "01_Daniel_9583314331960942.json").write_text("{}")

    (tmp_path / "cache").mkdir()
    monkeypatch.setenv("HORIZON_LATTES_DOWNLOAD_WORKERS", "2")
    monkeypatch.setattr(
        "src.flows.lattes.download.validate_script_lattes_runtime",
        lambda: "playwright-chromium",
    )
    monkeypatch.setattr(
        "src.flows.lattes.download.rotate_lattes_downloads", fake_rotate
    )
    monkeypatch.setattr(
        "src.flows.lattes.download.run_script_lattes_real", fake_run_script_lattes
    )

    # Execute Flow
    download_lattes_flow()

    # Verify
    assert os.path.exists("lattes.config")
    assert os.path.isdir("data/lattes_json")
    assert rotate_calls == [
        (["8400407353673370", "9583314331960942"], str(tmp_path / "cache"), 2)
    ]
    # Every curriculum reached the cache, so scriptLattes gets the whole list.
    assert not os.path.exists("lattes_effective.list")

    # Check if a JSON file was created (based on the mock data in the flow)
    # The flow mocks IDs, but scriptLattes might prefix them with numbers/names
    assert any("8400407353673370" in f for f in os.listdir("data/lattes_json"))
    assert any("9583314331960942" in f for f in os.listdir("data/lattes_json"))


def test_bounded_baixa_cv_lattes_gives_up_after_bounded_timeouts(tmp_path, monkeypatch):
    """A stuck CV must raise (so prefetch skips it) instead of retrying forever."""
    import scriptLattes.baixaLattes as baixa_lattes

    patch_script_lattes_runtime()

    attempts = []

    def always_timeout(id_lattes, diretorio):
        attempts.append(id_lattes)
        raise PlaywrightTimeoutError("navigation timeout")

    monkeypatch.setattr(baixa_lattes, "__get_data", always_timeout)
    monkeypatch.setenv("HORIZON_LATTES_DOWNLOAD_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("HORIZON_LATTES_DOWNLOAD_RETRY_SLEEP_S", "0")

    with pytest.raises(PlaywrightTimeoutError):
        baixa_lattes.baixaCVLattes("9583314331960942", str(tmp_path))

    assert len(attempts) == 2


def test_bounded_baixa_cv_lattes_skips_connection_resets(tmp_path, monkeypatch):
    """ERR_CONNECTION_RESET (seen in CI) must be retried a bounded number of
    times, then raise, rather than aborting immediately or hanging forever."""
    import scriptLattes.baixaLattes as baixa_lattes

    patch_script_lattes_runtime()

    attempts = []

    def always_reset(id_lattes, diretorio):
        attempts.append(id_lattes)
        raise Exception("net::ERR_CONNECTION_RESET")

    monkeypatch.setattr(baixa_lattes, "__get_data", always_reset)
    monkeypatch.setenv("HORIZON_LATTES_DOWNLOAD_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("HORIZON_LATTES_DOWNLOAD_RETRY_SLEEP_S", "0")

    with pytest.raises(Exception, match="ERR_CONNECTION_RESET"):
        baixa_lattes.baixaCVLattes("9583314331960942", str(tmp_path))

    assert len(attempts) == 3


def test_script_lattes_prints_stay_out_of_the_run_log(monkeypatch, capsys):
    """Spec 029: scriptLattes prints curriculum lines (phones, documents) on
    stdout, which the public run log keeps. They are dropped; the loguru
    summary stays."""
    import sys
    import types

    from loguru import logger

    from src.flows.lattes.download import run_script_lattes_real

    def fake_run(config_path, somente_json=False):
        print("Telefone: (00) 00000-0000 CPF 000.000.000-00")

    package = types.ModuleType("scriptLattes")
    run_module = types.ModuleType("scriptLattes.run")
    run_module.executar_scriptLattes = fake_run
    package.run = run_module
    monkeypatch.setitem(sys.modules, "scriptLattes", package)
    monkeypatch.setitem(sys.modules, "scriptLattes.run", run_module)
    monkeypatch.setattr(
        "src.flows.lattes.download.patch_script_lattes_runtime", lambda: None
    )
    messages = []
    sink_id = logger.add(lambda message: messages.append(str(message)))
    try:
        run_script_lattes_real.fn("config.cfg")
    finally:
        logger.remove(sink_id)

    assert "00000-0000" not in capsys.readouterr().out
    assert any("scriptLattes execution finished" in m for m in messages)
