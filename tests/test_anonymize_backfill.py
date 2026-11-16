import json
import sqlite3

import pytest

from src.core.logic.pii_anonymizer import is_anonymized_cpf, is_anonymized_email
from src.flows.maintenance import anonymize_backfill as backfill
from src.flows.maintenance.anonymize_backfill import (
    _anonymize_table_column,
    _discover_pii_columns,
    audit_pii,
)
from src.tracking.recorder import stable_hash


def _make_conn(sql: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(sql)
    return conn


# --- _discover_pii_columns ---

def test_discover_pii_columns_finds_identification_id():
    conn = _make_conn(
        "CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, identification_id TEXT);"
    )
    cols = _discover_pii_columns(conn)
    assert any(c["table"] == "persons" and c["column"] == "identification_id" for c in cols)


def test_discover_pii_columns_finds_email():
    conn = _make_conn(
        "CREATE TABLE person_emails (id INTEGER PRIMARY KEY, person_id INTEGER, email TEXT);"
    )
    cols = _discover_pii_columns(conn)
    assert any(c["table"] == "person_emails" and c["column"] == "email" for c in cols)


def test_discover_pii_columns_ignores_non_pii():
    conn = _make_conn(
        "CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, campus TEXT);"
    )
    cols = _discover_pii_columns(conn)
    assert cols == []


def test_discover_pii_columns_multiple_tables():
    conn = _make_conn("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, identification_id TEXT);
        CREATE TABLE person_emails (id INTEGER PRIMARY KEY, email TEXT);
    """)
    cols = _discover_pii_columns(conn)
    assert len(cols) == 2


# --- _anonymize_table_column ---

def test_anonymize_table_column_anonymizes_cpf():
    conn = _make_conn("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, identification_id TEXT);
        INSERT INTO persons VALUES (1, '12345678901');
    """)
    stats = _anonymize_table_column(conn, "persons", "identification_id", "cpf")
    row = conn.execute("SELECT identification_id FROM persons WHERE id=1").fetchone()[0]
    assert is_anonymized_cpf(row)
    assert stats["anonymized"] == 1
    assert stats["errors"] == 0


def test_anonymize_table_column_anonymizes_email():
    conn = _make_conn("""
        CREATE TABLE person_emails (id INTEGER PRIMARY KEY, email TEXT);
        INSERT INTO person_emails VALUES (1, 'user@example.com');
    """)
    stats = _anonymize_table_column(conn, "person_emails", "email", "email")
    row = conn.execute("SELECT email FROM person_emails WHERE id=1").fetchone()[0]
    assert is_anonymized_email(row)
    assert stats["anonymized"] == 1


def test_anonymize_table_column_skips_null():
    conn = _make_conn("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, identification_id TEXT);
        INSERT INTO persons VALUES (1, NULL);
    """)
    stats = _anonymize_table_column(conn, "persons", "identification_id", "cpf")
    assert stats["skipped_null"] == 1
    assert stats["anonymized"] == 0


def test_anonymize_table_column_idempotent_already_anonymized_cpf():
    conn = _make_conn("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, identification_id TEXT);
        INSERT INTO persons VALUES (1, 'LGPD-abc1234567890123');
    """)
    stats = _anonymize_table_column(conn, "persons", "identification_id", "cpf")
    assert stats["already_anonymized"] == 1
    assert stats["anonymized"] == 0


def test_anonymize_table_column_idempotent_already_anonymized_email():
    conn = _make_conn("""
        CREATE TABLE person_emails (id INTEGER PRIMARY KEY, email TEXT);
        INSERT INTO person_emails VALUES (1, 'abc123456789@anon.lgpd');
    """)
    stats = _anonymize_table_column(conn, "person_emails", "email", "email")
    assert stats["already_anonymized"] == 1
    assert stats["anonymized"] == 0


def test_anonymize_table_column_second_run_is_noop():
    conn = _make_conn("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, identification_id TEXT);
        INSERT INTO persons VALUES (1, '12345678901');
        INSERT INTO persons VALUES (2, '98765432100');
    """)
    _anonymize_table_column(conn, "persons", "identification_id", "cpf")
    stats2 = _anonymize_table_column(conn, "persons", "identification_id", "cpf")
    assert stats2["anonymized"] == 0
    assert stats2["already_anonymized"] == 2


def test_anonymize_table_column_stats_correct():
    conn = _make_conn("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, identification_id TEXT);
        INSERT INTO persons VALUES (1, '12345678901');
        INSERT INTO persons VALUES (2, NULL);
        INSERT INTO persons VALUES (3, 'LGPD-existinghash12345');
    """)
    stats = _anonymize_table_column(conn, "persons", "identification_id", "cpf")
    assert stats["total_rows"] == 3
    assert stats["anonymized"] == 1
    assert stats["skipped_null"] == 1
    assert stats["already_anonymized"] == 1
    assert stats["errors"] == 0


# --- audit_pii ---

def test_audit_pii_runs_without_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY, identification_id TEXT, name TEXT)")
    conn.execute("INSERT INTO persons VALUES (1, 'LGPD-abc1234567890123', 'Alice')")
    conn.commit()
    conn.close()
    audit_pii(db_path=db_path)


def test_audit_pii_empty_db(tmp_path):
    db_path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY, foo TEXT)")
    conn.commit()
    conn.close()
    audit_pii(db_path=db_path)


# --- Spec 029: sanitizing free text, JSON columns and the file itself ---

FAKE_EMAIL = "person@example.test"
FAKE_PHONE = "+55 00 00000-0000"
FAKE_CPF = "000.000.000-00"


def _sanitize_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE initiatives (id INTEGER PRIMARY KEY, description TEXT);
        CREATE TABLE attribute_assertions (
            id INTEGER PRIMARY KEY, source_record_id INTEGER,
            canonical_entity_type TEXT, canonical_entity_id INTEGER,
            attribute_name TEXT, value_json TEXT, value_hash TEXT,
            UNIQUE (source_record_id, canonical_entity_type, canonical_entity_id,
                    attribute_name, value_hash));
        CREATE TABLE entity_change_logs (
            id INTEGER PRIMARY KEY, before_json TEXT, after_json TEXT);
        CREATE TABLE source_records (
            id INTEGER PRIMARY KEY, raw_payload_json TEXT, payload_hash TEXT);
        CREATE TABLE source_document_states (
            source_system TEXT, document_key TEXT, content_hash TEXT,
            dependency_fingerprint TEXT, rule_version INTEGER);
        CREATE TABLE horizon_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """
    )
    conn.execute(
        "INSERT INTO initiatives VALUES (1, ?), (2, 'clean text')",
        (f"Contact {FAKE_EMAIL} or {FAKE_PHONE} cpf {FAKE_CPF}",),
    )
    value = json.dumps({"text": f"mail {FAKE_EMAIL}"})
    conn.execute(
        "INSERT INTO attribute_assertions VALUES (1, 1, 'researcher', 1, 'resume',"
        " ?, 'old-hash'), (2, 1, 'researcher', 1, 'name', '\"Ana\"', 'clean-hash')",
        (value,),
    )
    conn.execute(
        "INSERT INTO entity_change_logs VALUES (1, ?, ?)",
        (json.dumps({"r": FAKE_EMAIL}), json.dumps({"r": "clean"})),
    )
    conn.execute(
        "INSERT INTO source_records VALUES (1, ?, 'payload-hash-1')",
        (json.dumps({"email": "not-an-address", "n": 1}),),
    )
    conn.execute(
        "INSERT INTO source_document_states VALUES ('lattes', 'k', 'content-1', 'dep-1', 3)"
    )
    conn.commit()
    conn.close()


def _rows(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture
def sanitized_env(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill, "REPORTS_DIR", str(tmp_path / "reports"))
    path = str(tmp_path / "t.db")
    _sanitize_db(path)
    return path


def test_backfill_scrubs_text_and_json_columns(sanitized_env):
    backfill.run_backfill(sanitized_env)

    description = _rows(sanitized_env, "SELECT description FROM initiatives WHERE id=1")
    for plain in (FAKE_EMAIL, FAKE_PHONE, FAKE_CPF):
        assert plain not in description[0][0]
    assert _rows(sanitized_env, "SELECT description FROM initiatives WHERE id=2") == [
        ("clean text",)
    ]
    value_json = _rows(
        sanitized_env, "SELECT value_json FROM attribute_assertions WHERE id=1"
    )[0][0]
    assert FAKE_EMAIL not in value_json
    for column in ("before_json", "after_json"):
        stored = _rows(sanitized_env, f"SELECT {column} FROM entity_change_logs")[0][0]
        assert FAKE_EMAIL not in stored
    payload = json.loads(
        _rows(sanitized_env, "SELECT raw_payload_json FROM source_records")[0][0]
    )
    assert payload["email"].endswith("@anon.lgpd")
    assert payload["n"] == 1


def test_backfill_value_hash_follows_scrubbed_value_and_links_stay(sanitized_env):
    backfill.run_backfill(sanitized_env)

    rows = _rows(
        sanitized_env,
        "SELECT value_json, value_hash FROM attribute_assertions ORDER BY id",
    )
    assert rows[0][1] == stable_hash(json.loads(rows[0][0]))
    # A clean row keeps the hash it had.
    assert rows[1][1] == "clean-hash"
    assert _rows(sanitized_env, "SELECT payload_hash FROM source_records") == [
        ("payload-hash-1",)
    ]
    assert _rows(
        sanitized_env,
        "SELECT content_hash, dependency_fingerprint, rule_version"
        " FROM source_document_states",
    ) == [("content-1", "dep-1", 3)]


def test_backfill_second_run_changes_nothing_and_does_not_vacuum(
    sanitized_env, monkeypatch
):
    first = backfill.run_backfill(sanitized_env)
    assert first["vacuumed"] is True
    dump_before = _rows(
        sanitized_env, "SELECT description FROM initiatives ORDER BY id"
    )

    second = backfill.run_backfill(sanitized_env)

    assert second["vacuumed"] is False
    assert second["rows_changed"] == 0
    assert (
        _rows(sanitized_env, "SELECT description FROM initiatives ORDER BY id")
        == dump_before
    )


def test_backfill_leaves_no_plain_value_in_the_database_file(sanitized_env):
    backfill.run_backfill(sanitized_env)

    with open(sanitized_env, "rb") as fh:
        raw = fh.read()
    for plain in (FAKE_EMAIL, FAKE_PHONE, FAKE_CPF):
        assert plain.encode() not in raw


def test_backfill_does_not_vacuum_a_clean_database(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill, "REPORTS_DIR", str(tmp_path / "reports"))
    path = str(tmp_path / "clean.db")
    _sanitize_db(path)
    backfill.run_backfill(path)

    result = backfill.run_backfill(path)

    assert result["vacuumed"] is False


def _plain_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT, other TEXT)")
    conn.execute(
        "INSERT INTO notes VALUES (1, ?, 'clean')", (f"write to {FAKE_EMAIL}",)
    )
    conn.commit()
    conn.close()


def test_verify_database_counts_per_column_and_in_file_bytes(tmp_path):
    path = str(tmp_path / "plain.db")
    _plain_db(path)
    report_dir = tmp_path / "reports"

    result = backfill.verify_database(path, str(report_dir))

    assert {"table": "notes", "column": "body", "kind": "email", "count": 1} in result[
        "columns"
    ]
    assert not any(c["column"] == "other" for c in result["columns"])
    assert result["file_bytes_hits"]["email"] >= 1
    assert "freelist_pages" in result and "vacuumed" in result
    written = json.loads((report_dir / "database_verify_report.json").read_text())
    assert written == result
    assert FAKE_EMAIL not in json.dumps(written)


def test_verify_database_clean_database_has_zeros(tmp_path):
    path = str(tmp_path / "clean.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO notes VALUES (1, 'nothing here')")
    conn.commit()
    conn.close()

    result = backfill.verify_database(path, str(tmp_path / "reports"))

    assert result["columns"] == []
    assert result["file_bytes_hits"] == {"email": 0, "phone": 0, "cpf": 0}


def test_backfill_stamps_the_key_fingerprint_and_keeps_it(sanitized_env):
    from src.core.logic.pii_anonymizer import key_fingerprint

    backfill.run_backfill(sanitized_env)
    stamp = "SELECT value FROM horizon_meta WHERE key='pii_key_fingerprint'"
    assert _rows(sanitized_env, stamp) == [(key_fingerprint(),)]

    backfill.run_backfill(sanitized_env)
    assert _rows(sanitized_env, stamp) == [(key_fingerprint(),)]


def test_backfill_creates_horizon_meta_when_missing(tmp_path, monkeypatch):
    from src.core.logic.pii_anonymizer import key_fingerprint

    monkeypatch.setattr(backfill, "REPORTS_DIR", str(tmp_path / "reports"))
    path = str(tmp_path / "bare.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY, foo TEXT)")
    conn.commit()
    conn.close()

    backfill.run_backfill(path)

    assert _rows(
        path, "SELECT value FROM horizon_meta WHERE key='pii_key_fingerprint'"
    ) == [(key_fingerprint(),)]
