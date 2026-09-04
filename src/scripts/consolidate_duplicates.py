import argparse
import json
import os
import sqlite3
import sys

from loguru import logger

sys.path.append(os.getcwd())

from src.core.logic.person_consolidator import PersonConsolidator  # noqa: E402
from src.core.logic.reference_consolidator import ReferenceConsolidator  # noqa: E402

DEFAULT_DB_PATH = "db/horizon.db"
DEFAULT_REPORT_DIR = "data/reports"


def _write_report(report: dict, report_dir: str = DEFAULT_REPORT_DIR) -> str:
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "dedup_report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return report_path


def run_person_dedup(
    db_path: str = DEFAULT_DB_PATH, report_dir: str = DEFAULT_REPORT_DIR
) -> dict:
    """Weekly-pipeline person dedup: classify duplicates, merge the safe ones,
    and persist a reviewable report (contract R12/R14)."""
    consolidator = PersonConsolidator(db_path)
    groups = consolidator.find_all_groups()
    planned = consolidator.build_report(groups=groups)
    merged_now = consolidator.consolidate_all()
    planned["records_merged"] = merged_now
    planned["report_path"] = _write_report(planned, report_dir)
    logger.info(
        "Person dedup on {}: {} records merged, {} groups refused (see {}).",
        db_path,
        merged_now,
        planned["refused_groups"],
        planned["report_path"],
    )
    return planned


def _person_plan(db_path: str) -> dict:
    groups = PersonConsolidator(db_path).find_duplicate_groups()
    return {
        "person_duplicate_groups": len(groups),
        "person_duplicate_records": sum(len(group.loser_ids) for group in groups),
        "person_examples": [
            {
                "canonical_name": group.canonical_name,
                "winner_id": group.winner_id,
                "loser_ids": group.loser_ids,
            }
            for group in groups[:20]
        ],
    }


def _reference_plan(db_path: str) -> dict:
    consolidator = ReferenceConsolidator(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        team_groups = consolidator._canonical_groups(
            conn.execute(
                "SELECT id, name, description, short_name, organization_id FROM teams"
            ).fetchall()
        )
        knowledge_area_groups = consolidator._canonical_groups(
            conn.execute("SELECT id, name FROM knowledge_areas").fetchall()
        )
    return {
        "team_duplicate_groups": len(team_groups),
        "team_duplicate_records": sum(
            len(group["members"]) - 1 for group in team_groups
        ),
        "knowledge_area_duplicate_groups": len(knowledge_area_groups),
        "knowledge_area_duplicate_records": sum(
            len(group["members"]) - 1 for group in knowledge_area_groups
        ),
    }


def build_report(db_path: str, entity: str) -> dict:
    report = {"db_path": db_path, "entity": entity}
    if entity in {"persons", "all"}:
        report.update(_person_plan(db_path))
    if entity in {"references", "all"}:
        report.update(_reference_plan(db_path))
    return report


def execute(db_path: str, entity: str) -> dict:
    result = {"db_path": db_path, "entity": entity}
    if entity in {"persons", "all"}:
        result["person_records_merged"] = PersonConsolidator(db_path).consolidate_all()
    if entity in {"references", "all"}:
        consolidator = ReferenceConsolidator(db_path)
        knowledge_area_stats = consolidator.consolidate_knowledge_areas()
        team_stats = consolidator.consolidate_teams()
        result["knowledge_areas_merged"] = knowledge_area_stats.merged
        result["knowledge_areas_skipped"] = knowledge_area_stats.skipped
        result["teams_merged"] = team_stats.merged
        result["teams_skipped"] = team_stats.skipped
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consolidate duplicate entities in the Horizon SQLite database."
    )
    parser.add_argument(
        "--db-path",
        default="db/horizon.db",
        help="Path to the SQLite database. Default: db/horizon.db",
    )
    parser.add_argument(
        "--entity",
        choices=("persons", "references", "all"),
        default="all",
        help="Which duplicate families to consolidate.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be consolidated, without changing the database.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = (
        build_report(args.db_path, args.entity)
        if args.dry_run
        else execute(args.db_path, args.entity)
    )
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
