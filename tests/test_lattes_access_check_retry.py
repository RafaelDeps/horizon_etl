"""Spec 025: the curricula that got the access check page are asked again
once, after a pause, in the same run, under the spec 024 stop."""

import json
import os
import threading

import pytest
from loguru import logger

import src.flows.portal_stops as portal_stops
from src.adapters.sources.raw_store import JsonDownloadManifest
from src.core.logic.access_check_retry import AccessCheckRetrySettings
from src.core.logic.raw_rotation import counts_line
from src.flows.lattes.download import rotate_lattes_downloads
from tests.test_lattes_rotation import CAPTCHA, _page

IDS = [f"{i:016d}" for i in range(1, 21)]
OLD = "2026-10-01T00:00:00Z"
NO_PAUSE = AccessCheckRetrySettings(workers=1, pause_s=0.0)


class Portal:
    """Writes ``<dir>/<id>``: the access check page when ``rejects(id, k)``
    (k counts the requests for that id from 1, n all requests from 1), the
    curriculum otherwise. Counts the requests in flight."""

    def __init__(self, rejects=lambda lattes_id, k, n: False):
        self.rejects = rejects
        self.calls = []
        self.per_id = {}
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def __call__(self, lattes_id, directory):
        with self._lock:
            self.calls.append(lattes_id)
            k = self.per_id[lattes_id] = self.per_id.get(lattes_id, 0) + 1
            n = len(self.calls)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            body = CAPTCHA if self.rejects(lattes_id, k, n) else _page(lattes_id, "v2")
            with open(os.path.join(directory, lattes_id), "w") as f:
                f.write(body)
        finally:
            with self._lock:
                self.in_flight -= 1


def first_request_of(ids):
    ids = set(ids)
    return lambda lattes_id, k, n: lattes_id in ids and k == 1


def always(ids):
    ids = set(ids)
    return lambda lattes_id, k, n: lattes_id in ids


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    for key in (
        "HORIZON_PORTAL_EARLY_STOP",
        "HORIZON_LATTES_STOP_AFTER_FAILURES",
        "HORIZON_LATTES_RETRY_WORKERS",
        "HORIZON_LATTES_RETRY_PAUSE_MIN",
    ):
        monkeypatch.delenv(key, raising=False)


class Sleeps(list):
    def __call__(self, seconds):
        self.append(seconds)


def _setup(tmp_path, cached=(), dated=()):
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    for lattes_id in cached:
        (cache / lattes_id).write_text(_page(lattes_id, "v1"))
    path = tmp_path / "raw" / "lattes" / "download_manifest.json"
    manifest = JsonDownloadManifest(str(path), str(cache))
    for lattes_id in dated:
        manifest.record(lattes_id, OLD)
    manifest.save()
    return cache, path


def _rotate(
    cache, path, portal, ids=IDS, retry=NO_PAUSE, share=1.0, workers=1, sleep=None
):
    return rotate_lattes_downloads(
        ids,
        str(cache),
        JsonDownloadManifest(str(path), str(cache)),
        share,
        False,
        max_workers=workers,
        downloader=portal,
        retry=retry,
        sleep=Sleeps() if sleep is None else sleep,
    )


def _dates(cache, path):
    return JsonDownloadManifest(str(path), str(cache)).dates()


# --- US1: the second try -------------------------------------------------


def test_a_new_curriculum_rejected_once_is_cached_in_the_same_run(tmp_path):
    cache, path = _setup(tmp_path)
    portal = Portal(first_request_of(IDS[:3]))
    counts = _rotate(cache, path, portal)
    for lattes_id in IDS[:3]:
        assert (cache / lattes_id).read_text() == _page(lattes_id, "v2")
        assert _dates(cache, path)[lattes_id] != OLD
    assert counts["new"] == len(IDS) and counts["failed"] == 0
    assert counts["retried"] == 3 and counts["recovered"] == 3
    assert portal.per_id[IDS[0]] == 2 and portal.per_id[IDS[5]] == 1


def test_a_refresh_rejected_once_replaces_its_copy(tmp_path):
    cache, path = _setup(tmp_path, IDS, dated=IDS)
    counts = _rotate(cache, path, Portal(first_request_of(IDS[:2])))
    for lattes_id in IDS[:2]:
        assert (cache / lattes_id).read_text() == _page(lattes_id, "v2")
        assert _dates(cache, path)[lattes_id] != OLD
    assert counts["refreshed"] == len(IDS) and counts["reused_after_failure"] == 0
    assert counts["recovered"] == 2


def test_a_curriculum_rejected_twice_stays_as_today(tmp_path):
    cache, path = _setup(tmp_path, IDS[10:], dated=IDS[10:])
    rejected = [IDS[0], IDS[15]]  # one new, one refresh
    counts = _rotate(cache, path, Portal(always(rejected)))
    assert not (cache / IDS[0]).exists() and IDS[0] not in _dates(cache, path)
    assert (cache / IDS[15]).read_text() == _page(IDS[15], "v1")
    assert _dates(cache, path)[IDS[15]] == OLD
    assert counts["failed_ids"] == sorted(rejected)
    assert counts["retried"] == 2 and counts["recovered"] == 0


def test_the_pause_goes_to_sleep_without_a_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_PORTAL_EARLY_STOP", "0")
    cache, path = _setup(tmp_path)
    sleeps = Sleeps()
    _rotate(
        cache,
        path,
        Portal(first_request_of(IDS[:1])),
        retry=AccessCheckRetrySettings(workers=1, pause_s=300.0),
        sleep=sleeps,
    )
    assert sleeps == [300.0]


def test_the_pause_goes_to_the_stop_wait_with_the_stop_on(tmp_path, monkeypatch):
    waits = []
    import src.core.logic.portal_stop as portal_stop

    monkeypatch.setattr(portal_stop.PortalStop, "wait", lambda self, s: waits.append(s))
    cache, path = _setup(tmp_path)
    sleeps = Sleeps()
    _rotate(
        cache,
        path,
        Portal(first_request_of(IDS[:1])),
        retry=AccessCheckRetrySettings(workers=1, pause_s=120.0),
        sleep=sleeps,
    )
    assert waits == [120.0] and sleeps == []


def test_the_second_pass_uses_its_own_worker_count(tmp_path):
    cache, path = _setup(tmp_path)
    second = []

    def rejects(lattes_id, k, n):
        if k == 2:
            second.append(lattes_id)
        return k == 1 and n % 2 == 0  # 10 rejections, never 5 in a row

    portal = Portal(rejects)
    counts = _rotate(cache, path, portal, workers=3)
    assert counts["retried"] == 10 and counts["recovered"] == 10
    assert len(second) == 10
    # the first pass ran with 3 workers; the second one, alone, with 1
    assert portal.max_in_flight <= 3


def test_one_second_request_per_curriculum_even_when_listed_twice(tmp_path):
    cache, path = _setup(tmp_path)
    ids = IDS[:5] + IDS[:2]
    portal = Portal(always(IDS[:2]))
    counts = _rotate(cache, path, portal, ids=ids)
    assert portal.per_id[IDS[0]] == 2 and portal.per_id[IDS[1]] == 2
    assert counts["retried"] == 2


def test_a_timeout_that_ends_on_the_access_check_page_joins_the_second_pass(tmp_path):
    cache, path = _setup(tmp_path)
    calls = []

    def downloader(lattes_id, directory):
        # what bounded_baixa_cv_lattes leaves after a retried timeout: the
        # page of its last attempt
        calls.append(lattes_id)
        body = (
            CAPTCHA
            if calls.count(lattes_id) == 1 and lattes_id == IDS[0]
            else _page(lattes_id, "v2")
        )
        with open(os.path.join(directory, lattes_id), "w") as f:
            f.write(body)

    counts = _rotate(cache, path, downloader, ids=IDS[:3])
    assert calls.count(IDS[0]) == 2 and counts["recovered"] == 1


def test_no_rejection_means_no_pause_and_todays_counts(tmp_path):
    on_cache, on_path = _setup(tmp_path / "on", IDS[:8], dated=IDS[:8])
    sleeps = Sleeps()
    on = _rotate(on_cache, on_path, Portal(), share=0.5, sleep=sleeps)
    off_cache, off_path = _setup(tmp_path / "off", IDS[:8], dated=IDS[:8])
    off = _rotate(
        off_cache,
        off_path,
        Portal(),
        share=0.5,
        retry=AccessCheckRetrySettings(workers=0),
    )
    assert sleeps == [] and on == off and "retried" not in on
    assert portal_stops.read_access_check_retries() == {}


def test_turned_off_it_behaves_exactly_as_today(tmp_path):
    cache, path = _setup(tmp_path, IDS[10:], dated=IDS[10:])
    portal = Portal(always(IDS[::4]))
    counts = _rotate(cache, path, portal, retry=AccessCheckRetrySettings(workers=0))
    assert len(portal.calls) == len(IDS)
    assert "retried" not in counts and counts["failed"] == len(IDS[::4])
    assert portal_stops.read_access_check_retries() == {}


# --- US2: the stop -------------------------------------------------------


def test_no_second_pass_after_a_stop_in_the_first_pass(tmp_path):
    on_cache, on_path = _setup(tmp_path / "on", IDS[:15], dated=IDS[:15])
    sleeps = Sleeps()
    portal = Portal(lambda i, k, n: True)
    on = _rotate(on_cache, on_path, portal, sleep=sleeps)
    assert len(portal.calls) == 5 and sleeps == []
    assert "retried" not in on
    stop_on = portal_stops.read_portal_stops()
    off_cache, off_path = _setup(tmp_path / "off", IDS[:15], dated=IDS[:15])
    off = _rotate(
        off_cache,
        off_path,
        Portal(lambda i, k, n: True),
        retry=AccessCheckRetrySettings(workers=0),
    )
    assert on == off
    assert (
        stop_on["lattes"]["counts"]
        == portal_stops.read_portal_stops()["lattes"]["counts"]
    )


def test_the_count_of_failures_in_a_row_carries_over_the_pause(tmp_path):
    cache, path = _setup(tmp_path, IDS[10:], dated=IDS[10:])
    # first pass, 1 worker: the new 0..9 (7, 8, 9 rejected), then the
    # refreshes 10..19 (17, 18, 19 rejected), so it ends on 3 in a row;
    # every second-pass request is rejected too
    last_new, last_refresh = set(IDS[7:10]), set(IDS[17:])
    portal = Portal(lambda i, k, n: (i in last_new | last_refresh) or k == 2)
    counts = _rotate(cache, path, portal)
    second = [i for i in portal.calls if portal.per_id[i] == 2]
    # 3 in a row at the end of the first pass + 2 in the second = 5: stop
    assert len(portal.calls[20:]) == 2
    assert counts["retried"] == 6 and counts["recovered"] == 0
    assert counts["stopped"] == 4
    assert portal_stops.read_portal_stops()["lattes"]["reason"] == "failures_in_a_row"
    assert set(second) <= last_new | last_refresh


def test_a_success_in_the_second_pass_resets_the_count(tmp_path):
    cache, path = _setup(tmp_path)
    rejected = set(IDS[:3]) | set(IDS[5:8]) | set(IDS[10:13]) | set(IDS[15:18])

    def rejects(lattes_id, k, n):
        if k == 1:
            return lattes_id in rejected
        return lattes_id != IDS[0]  # the first second-try succeeds

    portal = Portal(rejects)
    counts = _rotate(cache, path, portal)
    # 12 retried: the first succeeds, then 5 rejections in a row stop it
    assert counts["retried"] == 12 and counts["recovered"] == 1
    assert len(portal.calls) == 20 + 1 + 5
    assert counts["stopped"] == 6


def test_without_the_stop_every_rejected_curriculum_is_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_PORTAL_EARLY_STOP", "0")
    cache, path = _setup(tmp_path)
    portal = Portal(lambda i, k, n: True)
    counts = _rotate(cache, path, portal)
    assert len(portal.calls) == 2 * len(IDS)
    assert counts["retried"] == len(IDS) and "stopped" not in counts


# --- US3: the counts and the report --------------------------------------


def test_the_counts_add_up_and_the_line_names_them(tmp_path):
    cache, path = _setup(tmp_path, IDS[10:], dated=IDS[10:])
    portal = Portal(lambda i, k, n: (i in IDS[:2] and k == 1) or i == IDS[12])
    counts = _rotate(cache, path, portal)
    assert counts["retried_ids"] == sorted([IDS[0], IDS[1], IDS[12]])
    assert counts["retried"] == counts["recovered"] + counts["failed"] + counts.get(
        "stopped", 0
    )
    assert counts_line("lattes", counts).endswith(" retried=3 recovered=2")


def test_the_report_gets_a_retries_entry(tmp_path):
    cache, path = _setup(tmp_path)
    _rotate(
        cache,
        path,
        Portal(first_request_of(IDS[:4])),
        retry=AccessCheckRetrySettings(workers=1, pause_s=0.0),
    )
    entry = portal_stops.read_access_check_retries()["lattes"]
    assert entry["retried"] == 4 and entry["recovered"] == 4
    assert entry["workers"] == 1 and entry["pause_s"] == 0.0 and entry["not_tried"] == 0
    assert entry["finished_at"].endswith("Z") and entry["elapsed_s"] >= 0
    document = json.load(open(portal_stops.PORTAL_STOPS_PATH))
    assert document["version"] == 1 and document["stops"] == {}


# --- US4: the settings ---------------------------------------------------


def test_the_environment_is_read_when_no_settings_are_given(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_LATTES_RETRY_WORKERS", "2")
    monkeypatch.setenv("HORIZON_LATTES_RETRY_PAUSE_MIN", "0")
    cache, path = _setup(tmp_path)
    counts = _rotate(cache, path, Portal(first_request_of(IDS[:2])), retry=None)
    assert counts["recovered"] == 2
    entry = portal_stops.read_access_check_retries()["lattes"]
    assert entry["workers"] == 2 and entry["pause_s"] == 0


def test_an_invalid_setting_falls_back_to_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_LATTES_RETRY_WORKERS", "many")
    monkeypatch.setenv("HORIZON_LATTES_RETRY_PAUSE_MIN", "0")
    messages = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        cache, path = _setup(tmp_path)
        counts = _rotate(cache, path, Portal(first_request_of(IDS[:1])), retry=None)
    finally:
        logger.remove(sink)
    assert counts["recovered"] == 1
    assert any("Invalid HORIZON_LATTES_RETRY_WORKERS" in m for m in messages)
