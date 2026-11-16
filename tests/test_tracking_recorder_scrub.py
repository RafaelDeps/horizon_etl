"""Spec 029: the recorder stores scrubbed values and hashes the scrubbed value."""

from types import SimpleNamespace

from src.tracking.context import current_ingestion_run_id, current_source_system
from src.tracking.recorder import TrackingRecorder, stable_hash

FAKE_EMAIL = "person@example.test"


class _FakeController:
    """Captures what the recorder asks the controller to store."""

    calls: list = []

    def __init__(self):
        self._service = SimpleNamespace(
            _repository=SimpleNamespace(
                _session=SimpleNamespace(
                    rollback=lambda: None, close=lambda: None, query=lambda *_: None
                )
            )
        )

    def create_assertion(self, **kwargs):
        type(self).calls.append(kwargs)

    def create_change_log(self, **kwargs):
        type(self).calls.append(kwargs)

    def create_source_record(self, **kwargs):
        type(self).calls.append(kwargs)


def _recorder():
    class Captured(_FakeController):
        calls: list = []

    recorder = TrackingRecorder()
    recorder._attribute_assertion_controller_cls = Captured
    recorder._entity_change_log_controller_cls = Captured
    recorder._source_record_controller_cls = Captured
    return recorder, Captured


def _assert(recorder, value):
    recorder.record_attribute_assertions(
        source_record_id=1,
        canonical_entity_type="researcher",
        canonical_entity_id=2,
        selected_attributes={"resume": value},
        selection_reason="test",
    )


def test_assertion_value_is_stored_scrubbed_and_hash_follows_it():
    recorder, captured = _recorder()

    _assert(recorder, {"text": f"write to {FAKE_EMAIL}"})

    stored = captured.calls[0]
    assert FAKE_EMAIL not in str(stored["value_json"])
    assert "@anon.lgpd" in stored["value_json"]["text"]
    assert stored["value_hash"] == stable_hash(stored["value_json"])


def test_clean_assertion_keeps_the_hash_it_always_had():
    recorder, captured = _recorder()
    value = {"text": "no personal data", "year": 2020, "tags": ["a", "b"]}

    _assert(recorder, value)

    assert captured.calls[0]["value_hash"] == stable_hash(value)
    assert captured.calls[0]["value_json"] == value


def test_change_log_before_and_after_are_stored_scrubbed():
    recorder, captured = _recorder()
    token = current_ingestion_run_id.set(1)
    try:
        recorder.record_change(
            source_record_id=1,
            canonical_entity_type="researcher",
            canonical_entity_id=2,
            operation="update",
            changed_fields=["resume"],
            before={"resume": f"old {FAKE_EMAIL}"},
            after={"resume": f"new {FAKE_EMAIL}"},
        )
    finally:
        current_ingestion_run_id.reset(token)

    stored = captured.calls[0]
    assert FAKE_EMAIL not in str(stored["before_json"])
    assert FAKE_EMAIL not in str(stored["after_json"])


def test_source_record_payload_hash_comes_from_the_original_payload():
    recorder, captured = _recorder()
    payload = {"email_text": f"contact {FAKE_EMAIL}"}
    run_token = current_ingestion_run_id.set(1)
    source_token = current_source_system.set("lattes")
    try:
        recorder.record_source_record(
            source_entity_type="researcher", payload=payload, source_record_id="1"
        )
    finally:
        current_ingestion_run_id.reset(run_token)
        current_source_system.reset(source_token)

    stored = captured.calls[0]
    assert stored["payload_hash"] == stable_hash(payload)
    assert FAKE_EMAIL not in str(stored["raw_payload_json"])
