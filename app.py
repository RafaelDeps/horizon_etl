import os
import sys

from dotenv import load_dotenv
from loguru import logger

from src.core.logic.pii_session_hook import install_lgpd_session_hooks
from src.flows.exports.canonical_data import export_canonical_data_flow
from src.flows.exports.initiatives_analytics_mart import (
    export_initiatives_analytics_mart_flow,
)
from src.flows.exports.knowledge_areas_mart import export_knowledge_areas_mart_flow
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
from src.flows.lattes.advisorships import ingest_lattes_advisorships_flow
from src.flows.lattes.complete import lattes_complete_flow
from src.flows.lattes.download import download_lattes_flow
from src.flows.lattes.projects import ingest_lattes_projects_flow

load_dotenv()

os.environ.setdefault("PREFECT_API_URL", "http://127.0.0.1:4200/api")

install_lgpd_session_hooks()


def _report_cnpq_summary(summary) -> None:
    """Torna visível o resultado da sincronização do CNPq.

    Emite os avisos estruturados no nível certo — URL inválida é ERROR, porque
    é defeito permanente de dado que se repete toda semana; falha de coleta é
    WARNING, porque o portal pode estar fora — e grava um relatório em
    ``data/reports/``, no mesmo padrão do backfill de LGPD, para que a cobertura
    da fase seja auditável depois sem depender de grep no log.
    """
    if not isinstance(summary, dict):
        return

    for aviso in summary.get("warnings", []):
        registrar = logger.error if aviso.get("severity") == "error" else logger.warning
        registrar(f"[{aviso.get('code')}] {aviso.get('message')}")

    logger.info(
        "CNPq sync: {}/{} grupos sincronizados | {} falha(s) de coleta | "
        "{} URL(s) inválida(s)",
        summary.get("success_count", 0),
        summary.get("total_groups", 0),
        summary.get("failed_count", 0),
        summary.get("invalid_url_count", 0),
    )

    try:
        import json as _json
        from datetime import datetime as _dt

        destino = os.path.join("data", "reports")
        os.makedirs(destino, exist_ok=True)
        caminho = os.path.join(
            destino, f"cnpq_sync_{_dt.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(caminho, "w", encoding="utf-8") as arquivo:
            _json.dump(summary, arquivo, ensure_ascii=False, indent=2)
        logger.info(f"CNPq sync report: {caminho}")
    except Exception as exc:  # relatório nunca pode derrubar a fase
        logger.warning(f"Could not write CNPq sync report: {exc}")


def main():
    """
    Main entry point for Horizon ETL.
    Allows running specific flows based on arguments or sequentially.
    """
    logger.info("Starting Horizon ETL Application")

    # Simple argument handling
    flow_to_run = sys.argv[1] if len(sys.argv) > 1 else "all"

    try:
        if flow_to_run == "full_pipeline":
            from src.flows.pipelines.unified import full_ingestion_pipeline

            campus_filter = sys.argv[2] if len(sys.argv) > 2 else None
            output_dir = sys.argv[3] if len(sys.argv) > 3 else "data/exports"
            logger.info(
                f"Executing FULL Pipeline (Campus: {campus_filter}, Output: {output_dir})"
            )
            full_ingestion_pipeline(campus_name=campus_filter, output_dir=output_dir)

        elif flow_to_run in ["weekly", "weekly_flows"]:
            campus_filter = sys.argv[2] if len(sys.argv) > 2 else None
            output_dir = sys.argv[3] if len(sys.argv) > 3 else "data/exports"
            logger.info(
                f"Executing WEEKLY Pipelines (Campus: {campus_filter or 'all'}, Output: {output_dir})"
            )
            # Process-isolated orchestration: each phase runs in its own
            # subprocess so a native crash (e.g. segfault in the browser-heavy
            # CNPq/Lattes phases) can't take the whole run and the exports down.
            from src.flows.pipelines.weekly_orchestrator import run_weekly

            sys.exit(run_weekly(campus_name=campus_filter, output_dir=output_dir))

        elif flow_to_run == "weekly_inprocess":
            from src.flows.pipelines.weekly import weekly_pipelines_flow

            campus_filter = sys.argv[2] if len(sys.argv) > 2 else None
            output_dir = sys.argv[3] if len(sys.argv) > 3 else "data/exports"
            logger.info("Executing WEEKLY Pipelines in a single process (legacy).")
            weekly_pipelines_flow(campus_name=campus_filter, output_dir=output_dir)

        elif flow_to_run == "all_sources":
            from src.flows.all import ingest_all_sources_flow

            campus_filter = sys.argv[2] if len(sys.argv) > 2 else None
            logger.info(
                f"Executing Flow: Ingest All Sources (Campus Filter: {campus_filter})"
            )
            ingest_all_sources_flow(campus_name=campus_filter)

        elif flow_to_run in ["sigpesq", "all"]:
            from src.flows.sigpesq.all import ingest_sigpesq_flow

            logger.info("Executing Flow: Ingest SigPesq")
            ingest_sigpesq_flow()

        if flow_to_run in ["cnpq_sync", "all"]:
            from src.flows.cnpq.groups import sync_cnpq_groups_flow

            campus_filter = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "cnpq_sync"
                else None
            )
            logger.info(
                f"Executing Flow: Sync CNPq Groups (Campus Filter: {campus_filter})"
            )
            cnpq_summary = sync_cnpq_groups_flow(campus_name=campus_filter)
            # O resumo era descartado aqui: `build_cnpq_sync_summary` produzia a
            # contagem de falhas e a lista de grupos, e nada consumia. Uma fase
            # podia deixar de coletar centenas de grupos e ainda sair com
            # código 0, porque o único sinal de sucesso é o exit code.
            _report_cnpq_summary(cnpq_summary)

        if flow_to_run in ["export_canonical", "all"]:
            # Optional output dir as 2nd arg if running specific flow
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "export_canonical"
                else "data/exports"
            )
            campus_filter = (
                sys.argv[3]
                if len(sys.argv) > 3 and flow_to_run == "export_canonical"
                else None
            )
            logger.info(
                f"Executing Flow: Export Canonical Data (Output: {output_dir}, Campus: {campus_filter})"
            )
            export_canonical_data_flow(output_dir=output_dir, campus=campus_filter)

        if flow_to_run in ["ka_mart", "all"]:
            output_path = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "ka_mart"
                else "data/exports/knowledge_areas_mart.json"
            )
            campus_filter = (
                sys.argv[3] if len(sys.argv) > 3 and flow_to_run == "ka_mart" else None
            )
            logger.info(
                f"Executing Flow: Export Knowledge Area Mart (Output: {output_path}, Campus: {campus_filter})"
            )
            export_knowledge_areas_mart_flow(
                output_path=output_path, campus=campus_filter
            )

        if flow_to_run in ["analytics_mart", "all"]:
            output_path = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "analytics_mart"
                else "data/exports/initiatives_analytics_mart.json"
            )
            logger.info(
                f"Executing Flow: Export Initiative Analytics Mart (Output: {output_path})"
            )
            export_initiatives_analytics_mart_flow(output_path=output_path)

        if flow_to_run in ["people_graph", "all"]:
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "people_graph"
                else "data/exports"
            )
            logger.info(
                f"Executing Flow: Export People Relationship Graph (Output Dir: {output_dir})"
            )
            export_people_relationship_graph_flow(output_dir=output_dir)

        if flow_to_run in ["rg_membership_manifest", "all"]:
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "rg_membership_manifest"
                else "data/exports"
            )
            logger.info(
                f"Executing Flow: Export Research Group Membership Graphs Manifest (Output Dir: {output_dir})"
            )
            export_research_group_membership_graphs_manifest_flow(output_dir=output_dir)

        if flow_to_run in ["students_collaboration_graph", "all"]:
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "students_collaboration_graph"
                else "data/exports"
            )
            logger.info(
                f"Executing Flow: Export Students Collaboration Graph (Output Dir: {output_dir})"
            )
            export_students_collaboration_graph_flow(output_dir=output_dir)

        if flow_to_run in ["null_researchers_collaboration_graph", "all"]:
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2
                and flow_to_run == "null_researchers_collaboration_graph"
                else "data/exports"
            )
            logger.info(
                f"Executing Flow: Export Null-Classification Collaboration Graph (Output Dir: {output_dir})"
            )
            export_null_researchers_collaboration_graph_flow(output_dir=output_dir)

        if flow_to_run in ["outside_ifes_collaboration_graph", "all"]:
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2
                and flow_to_run == "outside_ifes_collaboration_graph"
                else "data/exports"
            )
            logger.info(
                f"Executing Flow: Export Outside-IFES Collaboration Graph (Output Dir: {output_dir})"
            )
            export_outside_ifes_collaboration_graph_flow(output_dir=output_dir)

        if flow_to_run in ["researchers_collaboration_graph", "all"]:
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2
                and flow_to_run == "researchers_collaboration_graph"
                else "data/exports"
            )
            logger.info(
                f"Executing Flow: Export Researchers Collaboration Graph (Output Dir: {output_dir})"
            )
            export_researchers_collaboration_graph_flow(output_dir=output_dir)

        if flow_to_run in ["collaboration_graph", "all"]:
            output_dir = (
                sys.argv[2]
                if len(sys.argv) > 2 and flow_to_run == "collaboration_graph"
                else "data/exports"
            )
            logger.info(
                f"Executing Flow: Export People Collaboration Graph (Output Dir: {output_dir})"
            )
            export_people_collaboration_graph_flow(output_dir=output_dir)

        if flow_to_run == "lattes_download":
            logger.info("Executing Flow: Download Lattes Curricula")
            download_lattes_flow()

        if flow_to_run in ["ingest_lattes_projects", "all"]:
            logger.info("Executing Flow: Ingest Lattes Projects")
            ingest_lattes_projects_flow()

        if flow_to_run == "lattes_advisorships":
            logger.info("Executing Flow: Ingest Lattes Advisorships")
            ingest_lattes_advisorships_flow()

        if flow_to_run == "consolidate_duplicates":
            from src.scripts.consolidate_duplicates import run_person_dedup

            logger.info("Executing Flow: Consolidate Duplicate Persons")
            report = run_person_dedup()
            logger.info(
                "Person dedup finished: {} records merged, {} groups refused "
                "(report: {}).",
                report["records_merged"],
                report["refused_groups"],
                report["report_path"],
            )

        if flow_to_run == "enrich_projects":
            from src.flows.sigpesq.enrich_projects import enrich_projects_flow

            logger.info("Executing Flow: Enrich SigPesq Projects")
            enrich_projects_flow()

        if flow_to_run == "mark_reviewed":
            # Operational utility, not ingestion: records that a person checked
            # an auto-created initiative, which is the ONLY way its review flag
            # comes off.
            #
            #   python app.py mark_reviewed <initiative_id> <reviewer>
            #
            # Use a NON-PERSONAL identifier for <reviewer> -- registration
            # number or initials. It travels into the exported catalogue, and
            # the project forbids personal data such as e-mail in any output.
            from src.core.logic.project_enrichment import ProjectEnrichmentLoader

            if len(sys.argv) < 4:
                logger.error(
                    "Usage: python app.py mark_reviewed <initiative_id> <reviewer>"
                )
                sys.exit(2)
            loader = ProjectEnrichmentLoader()
            ok = loader.mark_reviewed(int(sys.argv[2]), sys.argv[3])
            sys.exit(0 if ok else 1)

        if flow_to_run == "backfill_enrichment_origin":
            # Repairs a database whose payloads already lost the origin. Not part
            # of the weekly run: it rebuilds the database each time, so this
            # would be dead weight there.
            from src.core.logic.project_enrichment import ProjectEnrichmentLoader

            logger.info("Rebuilding initiative origin from the audit trail")
            logger.info(
                f"Done: {ProjectEnrichmentLoader().backfill_origin_from_tracking()}"
            )

        if flow_to_run == "extract_project_files":
            from src.flows.sigpesq.project_files import extract_project_files_flow

            # Optional limit, to keep smoke tests cheap. Accepted as a positional
            # (make extract-project-files) or via env var, which is how the
            # weekly phase subprocess passes it down.
            raw_limit = (
                sys.argv[2]
                if len(sys.argv) > 2 and sys.argv[2]
                else os.getenv("HORIZON_PROJECT_FILES_LIMIT", "")
            )
            limit = int(raw_limit) if raw_limit else None
            logger.info("Executing Flow: Extract SigPesq Project Files")
            extract_project_files_flow(limit=limit)

        if flow_to_run == "lattes_full":
            logger.info("Executing Flow: Lattes Complete Pipeline")
            lattes_complete_flow()

        elif flow_to_run == "anonymize_backfill":
            from src.flows.maintenance.anonymize_backfill import anonymize_backfill_flow

            logger.info("Executing Flow: LGPD PII Anonymize Backfill")
            anonymize_backfill_flow()

    except Exception as e:
        logger.error(f"Application failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
