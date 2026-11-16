"""Spec 024, US2: the Lattes download stops requesting curricula after a
number of failures or access check pages in a row; the curricula left keep
their cached copy and are taken first by the next run."""

import json
import os
import threading

import pytest

import src.flows.portal_stops as portal_stops
from src.adapters.sources.raw_store import JsonDownloadManifest
from src.core.logic.raw_rotation import plan_downloads
from src.flows.lattes.download import rotate_lattes_downloads
from tests.test_lattes_rotation import CAPTCHA, _page

IDS = [f"{i:016d}" for i in range(1, 21)]


class Portal:
    """Writes ``<dir>/<id>``: the curriculum, or the access check page for
    the requests that ``blocked(n)`` marks (n counts from 1)."""

    def __init__(self, blocked=lambda n: True):
        self.blocked = blocked
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, lattes_id, directory):
        with self._lock:
            self.calls.append(lattes_id)
            n = len(self.calls)
        with open(os.path.join(directory, lattes_id), "w") as f:
            f.write(CAPTCHA if self.blocked(n) else _page(lattes_id, "v2"))


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    for key in ("HORIZON_PORTAL_EARLY_STOP", "HORIZON_LATTES_STOP_AFTER_FAILURES"):
        monkeypatch.delenv(key, raising=False)


def _setup(tmp_path, cached, dated=()):
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    for lattes_id in cached:
        (cache / lattes_id).write_text(_page(lattes_id, "v1"))
    path = tmp_path / "raw" / "lattes" / "download_manifest.json"
    manifest = JsonDownloadManifest(str(path), str(cache))
    for lattes_id in dated:
        manifest.record(lattes_id, "2026-10-01T00:00:00Z")
    manifest.save()
    return cache, path


def _rotate(cache, path, portal, share=1.0, workers=1):
    return rotate_lattes_downloads(
        IDS,
        str(cache),
        JsonDownloadManifest(str(path), str(cache)),
        share,
        False,
        max_workers=workers,
        downloader=portal,
    )


def test_a_blocking_portal_gets_five_requests(tmp_path):
    cache, path = _setup(tmp_path, IDS[:15], dated=IDS[:15])
    portal = Portal()
    counts = _rotate(cache, path, portal)
    assert len(portal.calls) == 5
    for lattes_id in IDS[:15]:
        assert (cache / lattes_id).read_text() == _page(lattes_id, "v1")
    for lattes_id in IDS[15:]:
        assert not (cache / lattes_id).exists()
    assert counts["failed"] == 5
    assert counts["stopped"] == len(IDS) - 5
    dates = JsonDownloadManifest(str(path), str(cache)).dates()
    assert all(dates[i] == "2026-10-01T00:00:00Z" for i in IDS[:15])
    entry = json.load(open(portal_stops.PORTAL_STOPS_PATH))["stops"]["lattes"]
    assert entry["reason"] == "failures_in_a_row" and entry["limit"] == 5


def test_with_three_workers_at_most_two_more_requests(tmp_path):
    cache, path = _setup(tmp_path, IDS)
    portal = Portal()
    counts = _rotate(cache, path, portal, workers=3)
    assert 5 <= len(portal.calls) <= 7
    assert counts["stopped"] == len(IDS) - len(portal.calls)


def test_a_block_from_the_fourth_request_stops_at_the_eighth(tmp_path):
    cache, path = _setup(tmp_path, IDS)
    portal = Portal(blocked=lambda n: n >= 4)
    counts = _rotate(cache, path, portal)
    assert len(portal.calls) == 8
    assert counts["refreshed"] == 3 and counts["failed"] == 5


def test_an_interleaved_limit_does_not_stop(tmp_path):
    cache, path = _setup(tmp_path, IDS)
    portal = Portal(blocked=lambda n: n % 5 == 0)  # like run 40966298828, 21%
    counts = _rotate(cache, path, portal)
    assert len(portal.calls) == len(IDS)
    assert "stopped" not in counts
    assert portal_stops.read_portal_stops() == {}


def test_a_stop_during_the_new_curricula_leaves_the_refreshes_untried(tmp_path):
    cache, path = _setup(tmp_path, IDS[:10])  # 10 cached, 10 new
    portal = Portal()
    counts = _rotate(cache, path, portal)
    assert len(portal.calls) == 5
    assert set(portal.calls) <= set(IDS[10:])  # the new ones go first
    assert counts["refreshed"] == 0 and counts["reused"] == 10


def test_the_next_run_takes_the_untried_curricula_first(tmp_path):
    cache, path = _setup(tmp_path, IDS[:15], dated=IDS[:15])
    _rotate(cache, path, Portal())
    dates = JsonDownloadManifest(str(path), str(cache)).dates()
    plan = plan_downloads(IDS, dates, share=0.25)
    assert plan.new == IDS[15:]  # never downloaded: still new
    # nothing was refreshed: the oldest are still the first by id
    assert plan.refresh == IDS[: len(plan.refresh)]


def test_the_stop_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_PORTAL_EARLY_STOP", "0")
    cache, path = _setup(tmp_path, IDS)
    portal = Portal()
    counts = _rotate(cache, path, portal)
    assert len(portal.calls) == len(IDS)
    assert counts["failed"] == len(IDS) and "stopped" not in counts


def test_a_custom_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_LATTES_STOP_AFTER_FAILURES", "2")
    cache, path = _setup(tmp_path, IDS)
    portal = Portal()
    _rotate(cache, path, portal)
    assert len(portal.calls) == 2


def test_a_healthy_portal_is_the_same_with_the_stop_off(tmp_path, monkeypatch):
    on_cache, on_path = _setup(tmp_path / "on", IDS[:12])
    on = _rotate(on_cache, on_path, Portal(blocked=lambda n: False), share=0.5)
    monkeypatch.setenv("HORIZON_PORTAL_EARLY_STOP", "0")
    off_cache, off_path = _setup(tmp_path / "off", IDS[:12])
    off = _rotate(off_cache, off_path, Portal(blocked=lambda n: False), share=0.5)
    assert on == off
    assert sorted(os.listdir(on_cache)) == sorted(os.listdir(off_cache))
