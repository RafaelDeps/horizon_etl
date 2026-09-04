import argparse
import json
import os
import sys

sys.path.append(os.getcwd())

import sqlite3

from src.core.logic.advisorship_canonical_values import (
    AdvisorshipSourceInfo,
    report_year_from_path,
    resolve_advisorship_canonical_values,
)

DEFAULT_DB_PATH = "db/horizon.db"
DEFAULT_JSON_PATH = "data/exports/advisorships_canonical.json"

_REPORT_DIR_YEAR_RE = r"^data/raw/sigpesq/advisorships/\d{4}/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit SC-004/FR-004: every non-null advisorship program/provider in "
            "advisorships_canonical.json must be traceable to a SigPesq source record "
            "under advisorship/YYYY/ with a payload Ano."
        ),
    )
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--exit-on-findings",
        action="store_true",
        default=True,
        help="exit non-zero when findings exist (default: on)",
    )
    return parser.parse_args()


def _load_payload(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def load_source_records(db_path: str) -> dict:
    rows = (
        sqlite3.connect(db_path)
        .execute(
            """
        SELECT
            em.canonical_entity_id AS advisorship_id,
            sr.id AS source_record_id,
            sr.source_system,
            sr.source_path,
            sr.raw_payload_json
        FROM entity_matches em
        JOIN source_records sr ON sr.id = em.source_record_id
        WHERE em.canonical_entity_type = 'advisorship'
          AND sr.source_entity_type = 'advisorship'
        ORDER BY em.canonical_entity_id, sr.id
        """
        )
        .fetchall()
    )

    grouped = {}
    for adv_id, rec_id, system, path, raw in rows:
        grouped.setdefault(adv_id, []).append(
            AdvisorshipSourceInfo(
                advisorship_id=adv_id,
                source_record_id=rec_id,
                source_system=system,
                source_path=path,
                payload=_load_payload(raw),
            )
        )
    return grouped


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.json_path):
        print(json.dumps({"error": f"artifact not found: {args.json_path}"}, indent=2))
        return 2

    with open(args.json_path) as fh:
        export = json.load(fh)
    advisories = [adv for group in export for adv in group.get("advisorships", [])]
    by_id = {adv["id"]: adv for adv in advisories}

    source_records = load_source_records(args.db_path)

    findings = []
    stats = {"advisorship_ids_in_export": len(by_id), "categorized_in_export": 0}

    for adv_id, adv in by_id.items():
        records = source_records.get(adv_id, [])
        values = resolve_advisorship_canonical_values(records)

        year = adv.get("year")
        program = adv.get("program")
        provider = adv.get("provider")

        if program is not None or provider is not None:
            stats["categorized_in_export"] += 1
            backing = [
                r
                for r in records
                if report_year_from_path(r.source_path) is not None
                and r.payload.get("Ano") is not None
            ]
            if not backing:
                findings.append(
                    {
                        "advisorship_id": adv_id,
                        "rule": "non-null category without backing sigpesq record",
                        "detail": (
                            "no advisorship source record at data/raw/sigpesq/"
                            "advisorships/YYYY/ with payload Ano"
                        ),
                    }
                )

            if values.year is not None and values.year != year:
                findings.append(
                    {
                        "advisorship_id": adv_id,
                        "rule": "year mismatch",
                        "detail": f"export year={year}, resolved year={values.year}",
                    }
                )
            if values.program is not None and values.program != program:
                findings.append(
                    {
                        "advisorship_id": adv_id,
                        "rule": "program mismatch",
                        "detail": f"export program={program!r}, resolved program={values.program!r}",
                    }
                )
            if values.provider is not None and values.provider != provider:
                findings.append(
                    {
                        "advisorship_id": adv_id,
                        "rule": "provider mismatch",
                        "detail": f"export provider={provider!r}, resolved provider={values.provider!r}",
                    }
                )
        elif values.program is not None or values.provider is not None:
            findings.append(
                {
                    "advisorship_id": adv_id,
                    "rule": "export missing category present in source",
                    "detail": f"resolved program={values.program!r}, provider={values.provider!r}",
                }
            )

    report = {
        "artifact": args.json_path,
        "db": args.db_path,
        "stats": stats,
        "findings": findings,
        "state": "FAIL" if findings else "PASS",
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if findings and args.exit_on_findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
