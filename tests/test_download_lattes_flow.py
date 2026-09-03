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
        (cache_dir / lattes_id).write_text("downloaded")

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


def test_validate_script_lattes_runtime_rejects_driver_browser_major_mismatch(
    tmp_path, monkeypatch
):
    chromedriver = tmp_path / "chromedriver"
    chrome = tmp_path / "chrome"
    chromedriver.write_text("")
    chrome.write_text("")

    def fake_version(command):
        if command == [str(chromedriver), "--version"]:
            return "ChromeDriver 144.0.7559.109"
        if command == [str(chrome), "--version"]:
            return "Google Chrome for Testing 147.0.7727.55"
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("src.flows.lattes.download._read_command_version", fake_version)

    with pytest.raises(ScriptLattesRuntimeError, match="reports major version"):
        validate_script_lattes_runtime(str(chromedriver), str(chrome))


def test_validate_script_lattes_runtime_skips_auto_discovered_mismatches(
    tmp_path, monkeypatch
):
    chromedriver = tmp_path / "chromedriver"
    old_chrome = tmp_path / "old-chrome"
    matching_chromium = tmp_path / "matching-chromium"
    chromedriver.write_text("")
    old_chrome.write_text("")
    matching_chromium.write_text("")
    monkeypatch.delenv("CHROME_BINARY", raising=False)

    def fake_which(command):
        return {
            "google-chrome": str(old_chrome),
            "chromium": str(matching_chromium),
        }.get(command)

    def fake_version(command):
        if command == [str(chromedriver), "--version"]:
            return "ChromeDriver 147.0.7727.55"
        if command == [str(old_chrome), "--version"]:
            return "Google Chrome 144.0.7559.109"
        if command == [str(matching_chromium), "--version"]:
            return "Chromium 147.0.7727.55"
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("src.flows.lattes.download.shutil.which", fake_which)
    monkeypatch.setattr("src.flows.lattes.download._read_command_version", fake_version)

    assert validate_script_lattes_runtime(str(chromedriver)) == str(matching_chromium)


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

    prefetch_calls = []

    def fake_prefetch(lattes_ids, cache_dir, max_workers, chrome_binary):
        prefetch_calls.append((lattes_ids, cache_dir, max_workers, chrome_binary))
        return lattes_ids

    def fake_run_script_lattes(config_path, chrome_binary):
        output_dir = tmp_path / "data" / "lattes_json"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "00_Paulo_8400407353673370.json").write_text("{}")
        (output_dir / "01_Daniel_9583314331960942.json").write_text("{}")

    monkeypatch.setenv("HORIZON_LATTES_DOWNLOAD_WORKERS", "2")
    monkeypatch.setattr(
        "src.flows.lattes.download.validate_script_lattes_runtime",
        lambda _chromedriver: "/tmp/chrome",
    )
    monkeypatch.setattr(
        "src.flows.lattes.download.prefetch_lattes_cache", fake_prefetch
    )
    monkeypatch.setattr(
        "src.flows.lattes.download.run_script_lattes_real", fake_run_script_lattes
    )

    # Execute Flow
    download_lattes_flow()

    # Verify
    assert os.path.exists("lattes.config")
    assert os.path.isdir("data/lattes_json")
    assert prefetch_calls == [
        (
            ["8400407353673370", "9583314331960942"],
            str(tmp_path / "cache"),
            2,
            "/tmp/chrome",
        )
    ]

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
