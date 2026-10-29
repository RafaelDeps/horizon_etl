"""Spec 023, US1: Lattes curricula are downloaded when missing plus a rotating
share of cached ones, and a failed refresh keeps the cached copy."""

import os
import threading

from src.adapters.sources.raw_store import JsonDownloadManifest
from src.flows.lattes.download import rotate_lattes_downloads

IDS = [f"{i:016d}" for i in range(1, 9)]


class FakeDownloader:
    """Writes ``<dir>/<id>`` with a version mark, or fails for some ids."""

    def __init__(self, version="v2", failing=()):
        self.version = version
        self.failing = set(failing)
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, lattes_id, directory):
        with self._lock:
            self.calls.append(lattes_id)
        if lattes_id in self.failing:
            raise RuntimeError("portal timeout")
        with open(os.path.join(directory, lattes_id), "w") as f:
            f.write(f"{lattes_id} {self.version}")


def _setup(tmp_path, cached):
    cache = tmp_path / "cache"
    cache.mkdir()
    for lattes_id in cached:
        (cache / lattes_id).write_text(f"{lattes_id} v1")
    manifest_path = tmp_path / "raw" / "lattes" / "download_manifest.json"
    return cache, manifest_path


def _manifest(cache, path):
    return JsonDownloadManifest(str(path), str(cache))


def test_missing_ids_plus_the_oldest_quarter_are_downloaded(tmp_path):
    cache, path = _setup(tmp_path, IDS[:6])
    downloader = FakeDownloader()
    counts = rotate_lattes_downloads(
        IDS, str(cache), _manifest(cache, path), 0.25, False, downloader=downloader
    )
    # 2 new + ceil(0.25 * 6) = 2 undated cached ones (by id)
    assert sorted(downloader.calls) == sorted(IDS[6:] + IDS[:2])
    assert counts["new"] == 2 and counts["refreshed"] == 2 and counts["reused"] == 4
    for lattes_id in IDS[6:] + IDS[:2]:
        assert (cache / lattes_id).read_text() == f"{lattes_id} v2"
    for lattes_id in IDS[2:6]:
        assert (cache / lattes_id).read_text() == f"{lattes_id} v1"
    dates = _manifest(cache, path).dates()
    assert all(dates[i] for i in IDS[6:] + IDS[:2])
    assert all(dates[i] is None for i in IDS[2:6])
    assert not (cache / ".refresh").exists()


def test_a_failed_refresh_keeps_the_cached_copy_and_its_date(tmp_path):
    cache, path = _setup(tmp_path, IDS[:4])
    manifest = _manifest(cache, path)
    manifest.record(IDS[1], "2026-10-01T00:00:00Z")
    manifest.save()
    downloader = FakeDownloader(failing={IDS[0]})
    counts = rotate_lattes_downloads(
        IDS[:4], str(cache), _manifest(cache, path), 0.5, False, downloader=downloader
    )
    # Undated 0, 2 and 3 are the oldest; ceil(0.5 * 4) = 2 -> 0 and 2.
    assert sorted(downloader.calls) == [IDS[0], IDS[2]]
    assert (cache / IDS[0]).read_text() == f"{IDS[0]} v1"
    assert (cache / IDS[2]).read_text() == f"{IDS[2]} v2"
    assert counts["failed"] == 1 and counts["reused_after_failure"] == 1
    dates = _manifest(cache, path).dates()
    assert dates[IDS[0]] is None and dates[IDS[1]] == "2026-10-01T00:00:00Z"


def test_a_failed_new_download_leaves_no_cache_file(tmp_path):
    cache, path = _setup(tmp_path, [])
    downloader = FakeDownloader(failing={IDS[0]})
    counts = rotate_lattes_downloads(
        IDS[:2], str(cache), _manifest(cache, path), 0.25, False, downloader=downloader
    )
    assert not (cache / IDS[0]).exists() and (cache / IDS[1]).exists()
    assert counts["new"] == 1 and counts["failed"] == 1
    assert counts["reused_after_failure"] == 0


def test_four_runs_date_every_cached_curriculum(tmp_path):
    cache, path = _setup(tmp_path, IDS)
    for _ in range(4):
        rotate_lattes_downloads(
            IDS,
            str(cache),
            _manifest(cache, path),
            0.25,
            False,
            downloader=FakeDownloader(),
        )
    dates = _manifest(cache, path).dates()
    assert all(dates[i] for i in IDS)


def test_full_refresh_downloads_every_curriculum(tmp_path):
    cache, path = _setup(tmp_path, IDS)
    downloader = FakeDownloader()
    counts = rotate_lattes_downloads(
        IDS, str(cache), _manifest(cache, path), 0.25, True, downloader=downloader
    )
    assert sorted(downloader.calls) == IDS and counts["refreshed"] == len(IDS)


def test_an_unidentified_curriculum_is_retried_on_the_next_run(tmp_path):
    from src.core.logic.raw_rotation import plan_downloads
    from src.flows.lattes.cv_document import retry_unidentified

    cache, path = _setup(tmp_path, IDS)
    manifest = _manifest(cache, path)
    for lattes_id in IDS:
        manifest.record(lattes_id, "2026-11-05T02:00:00Z")
    manifest.save()

    class Skip:
        failures = [
            (IDS[5], "unidentified", "x"),
            (IDS[6], "download", "y"),  # other failures keep their date
        ]

    assert retry_unidentified(Skip(), _manifest(cache, path)) == 1
    dates = _manifest(cache, path).dates()
    assert dates[IDS[5]] is None and dates[IDS[6]] == "2026-11-05T02:00:00Z"
    # The next rotation takes it first.
    assert plan_downloads(IDS, dates, share=0.125).refresh == [IDS[5]]
