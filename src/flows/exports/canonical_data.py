import json
import os
import time
import zipfile
from typing import Optional

from loguru import logger
from prefect import flow, task

from src.adapters.database.horizon_id_store import (
    SqliteHorizonIdStore,
    sqlite_path_from_url,
)
from src.adapters.sinks.json_sink import JsonSink
from src.core.logic.canonical_exporter import CanonicalDataExporter
from src.core.logic.horizon_id_assigner import write_alias_file, write_id_file
from src.core.logic.pii_anonymizer import key_fingerprint, scan_text, scrub_pii_deep
from src.core.logic.research_group_exporter import ResearchGroupExporter
from src.flows.exports.null_researchers_collaboration_graph import (
    export_null_researchers_collaboration_graph_flow,
)
from src.flows.exports.outside_ifes_collaboration_graph import (
    export_outside_ifes_collaboration_graph_flow,
)
from src.flows.exports.people_collaboration_graph import (
    export_people_collaboration_graph_flow,
)
from src.flows.exports.people_relationship_graph import (
    export_people_relationship_graph_flow,
)
from src.flows.exports.research_group_membership_graphs_manifest import (
    export_research_group_membership_graphs_manifest_flow,
)
from src.flows.exports.researchers_collaboration_graph import (
    export_researchers_collaboration_graph_flow,
)
from src.flows.exports.students_collaboration_graph import (
    export_students_collaboration_graph_flow,
)
from src.notifications.telegram import telegram_flow_state_handlers


@task(name="export_organizations_task")
def export_organizations_task(output_dir: str):
    logger.info("Starting Organizations export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_organizations(
        os.path.join(output_dir, "organizations_canonical.json")
    )


@task(name="export_campuses_task")
def export_campuses_task(output_dir: str, campus: Optional[str] = None):
    logger.info("Starting Campuses export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_campuses(
        os.path.join(output_dir, "campuses_canonical.json"), campus_filter=campus
    )


@task(name="export_knowledge_areas_task")
def export_knowledge_areas_task(output_dir: str):
    logger.info("Starting Knowledge Areas export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_knowledge_areas(
        os.path.join(output_dir, "knowledge_areas_canonical.json")
    )


@task(name="export_researchers_task")
def export_researchers_task(output_dir: str):
    logger.info("Starting Researchers export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_researchers(os.path.join(output_dir, "researchers_canonical.json"))


@task(name="export_researchers_tracking_task")
def export_researchers_tracking_task(output_dir: str):
    logger.info("Starting Researchers tracking export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_researchers_tracking(
        os.path.join(output_dir, "researchers_tracking.json")
    )


@task(name="export_groups_task")
def export_groups_task(output_dir: str, campus: Optional[str] = None):
    output_path = os.path.join(output_dir, "research_groups_canonical.json")
    logger.info(
        f"Starting Research Groups export to {output_path} (Filter: {campus})..."
    )
    sink = JsonSink()
    exporter = ResearchGroupExporter(sink=sink)
    exporter.export_all(output_path, campus_filter=campus)


@task(name="export_initiatives_task")
def export_initiatives_task(output_dir: str):
    logger.info("Starting Initiatives export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_initiatives(os.path.join(output_dir, "initiatives_canonical.json"))


@task(name="export_initiatives_tracking_task")
def export_initiatives_tracking_task(output_dir: str):
    logger.info("Starting Initiatives tracking export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_initiatives_tracking(
        os.path.join(output_dir, "initiatives_tracking.json")
    )


@task(name="export_initiative_types_task")
def export_initiative_types_task(output_dir: str):
    logger.info("Starting Initiative Types export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_initiative_types(
        os.path.join(output_dir, "initiative_types_canonical.json")
    )


@task(name="export_articles_task")
def export_articles_task(output_dir: str):
    logger.info("Starting Articles export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_articles(os.path.join(output_dir, "articles_canonical.json"))


@task(name="export_awards_task")
def export_awards_task(output_dir: str):
    logger.info("Starting Awards export...")
    exporter = CanonicalDataExporter(sink=JsonSink())
    exporter.export_awards(os.path.join(output_dir, "awards_canonical.json"))


@task(name="export_languages_task")
def export_languages_task(output_dir: str):
    logger.info("Starting Languages/Proficiencies export...")
    exporter = CanonicalDataExporter(sink=JsonSink())
    exporter.export_languages(os.path.join(output_dir, "languages_canonical.json"))
    exporter.export_proficiencies(
        os.path.join(output_dir, "proficiencies_canonical.json")
    )


@task(name="export_professional_activities_task")
def export_professional_activities_task(output_dir: str):
    logger.info("Starting Professional Activities export...")
    exporter = CanonicalDataExporter(sink=JsonSink())
    exporter.export_professional_activities(
        os.path.join(output_dir, "professional_activities_canonical.json")
    )


@task(name="export_research_productions_task")
def export_research_productions_task(output_dir: str):
    logger.info("Starting Research Productions export...")
    exporter = CanonicalDataExporter(sink=JsonSink())
    exporter.export_production_types(
        os.path.join(output_dir, "production_types_canonical.json")
    )
    exporter.export_research_productions(
        os.path.join(output_dir, "research_productions_canonical.json")
    )
    exporter.export_production_authors(
        os.path.join(output_dir, "production_authors_canonical.json")
    )


@task(name="export_advisorships_task")
def export_advisorships_task(output_dir: str):
    logger.info("Starting Advisorships export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_advisorships(
        os.path.join(output_dir, "advisorships_canonical.json")
    )


@task(name="export_advisorships_tracking_task")
def export_advisorships_tracking_task(output_dir: str):
    logger.info("Starting Advisorships tracking export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_advisorships_tracking(
        os.path.join(output_dir, "advisorships_tracking.json")
    )


@task(name="export_ingestion_runs_task")
def export_ingestion_runs_task(output_dir: str):
    logger.info("Starting Ingestion Runs export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_ingestion_runs(
        os.path.join(output_dir, "ingestion_runs_canonical.json")
    )


@task(name="export_source_records_task")
def export_source_records_task(output_dir: str):
    logger.info("Starting Source Records export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_source_records(
        os.path.join(output_dir, "source_records_canonical.json")
    )


@task(name="export_entity_matches_task")
def export_entity_matches_task(output_dir: str):
    logger.info("Starting Entity Matches export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_entity_matches(
        os.path.join(output_dir, "entity_matches_canonical.json")
    )


@task(name="export_attribute_assertions_task")
def export_attribute_assertions_task(output_dir: str):
    logger.info("Starting Attribute Assertions export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_attribute_assertions(
        os.path.join(output_dir, "attribute_assertions_canonical.json")
    )


@task(name="export_entity_change_logs_task")
def export_entity_change_logs_task(output_dir: str):
    logger.info("Starting Entity Change Logs export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_entity_change_logs(
        os.path.join(output_dir, "entity_change_logs_canonical.json")
    )


@task(name="export_fellowships_task")
def export_fellowships_task(output_dir: str):
    logger.info("Starting Fellowships export...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    exporter.export_fellowships(os.path.join(output_dir, "fellowships_canonical.json"))


@task(name="export_advisorship_analytics_task")
def export_advisorship_analytics_task(output_dir: str):
    logger.info("Starting Advisorship Analytics Mart generation...")
    sink = JsonSink()
    exporter = CanonicalDataExporter(sink=sink)
    input_path = os.path.join(output_dir, "advisorships_canonical.json")
    output_path = os.path.join(output_dir, "advisorship_analytics.json")
    exporter.generate_advisorship_mart(input_path, output_path)


@task(name="export_horizon_ids_task")
def export_horizon_ids_task(output_dir: str):
    """Spec 020: publishes the permanent ids and their aliases in two new
    files next to the existing exports, which keep their format. A database
    without ids (the assign_horizon_ids phase did not run) only logs a
    warning."""
    logger.info("Starting Horizon ids export...")
    try:
        store = SqliteHorizonIdStore(sqlite_path_from_url(os.getenv("DATABASE_URL")))
        write_id_file(store, output_dir)
        write_alias_file(store, output_dir)
    except Exception as exc:  # the new files must never sink the export
        logger.warning("Horizon ids export skipped: {}", exc)
    # Spec 021: status and dates of every source document, in a new file.
    try:
        from src.adapters.database.document_state_store import read_document_states
        from src.core.logic.document_skip import write_states_file

        db_path = sqlite_path_from_url(os.getenv("DATABASE_URL"))
        write_states_file(read_document_states(db_path), output_dir)
    except Exception as exc:
        logger.warning("Document states export skipped: {}", exc)


# Directories that live under the export folder but are NOT deliverables.
#
# * project_sigpesq_files_json -- INPUT: regenerable by
#   `make extract-project-files`, and carrying coordinator e-mail addresses in
#   clear text. The canonical exports built FROM it are already scrubbed -- the
#   enrichment payload drops those fields entirely -- so the raw corpus is kept
#   out of the walk and scrubbed copies are added to the zip explicitly.
# * formandos/, docentes/, mestrado/ -- formatted report views (HTML), not part
#   of the dataset.
# * parquet/ -- alternate format mirror; no longer emitted by the flow.
#
# The zip is versioned, so sweeping any of these in would put intermediate or
# redundant material -- or raw personal data -- into git.
SKIP_DIRS = {
    "project_sigpesq_files_json",
    "formandos",
    "docentes",
    "mestrado",
    "parquet",
}


# Where the archive build reports what its safety net replaced (counts only).
SCAN_REPORT_PATH = "data/reports/export_scan_report.json"

# The archive is committed to git; a build over this is refused (spec 029).
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024

MANIFEST_NAME = "export_manifest.json"

# Members the archive may carry; anything else is left out and logged.
_TEXT_EXTENSIONS = {".json", ".csv", ".html", ".md", ".txt"}


def _zip_date(path: str) -> tuple:
    """Zip date of a file, the way ``ZipFile.write`` takes it."""
    return zipfile.ZipInfo.from_file(path).date_time


def _write_scan_report(report: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SCAN_REPORT_PATH) or ".", exist_ok=True)
        with open(SCAN_REPORT_PATH, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError as exc:
        logger.warning("Export scan report not written: {}", exc)


@task(name="zip_exports_task")
def zip_exports_task(output_dir: str):
    zip_path = os.path.join(output_dir, "exports_canonical.zip")
    tmp_zip_path = zip_path + ".tmp"
    logger.info("Zipping exports to {}...", zip_path)
    # Spec 029: the safety net needs the key (tokens are keyed); fail early,
    # before anything is written, so the previous archive stays.
    key_fingerprint()
    started = time.monotonic()
    # A manifest in the folder is never carried: the one written below is the
    # only manifest the archive may hold.
    skip_names = {
        os.path.basename(zip_path),
        os.path.basename(tmp_zip_path),
        MANIFEST_NAME,
    }
    skipped_dirs = 0
    files_scanned = 0
    matches: dict[str, dict[str, int]] = {}
    left_out: list[dict[str, str]] = []

    def add_member(zf: zipfile.ZipFile, arcname: str, data: bytes, date_time):
        """Scan one text member; write it as is when clean, else replaced."""
        nonlocal files_scanned
        text = data.decode("utf-8")
        scanned, counts = scan_text(text)
        files_scanned += 1
        if any(counts.values()):
            matches[arcname] = counts
            info = zipfile.ZipInfo(arcname, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, scanned.encode("utf-8"))
            return True
        return False

    try:
        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(output_dir):
                # Prune in place so os.walk never descends into them.
                dirs.sort()
                pruned = [
                    d
                    for d in dirs
                    if d in SKIP_DIRS or d.startswith("exports_canonical")
                ]
                for d in pruned:
                    dirs.remove(d)
                    skipped_dirs += 1
                    logger.info("Excluded from zip (input, not output): {}/", d)
                for fname in sorted(files):
                    # No archive inside the archive: skip every nested .zip
                    # (data_snapshot.zip, a previous archive, anything else).
                    if fname in skip_names or fname.lower().endswith(".zip"):
                        continue
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, output_dir)
                    extension = os.path.splitext(fname)[1].lower()
                    if extension not in _TEXT_EXTENSIONS:
                        left_out.append({"file": arcname, "reason": "extension"})
                        logger.warning("Left out of the zip (extension): {}", arcname)
                        continue
                    with open(fpath, "rb") as fh:
                        data = fh.read()
                    try:
                        data.decode("utf-8")
                    except UnicodeDecodeError:
                        if extension == ".json":
                            raise
                        left_out.append({"file": arcname, "reason": "not utf-8"})
                        logger.warning("Left out of the zip (not utf-8): {}", arcname)
                        continue
                    if not add_member(zf, arcname, data, _zip_date(fpath)):
                        zf.write(fpath, arcname)

            # The SigPesq project documents are INPUT, not output (regenerable,
            # and carrying coordinator e-mails in clear text -- see SKIP_DIRS),
            # so the raw folder is pruned from the walk above. What ships instead
            # are scrubbed copies written here in memory: every e-mail/phone is
            # replaced by its LGPD token and the raw corpus stays untouched.
            pj_dir = os.path.join(output_dir, "project_sigpesq_files_json")
            if os.path.isdir(pj_dir):
                scrubbed_count = 0
                for fname in sorted(os.listdir(pj_dir)):
                    if not fname.startswith("PJ_") or not fname.endswith(".json"):
                        continue
                    try:
                        with open(os.path.join(pj_dir, fname), encoding="utf-8") as fh:
                            document = json.load(fh)
                    except (OSError, json.JSONDecodeError) as exc:
                        logger.warning(
                            "Skipped unreadable project document {}: {}", fname, exc
                        )
                        continue
                    arcname = os.path.join("project_sigpesq_files_json", fname)
                    data = json.dumps(
                        scrub_pii_deep(document), ensure_ascii=False, indent=2
                    ).encode("utf-8")
                    # Scrubbed copy: written in every case, after the scan.
                    if not add_member(
                        zf, arcname, data, _zip_date(os.path.join(pj_dir, fname))
                    ):
                        zf.writestr(arcname, data)
                    scrubbed_count += 1
                if scrubbed_count:
                    logger.info(
                        "Added {} scrubbed project documents to the zip",
                        scrubbed_count,
                    )

            # Spec 029: which key anonymized this archive, and whether it was
            # built by the official workflow. Written last; no timestamp, so
            # it adds no change of its own.
            manifest = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
            manifest.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(
                manifest,
                json.dumps(
                    {
                        "official": os.environ.get("GITHUB_ACTIONS") == "true",
                        "key_fingerprint": key_fingerprint(),
                    },
                    sort_keys=True,
                ),
            )
        size = os.path.getsize(tmp_zip_path)
        if size > MAX_ARCHIVE_BYTES:
            raise RuntimeError(
                f"The archive is {size} bytes, over the {MAX_ARCHIVE_BYTES} limit; "
                "the previous archive is kept"
            )
        os.replace(tmp_zip_path, zip_path)
    except BaseException:
        if os.path.exists(tmp_zip_path):
            os.unlink(tmp_zip_path)
        raise
    seconds = round(time.monotonic() - started, 2)
    _write_scan_report(
        {
            "files_scanned": files_scanned,
            "seconds": seconds,
            "matches": matches,
            "left_out": left_out,
        }
    )
    for name, counts in sorted(matches.items()):
        logger.warning("Export safety net replaced matches in {}: {}", name, counts)
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    logger.info("Exports zipped: {} ({:.1f} MB)", zip_path, size_mb)


@flow(name="Export Canonical Data Flow", **telegram_flow_state_handlers())
def export_canonical_data_flow(
    output_dir: str = "data/exports",
    campus: Optional[str] = None,
    zip_exports: bool = True,
):
    """
    Flow to export canonical data (Organizations, Campuses, Knowledge Areas, Researchers)
    AND Research Groups to JSON files.

    Args:
        output_dir: Directory where the JSON files will be saved. Defaults to 'data/exports'.
        campus: Optional name of the campus to filter by.
        zip_exports: Build the archive at the end (default, for in-process
            callers). The weekly passes False and runs the ``zip_exports``
            phase after the marts and the graph (spec 029).
    """
    # Ensure absolute path or relative to CWD
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.getcwd(), output_dir)

    os.makedirs(output_dir, exist_ok=True)

    # Run tasks in parallel or sequence
    export_organizations_task(output_dir)
    export_campuses_task(output_dir, campus)
    export_knowledge_areas_task(output_dir)
    export_researchers_task(output_dir)
    export_researchers_tracking_task(output_dir)
    export_groups_task(output_dir, campus)
    export_initiatives_task(output_dir)
    export_initiatives_tracking_task(output_dir)
    export_initiative_types_task(output_dir)
    export_articles_task(output_dir)
    export_awards_task(output_dir)
    export_languages_task(output_dir)
    export_professional_activities_task(output_dir)
    export_research_productions_task(output_dir)
    export_advisorships_task(output_dir)
    export_advisorships_tracking_task(output_dir)
    export_ingestion_runs_task(output_dir)
    export_source_records_task(output_dir)
    export_entity_matches_task(output_dir)
    export_attribute_assertions_task(output_dir)
    export_entity_change_logs_task(output_dir)
    export_fellowships_task(output_dir)
    export_advisorship_analytics_task(output_dir)
    export_people_relationship_graph_flow(output_dir=output_dir)
    export_people_collaboration_graph_flow(output_dir=output_dir)
    export_researchers_collaboration_graph_flow(output_dir=output_dir)
    export_students_collaboration_graph_flow(output_dir=output_dir)
    export_outside_ifes_collaboration_graph_flow(output_dir=output_dir)
    export_null_researchers_collaboration_graph_flow(output_dir=output_dir)
    export_research_group_membership_graphs_manifest_flow(output_dir=output_dir)
    export_horizon_ids_task(output_dir)
    if zip_exports:
        zip_exports_task(output_dir)


@flow(name="Zip Exports Flow", **telegram_flow_state_handlers())
def zip_exports_flow(output_dir: str = "data/exports"):
    """Builds exports_canonical.zip from the files already in ``output_dir``
    (spec 029). Its own phase, so the archive holds the current marts and
    graph."""
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.getcwd(), output_dir)
    zip_exports_task(output_dir)


if __name__ == "__main__":
    export_canonical_data_flow()
