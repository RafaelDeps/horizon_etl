"""Spec 024: the report of the portals given up in a weekly."""

import json

import src.flows.portal_stops as portal_stops
from src.core.logic.portal_stop import PortalStop
from src.flows.portal_stops import (
    clear_portal_stops,
    read_access_check_retries,
    read_portal_stops,
    record_access_check_retry,
    record_portal_stop,
)


def _stopped(source, failures=2):
    stop = PortalStop(source, max_failures=failures)
    stop.start()
    for _ in range(failures):
        stop.record(False)
    return stop


COUNTS = {
    "new": 0,
    "refreshed": 1,
    "reused": 3,
    "failed": 2,
    "reused_after_failure": 2,
    "failed_ids": ["a", "b"],
    "stopped": 5,
    "stopped_ids": ["c"],
}


def test_round_trip_with_two_sources(tmp_path):
    path = str(tmp_path / "reports" / "portal_stops.json")
    record_portal_stop("cnpq", _stopped("cnpq"), COUNTS, path=path)
    record_portal_stop("lattes", _stopped("lattes", 5), COUNTS, path=path)
    stops = read_portal_stops(path)
    assert set(stops) == {"cnpq", "lattes"}
    assert stops["cnpq"]["reason"] == "failures_in_a_row"
    assert stops["lattes"]["limit"] == 5
    assert stops["cnpq"]["counts"]["stopped"] == 5
    assert "failed_ids" not in stops["cnpq"]["counts"]
    assert "stopped_ids" not in stops["cnpq"]["counts"]
    data = json.loads(open(path).read())
    assert data["version"] == 1


def test_a_source_is_replaced(tmp_path):
    path = str(tmp_path / "portal_stops.json")
    record_portal_stop("cnpq", _stopped("cnpq", 2), COUNTS, path=path)
    record_portal_stop("cnpq", _stopped("cnpq", 3), COUNTS, path=path)
    assert read_portal_stops(path)["cnpq"]["limit"] == 3


def test_unreadable_or_missing_file(tmp_path):
    path = tmp_path / "portal_stops.json"
    assert read_portal_stops(str(path)) == {}
    path.write_text("{broken")
    assert read_portal_stops(str(path)) == {}
    path.write_text("[]")
    assert read_portal_stops(str(path)) == {}


def test_a_write_error_is_logged_not_raised(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        portal_stops.logger, "warning", lambda *a, **k: warnings.append(a)
    )
    blocker = tmp_path / "file"
    blocker.write_text("x")
    record_portal_stop(
        "cnpq", _stopped("cnpq"), COUNTS, path=str(blocker / "sub" / "x.json")
    )
    assert warnings


def test_clear(tmp_path):
    path = str(tmp_path / "portal_stops.json")
    clear_portal_stops(path)  # missing: nothing happens
    record_portal_stop("cnpq", _stopped("cnpq"), COUNTS, path=path)
    clear_portal_stops(path)
    assert read_portal_stops(path) == {}


def test_tests_never_write_the_repository_report():
    # tests/conftest.py redirects the module default.
    assert portal_stops.PORTAL_STOPS_PATH != "data/reports/portal_stops.json"


# Spec 025: the second try of the access check pages shares the file.
RETRY = {"source": "lattes", "retried": 38, "recovered": 35}


def test_a_retry_entry_keeps_the_stops_and_a_stop_keeps_the_retries(tmp_path):
    path = str(tmp_path / "portal_stops.json")
    record_portal_stop("cnpq", _stopped("cnpq"), COUNTS, path=path)
    record_access_check_retry("lattes", RETRY, path=path)
    assert read_portal_stops(path)["cnpq"]["limit"] == 2
    assert read_access_check_retries(path) == {"lattes": RETRY}
    record_portal_stop("lattes", _stopped("lattes"), COUNTS, path=path)
    assert read_access_check_retries(path) == {"lattes": RETRY}
    assert set(read_portal_stops(path)) == {"cnpq", "lattes"}
    assert json.load(open(path))["version"] == 1


def test_retries_missing_or_unreadable(tmp_path):
    path = tmp_path / "portal_stops.json"
    assert read_access_check_retries(str(path)) == {}
    record_portal_stop("cnpq", _stopped("cnpq"), COUNTS, path=str(path))
    assert read_access_check_retries(str(path)) == {}
    path.write_text("{broken")
    assert read_access_check_retries(str(path)) == {}


def test_a_retry_write_error_is_logged_not_raised(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        portal_stops.logger, "warning", lambda *a, **k: warnings.append(a)
    )
    blocker = tmp_path / "file"
    blocker.write_text("x")
    record_access_check_retry("lattes", RETRY, path=str(blocker / "sub" / "x.json"))
    assert warnings


def test_the_retried_ids_stay_out_of_the_stop_entry(tmp_path):
    path = str(tmp_path / "portal_stops.json")
    counts = dict(COUNTS, retried=2, recovered=1, retried_ids=["a", "b"])
    record_portal_stop("lattes", _stopped("lattes"), counts, path=path)
    entry = read_portal_stops(path)["lattes"]["counts"]
    assert "retried_ids" not in entry and entry["retried"] == 2
