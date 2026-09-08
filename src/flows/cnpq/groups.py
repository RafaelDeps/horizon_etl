import os
import re
from typing import Optional

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task
from prefect.task_runners import ProcessPoolTaskRunner
from research_domain import CampusController, ResearchGroupController
from research_domain.controllers import ResearcherController

from src.adapters.sources.cnpq_crawler import normalize_cnpq_url
from src.core.logic.researcher_resolution import ResearcherRef, load_researcher_index
from src.core.logic.strategies.cnpq_sync import CnpqSyncLogic
from src.flows.cnpq.fetch_worker import fetch_group
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder

load_dotenv()

# Concurrent CNPq portal fetches. 4 is the level already agreed for this
# portal (see specs/012-cnpq-concurrent-fetch/research.md R5); set to 1 to
# reproduce the pre-012 fully sequential behavior without a code change.
CNPQ_FETCH_CONCURRENCY = int(os.getenv("CNPQ_FETCH_CONCURRENCY", "4"))

# O espelho do DGP resolve por um identificador de 16 dígitos. Das 345 URLs da
# planilha do SigPesq, 344 seguem exatamente este formato; a exceção é digitação
# manual no portal de origem.
DGP_MIRROR_URL = re.compile(
    r"^https?://dgp\.cnpq\.br/dgp/espelhogrupo/\d{16}$", re.IGNORECASE
)


@task
def get_groups_to_sync(
    limit: Optional[int] = None, offset: int = 0, campus_name: Optional[str] = None
):
    """
    Fetches research groups that have a CNPq URL, optionally filtering by campus name.
    """
    logger = get_run_logger()
    logger.info("Fetching research groups with CNPq URLs...")

    rg_ctrl = ResearchGroupController()
    all_groups = rg_ctrl.get_all()

    # Campus filtering if requested
    campus_id = None
    if campus_name:
        logger.info(f"Filtering by campus matching: '{campus_name}'")
        campus_ctrl = CampusController()
        campuses = campus_ctrl.get_all()
        matching_campuses = [
            c for c in campuses if campus_name.lower() in c.name.lower()
        ]

        if not matching_campuses:
            logger.warning(
                f"No campus found matching '{campus_name}'. Proceeding with no results."
            )
            return {"valid": [], "invalid": []}

        if len(matching_campuses) > 1:
            logger.warning(
                f"Multiple campuses match '{campus_name}': {[c.name for c in matching_campuses]}. Using the first one: {matching_campuses[0].name}"
            )

        campus_id = matching_campuses[0].id
        logger.info(f"Using Campus ID {campus_id} for filtering.")

    sync_list = []
    invalid_list = []
    for g in all_groups:
        if getattr(g, "cnpq_url", None):
            # Check campus filter
            if campus_id and getattr(g, "campus_id", None) != campus_id:
                continue

            url = normalize_cnpq_url(g.cnpq_url)
            if not DGP_MIRROR_URL.match(url):
                # Defeito permanente de dado, não indisponibilidade do portal.
                # Tentar mesmo assim custa ~36 s (o wait_for_selector espera
                # 10 s e o retry relança o Chromium três vezes) e produz um
                # "Timeout exceeded" idêntico ao do CNPq fora do ar — o que
                # torna impossível distinguir os dois casos no log.
                invalid_list.append({"id": g.id, "name": g.name, "url": g.cnpq_url})
                continue

            sync_list.append({"id": g.id, "name": g.name, "url": url})

    if invalid_list:
        logger.warning(
            f"{len(invalid_list)} grupo(s) com cnpq_url sem o identificador de 16 "
            f"dígitos do DGP — não serão coletados, e o dado precisa ser corrigido "
            f"no SigPesq: "
            + "; ".join(f"{g['id']} {g['name']} → {g['url']}" for g in invalid_list[:5])
        )

    # Simple slicing for limit/offset
    if limit is not None:
        sync_list = sync_list[offset : offset + limit]
        logger.info(
            f"Batched {len(sync_list)} groups (offset={offset}, limit={limit})."
        )
    else:
        logger.info(f"Found {len(sync_list)} groups to synchronize.")

    return {"valid": sync_list, "invalid": invalid_list}


def _write_group_result(
    fetch_result: dict, sync_logic: "CnpqSyncLogic", researcher_index: list
):
    """
    Writes one already-fetched group's data to the database.

    This is the serial half of the fetch/write split introduced in
    specs/012-cnpq-concurrent-fetch/: fetching runs concurrently in separate
    processes (see ``fetch_group`` in ``src.flows.cnpq.fetch_worker``), but
    this function -- and the ``researcher_index`` list it mutates via
    ``sync_members`` -- MUST only ever be called directly, one group at a
    time, never via ``.submit()``. See
    specs/012-cnpq-concurrent-fetch/contracts/fetch_write_contract.md for why.

    ``researcher_index`` is built once per flow run (see
    ``sync_cnpq_groups_flow``) and shared across every group, instead of each
    call re-reading the full researcher registry -- see
    specs/011-cnpq-sync-index-reuse/research.md R1.
    """
    logger = get_run_logger()
    group_id = fetch_result["group_id"]
    group_name = fetch_result["group_name"]
    url = fetch_result["url"]
    data = fetch_result["data"]

    source_record = tracking_recorder.record_source_record(
        source_entity_type="cnpq_group_payload",
        payload=data,
        source_record_id=str(group_id),
        source_file=url,
        source_path=url,
    )

    # 1. Sync group info
    sync_logic.sync_group(
        group_id,
        data,
        source_record_id=getattr(source_record, "id", None),
    )

    # 2. Sync members (leaders already merged in by fetch_group)
    members = fetch_result["members"]
    from collections import Counter

    roles_count = Counter(m.get("role") for m in members)
    logger.info(
        f"Extracted {len(members)} members for {group_name}: {dict(roles_count)}"
    )
    sync_logic.sync_members(
        group_id, members, source_file=url, researcher_index=researcher_index
    )

    # 3. Sync Research Lines (Knowledge Areas)
    lines = fetch_result["research_lines"]
    logger.info(f"Extracted {len(lines)} research lines for {group_name}")
    sync_logic.sync_knowledge_areas(group_id, lines, source_file=url)

    return {
        "success": True,
        "group_id": group_id,
        "group_name": group_name,
        "url": url,
    }


def build_cnpq_sync_summary(
    results: list[dict], invalid_groups: Optional[list[dict]] = None
) -> dict:
    failed_groups = [
        {
            "group_id": result.get("group_id"),
            "group_name": result.get("group_name"),
            "url": result.get("url"),
        }
        for result in results
        if not result.get("success")
    ]
    warnings = []
    if failed_groups:
        warnings.append(
            {
                "source": "cnpq",
                "severity": "warning",
                "code": "cnpq_group_sync_failed",
                "count": len(failed_groups),
                "examples": failed_groups[:5],
                "message": (
                    f"CNPq sync failed for {len(failed_groups)} group(s); "
                    "inspect URLs or portal availability."
                ),
            }
        )

    invalid_groups = invalid_groups or []
    if invalid_groups:
        # Código distinto de propósito: URL inválida é defeito permanente, cujo
        # dono é quem cura o dado no SigPesq. Falha de coleta é transitória, e
        # o dono é o portal. Sob o mesmo código, um esconde o outro.
        warnings.append(
            {
                "source": "cnpq",
                "severity": "error",
                "code": "cnpq_group_url_invalid",
                "count": len(invalid_groups),
                "examples": invalid_groups[:5],
                "message": (
                    f"{len(invalid_groups)} grupo(s) com cnpq_url fora do formato "
                    "do espelho DGP; corrigir o cadastro no SigPesq."
                ),
            }
        )

    return {
        "source": "cnpq",
        "total_groups": len(results),
        "success_count": len(results) - len(failed_groups),
        "failed_count": len(failed_groups),
        "failed_groups": failed_groups,
        "invalid_url_count": len(invalid_groups),
        "invalid_url_groups": invalid_groups,
        "warnings": warnings,
    }


@flow(
    name="Sync CNPq Research Groups",
    task_runner=ProcessPoolTaskRunner(max_workers=CNPQ_FETCH_CONCURRENCY),
    **telegram_flow_state_handlers(),
)
def sync_cnpq_groups_flow(campus_name: Optional[str] = None):
    """
    Prefect flow to synchronize research groups with CNPq DGP mirror.

    Fetching each group's page runs concurrently, in separate processes
    (``CNPQ_FETCH_CONCURRENCY`` workers, see ``fetch_group`` in
    ``src.flows.cnpq.fetch_worker``). Writing to the database stays strictly
    serial: futures are consumed in submission order, and ``_write_group_result``
    is always called directly -- never via ``.submit()`` -- so at most one
    group's write is ever in progress. See
    specs/012-cnpq-concurrent-fetch/contracts/fetch_write_contract.md for why
    this separation exists and must be preserved.
    """
    logger = get_run_logger()
    logger.info(f"Starting CNPq Synchronization Flow (Filter: {campus_name or 'None'})")

    to_sync = get_groups_to_sync(campus_name=campus_name)
    groups = to_sync["valid"]
    invalid_groups = to_sync["invalid"]

    # Read the researcher registry once for the whole run, not once per
    # group: ResearcherController().get_all() eagerly loads four unrelated
    # collections per researcher and costs ~8.8s per call against the current
    # data, versus 0.03s for this lightweight index -- 351 groups paid that
    # cost separately before. See specs/011-cnpq-sync-index-reuse/research.md.
    session = ResearcherController()._service._repository._session
    researcher_index: list[ResearcherRef] = load_researcher_index(session)
    logger.info(f"Researcher index loaded with {len(researcher_index)} entries")

    sync_logic = CnpqSyncLogic()

    results = []
    with tracking_recorder.run_context(
        source_system="cnpq_sync", flow_name="cnpq_sync"
    ):
        # Submit every fetch up front (bounded by CNPQ_FETCH_CONCURRENCY
        # worker processes), then consume results IN SUBMISSION ORDER --
        # deterministic and reproducible, at the cost of the writer
        # occasionally waiting on a slower group instead of taking whichever
        # finishes first. See specs/012-cnpq-concurrent-fetch/research.md R4.
        futures = [fetch_group.submit(g_info) for g_info in groups]

        for g_info, future in zip(groups, futures):
            fetch_result = future.result()
            if not fetch_result["success"]:
                logger.error(f"Failed to extract data for {g_info['name']}")
                results.append(fetch_result)
                continue
            # Direct call, never .submit(): this is what keeps the write
            # step -- and the researcher_index it mutates -- strictly serial.
            res = _write_group_result(fetch_result, sync_logic, researcher_index)
            results.append(res)

    success_count = sum(1 for r in results if r.get("success"))
    summary = build_cnpq_sync_summary(results, invalid_groups)
    logger.info(
        f"Flow finished. Successfully synchronized {success_count}/{len(groups)} groups."
    )
    return summary


if __name__ == "__main__":
    sync_cnpq_groups_flow()
