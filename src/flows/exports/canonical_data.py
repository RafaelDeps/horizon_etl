import os
import zipfile
from typing import Optional

from loguru import logger
from prefect import flow, task

from src.adapters.sinks.json_sink import JsonSink
from src.core.logic.canonical_exporter import CanonicalDataExporter
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


@task(name="export_parquet_task")
def export_parquet_task(output_dir: str):
    """Emit a Parquet mirror of the canonical JSON exports under ``<output_dir>/parquet``.

    Tables become ``<name>.parquet``; top-level node-link graphs are split into
    ``<name>.nodes.parquet`` + ``<name>.edges.parquet`` + ``<name>.meta.json``.
    """
    from src.scripts.export_parquet import convert_dir

    dst = os.path.join(output_dir, "parquet")
    stats = convert_dir(output_dir, dst)
    logger.info("Parquet export: {} -> {}", stats, dst)


# Directories that live under the export folder but are INPUT, not output.
#
# The SigPesq project documents are raw material: regenerable by
# `make extract-project-files`, and carrying coordinator names and e-mail
# addresses in clear text. The canonical exports built FROM them are already
# scrubbed -- the enrichment payload drops those fields entirely -- so shipping
# the sources alongside the results would smuggle back exactly the personal data
# the rest of the pipeline is careful to anonymize. The zip is versioned, so this
# would put those addresses in git.
SKIP_DIRS = {"project_sigpesq_files_json"}


@task(name="zip_exports_task")
def zip_exports_task(output_dir: str):
    zip_path = os.path.join(output_dir, "exports_canonical.zip")
    tmp_zip_path = zip_path + ".tmp"
    logger.info("Zipping exports to {}...", zip_path)
    skip_names = {os.path.basename(zip_path), os.path.basename(tmp_zip_path)}
    skipped_dirs = 0
    try:
        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(output_dir):
                # Prune in place so os.walk never descends into them.
                pruned = [d for d in dirs if d in SKIP_DIRS]
                for d in pruned:
                    dirs.remove(d)
                    skipped_dirs += 1
                    logger.info("Excluded from zip (input, not output): {}/", d)
                for fname in files:
                    if fname in skip_names:
                        continue
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, output_dir)
                    zf.write(fpath, arcname)
        os.replace(tmp_zip_path, zip_path)
    except BaseException:
        if os.path.exists(tmp_zip_path):
            os.unlink(tmp_zip_path)
        raise
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    logger.info("Exports zipped: {} ({:.1f} MB)", zip_path, size_mb)


@flow(name="Export Canonical Data Flow", **telegram_flow_state_handlers())
def export_canonical_data_flow(
    output_dir: str = "data/exports", campus: Optional[str] = None
):
    """
    Flow to export canonical data (Organizations, Campuses, Knowledge Areas, Researchers)
    AND Research Groups to JSON files.

    Args:
        output_dir: Directory where the JSON files will be saved. Defaults to 'data/exports'.
        campus: Optional name of the campus to filter by.
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
    export_parquet_task(output_dir)
    zip_exports_task(output_dir)


if __name__ == "__main__":
    export_canonical_data_flow()
