import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from prefect import flow, get_run_logger

from src.core.logic.pii_anonymizer import (
    PII_COLUMN_REGISTRY,
    anonymize_person_data,
    is_anonymized_cpf,
    is_anonymized_email,
    is_anonymized_text,
)
from src.notifications.telegram import telegram_flow_state_handlers

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
                found.append({"table": table, "column": col, "field_type": PII_COLUMN_REGISTRY[col]})

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


@flow(name="lgpd-anonymize-backfill", **telegram_flow_state_handlers())
def anonymize_backfill_flow(db_path: str = "db/horizon.db") -> dict:
    run_logger = get_run_logger()
    started_at = datetime.now(timezone.utc).isoformat()
    run_logger.info(f"Starting LGPD PII backfill on {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        pii_columns = _discover_pii_columns(conn)
        run_logger.info(f"Discovered {len(pii_columns)} PII column(s): {pii_columns}")

        table_stats = []
        for entry in pii_columns:
            stats = _anonymize_table_column(conn, entry["table"], entry["column"], entry["field_type"])
            table_stats.append(stats)
            run_logger.info(
                f"{stats['table']}.{stats['column']}: "
                f"anonymized={stats['anonymized']} "
                f"already_done={stats['already_anonymized']} "
                f"skipped_null={stats['skipped_null']} "
                f"errors={stats['errors']}"
            )
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
        "total_anonymized": total_anonymized,
        "total_errors": total_errors,
    }

    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"lgpd_backfill_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    run_logger.info(f"Backfill complete. Status={status}. Report: {report_path}")
    return report


def audit_pii(db_path: str = "db/horizon.db") -> None:
    conn = sqlite3.connect(db_path)
    try:
        pii_columns = _discover_pii_columns(conn)
        cur = conn.cursor()
        print(f"\n=== LGPD PII Audit: {db_path} ===")
        any_unmasked = False
        for entry in pii_columns:
            table, column, field_type = entry["table"], entry["column"], entry["field_type"]
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
