import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from prefect import flow, get_run_logger

load_dotenv()

from src.core.logic.pii_anonymizer import (
    _CPF_RE,
    _EMAIL_RE,
    _PHONE_RE,
    PII_COLUMN_REGISTRY,
    anonymize_person_data,
    is_anonymized_cpf,
    is_anonymized_email,
    is_anonymized_text,
    key_fingerprint,
    scan_text,
)
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import stable_hash  # noqa: E402

# Where the backfill and the verification write their reports.
REPORTS_DIR = "data/reports"

# Spec 029: columns that can hold plain text typed by people or copied from a
# source payload. ``description`` is found in every table that has one; the
# JSON columns are listed. A pair is (table, column).
_JSON_SANITIZE_COLUMNS = (
    ("attribute_assertions", "value_json"),
    ("entity_change_logs", "before_json"),
    ("entity_change_logs", "after_json"),
    ("source_records", "raw_payload_json"),
)
_SANITIZE_BATCH = 2000

_ALREADY_ANONYMIZED_CHECKS = {
    "cpf": is_anonymized_cpf,
    "email": is_anonymized_email,
    "free_text": is_anonymized_text,
}


def _discover_pii_columns(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]

    found = []
    for table in tables:
        cur.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cur.fetchall()]
        for col in columns:
            if col in PII_COLUMN_REGISTRY:
                found.append(
                    {
                        "table": table,
                        "column": col,
                        "field_type": PII_COLUMN_REGISTRY[col],
                    }
                )

    return found


def _anonymize_table_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    field_type: str,
) -> dict:
    cur = conn.cursor()
    stats = {
        "table": table,
        "column": column,
        "field_type": field_type,
        "total_rows": 0,
        "already_anonymized": 0,
        "anonymized": 0,
        "skipped_null": 0,
        "errors": 0,
    }

    try:
        cur.execute(f"SELECT id, {column} FROM {table}")
        rows = cur.fetchall()
        stats["total_rows"] = len(rows)

        is_already = _ALREADY_ANONYMIZED_CHECKS.get(field_type, lambda v: False)

        for row_id, value in rows:
            if value is None:
                stats["skipped_null"] += 1
                continue
            if is_already(value):
                stats["already_anonymized"] += 1
                continue
            try:
                anonymized = anonymize_person_data({column: value})[column]
                cur.execute(
                    f"UPDATE {table} SET {column} = ? WHERE id = ?",
                    (anonymized, row_id),
                )
                stats["anonymized"] += 1
            except Exception as exc:
                logger.error(f"Error anonymizing {table}.{column} id={row_id}: {exc}")
                stats["errors"] += 1

        conn.commit()
    except Exception as exc:
        logger.error(f"Failed processing {table}.{column}: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        stats["errors"] += 1

    return stats


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _sanitize_targets(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Free-text and JSON columns present in this database."""
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]
    targets = []
    for table in tables:
        columns = _table_columns(conn, table)
        if "description" in columns:
            targets.append((table, "description"))
    for table, column in _JSON_SANITIZE_COLUMNS:
        if table in tables and column in _table_columns(conn, table):
            targets.append((table, column))
    return targets


def _sanitize_column(conn: sqlite3.Connection, table: str, column: str) -> dict:
    """Replace plain data in one column, a batch at a time. A row that is
    already clean is not written. ``attribute_assertions.value_hash`` follows
    the scrubbed value; every other hash stays as it was."""
    stats = {"table": table, "column": column, "rows_changed": 0, "hash_collisions": 0}
    follows_hash = (table, column) == ("attribute_assertions", "value_json")
    last_rowid = -1
    while True:
        rows = conn.execute(
            f"SELECT rowid, {column} FROM {table} WHERE rowid > ? "
            "ORDER BY rowid LIMIT ?",
            (last_rowid, _SANITIZE_BATCH),
        ).fetchall()
        if not rows:
            break
        last_rowid = rows[-1][0]
        for rowid, value in rows:
            if not isinstance(value, str):
                continue
            scrubbed, counts = scan_text(value)
            if not any(counts.values()):
                continue
            conn.execute(
                f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (scrubbed, rowid)
            )
            stats["rows_changed"] += 1
            if follows_hash:
                try:
                    new_hash = stable_hash(json.loads(scrubbed))
                    conn.execute(
                        "UPDATE attribute_assertions SET value_hash = ? WHERE rowid = ?",
                        (new_hash, rowid),
                    )
                except sqlite3.IntegrityError:
                    # The scrubbed value equals another assertion of the same
                    # source: keep the old hash rather than delete a row.
                    stats["hash_collisions"] += 1
                except ValueError:
                    pass
        conn.commit()
    return stats


def _stamp_key_fingerprint(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS horizon_meta ("
        " key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO horizon_meta (key, value) VALUES ('pii_key_fingerprint', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key_fingerprint(),),
    )
    conn.commit()


def sanitize_database(conn: sqlite3.Connection) -> dict:
    """Spec 029: scrub free text and JSON columns, then VACUUM only when rows
    changed so freed pages do not keep the old values. A second pass finds
    nothing and does not VACUUM."""
    column_stats = [
        _sanitize_column(conn, table, column)
        for table, column in _sanitize_targets(conn)
    ]
    rows_changed = sum(s["rows_changed"] for s in column_stats)
    vacuumed = False
    if rows_changed:
        conn.execute("VACUUM")
        vacuumed = True
    return {"columns": column_stats, "rows_changed": rows_changed, "vacuumed": vacuumed}


_TEXT_TYPES = ("CHAR", "CLOB", "TEXT", "JSON")
_VERIFY_CHUNK = 64 * 1024 * 1024
_VERIFY_OVERLAP = 512
_FILE_PATTERNS = {
    "email": re.compile(_EMAIL_RE.pattern.encode("ascii")),
    "phone": re.compile(_PHONE_RE.pattern.encode("ascii")),
    "cpf": re.compile(_CPF_RE.pattern.encode("ascii")),
}


def _count_file_bytes_hits(db_path: str) -> dict[str, int]:
    """Matches of the detectors in the database file itself (live pages, freed
    pages and the page slack alike). Counts only."""
    hits = {kind: 0 for kind in _FILE_PATTERNS}
    with open(db_path, "rb") as fh:
        carry = b""
        while True:
            chunk = fh.read(_VERIFY_CHUNK)
            data = carry + chunk
            last = not chunk
            # A match that starts in the carried tail is counted next round.
            limit = len(data) if last else max(len(data) - _VERIFY_OVERLAP, 0)
            for kind, pattern in _FILE_PATTERNS.items():
                hits[kind] += sum(
                    1 for m in pattern.finditer(data) if m.start() < limit
                )
            if last:
                break
            carry = data[limit:]
    return hits


def verify_database(
    db_path: str, report_dir: str = REPORTS_DIR, vacuumed: bool = False
) -> dict:
    """Spec 029: count what the detectors still find, per text column and in
    the file bytes. The report holds counts, never values."""
    columns = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            text_columns = [
                row[1]
                for row in conn.execute(f'PRAGMA table_info("{table}")')
                if any(t in (row[2] or "").upper() for t in _TEXT_TYPES)
            ]
            for column in text_columns:
                counts = {"email": 0, "phone": 0, "cpf": 0, "known_field": 0}
                for (value,) in conn.execute(
                    f'SELECT "{column}" FROM "{table}" WHERE typeof("{column}")=\'text\''
                ):
                    _, found = scan_text(value)
                    for kind, number in found.items():
                        counts[kind] += 1 if number else 0
                for kind, number in counts.items():
                    if number:
                        columns.append(
                            {
                                "table": table,
                                "column": column,
                                "kind": kind,
                                "count": number,
                            }
                        )
        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
    finally:
        conn.close()
    report = {
        "columns": columns,
        "file_bytes_hits": _count_file_bytes_hits(db_path),
        "freelist_pages": freelist,
        "vacuumed": vacuumed,
    }
    os.makedirs(report_dir, exist_ok=True)
    with open(
        os.path.join(report_dir, "database_verify_report.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


def run_backfill(db_path: str = "db/horizon.db", log=logger.info) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    log(f"Starting LGPD PII backfill on {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        pii_columns = _discover_pii_columns(conn)
        log(f"Discovered {len(pii_columns)} PII column(s): {pii_columns}")

        table_stats = []
        for entry in pii_columns:
            stats = _anonymize_table_column(
                conn, entry["table"], entry["column"], entry["field_type"]
            )
            table_stats.append(stats)
            log(
                f"{stats['table']}.{stats['column']}: "
                f"anonymized={stats['anonymized']} "
                f"already_done={stats['already_anonymized']} "
                f"skipped_null={stats['skipped_null']} "
                f"errors={stats['errors']}"
            )
        sanitized = sanitize_database(conn)
        log(
            f"Sanitized {sanitized['rows_changed']} row(s); "
            f"vacuumed={sanitized['vacuumed']}"
        )
        _stamp_key_fingerprint(conn)
    finally:
        conn.close()

    completed_at = datetime.now(timezone.utc).isoformat()
    total_anonymized = sum(s["anonymized"] for s in table_stats)
    total_errors = sum(s["errors"] for s in table_stats)
    status = "success" if total_errors == 0 else "partial_failure"

    report = {
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "tables": table_stats,
        "sanitized_columns": sanitized["columns"],
        "rows_changed": sanitized["rows_changed"],
        "vacuumed": sanitized["vacuumed"],
        "total_anonymized": total_anonymized,
        "total_errors": total_errors,
    }

    reports_dir = Path(REPORTS_DIR)
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"lgpd_backfill_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    log(f"Backfill complete. Status={status}. Report: {report_path}")
    return report


@flow(name="lgpd-anonymize-backfill", **telegram_flow_state_handlers())
def anonymize_backfill_flow(db_path: str = "db/horizon.db") -> dict:
    return run_backfill(db_path, log=get_run_logger().info)


def audit_pii(db_path: str = "db/horizon.db") -> None:
    conn = sqlite3.connect(db_path)
    try:
        pii_columns = _discover_pii_columns(conn)
        cur = conn.cursor()
        print(f"\n=== LGPD PII Audit: {db_path} ===")
        any_unmasked = False
        for entry in pii_columns:
            table, column, field_type = (
                entry["table"],
                entry["column"],
                entry["field_type"],
            )
            is_already = _ALREADY_ANONYMIZED_CHECKS.get(field_type, lambda v: False)
            cur.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")
            values = [row[0] for row in cur.fetchall()]
            unmasked = [v for v in values if not is_already(v)]
            status = "✅ CLEAN" if not unmasked else f"⚠️  {len(unmasked)} UNMASKED"
            print(f"  {table}.{column}: {len(values)} rows — {status}")
            if unmasked:
                any_unmasked = True
        if any_unmasked:
            print("\nRun `make anonymize-backfill` to anonymize remaining records.")
        else:
            print("\nAll PII fields are anonymized.")
    finally:
        conn.close()
