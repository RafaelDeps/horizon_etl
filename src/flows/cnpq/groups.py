import os
import re
import time
from typing import Optional

from dotenv import load_dotenv
from loguru import logger as summary_logger
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from prefect.utilities.annotations import quote
from research_domain import CampusController, ResearchGroupController
from research_domain.controllers import ResearcherController

from src.adapters.sources.cnpq_crawler import CnpqCrawlerAdapter, normalize_cnpq_url
from src.core.logic.researcher_resolution import load_researcher_index
from src.core.logic.strategies.cnpq_sync import CnpqSyncLogic
from src.flows.cnpq.concurrent_fetch import fetch_all, resolve_workers
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder

load_dotenv()

# Back-off sleep used by the concurrent fetcher; tests replace it.
_SLEEP = time.sleep

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


# Distinguishes "the flow already fetched this group (maybe with no data)" from
# "fetch it here", the original per-group behaviour kept for direct callers.
_NOT_FETCHED = object()


@task(cache_policy=NO_CACHE)
def sync_single_group(
    group_info: dict, data=_NOT_FETCHED, researcher_index: Optional[list] = None
):
    """
    Synchronizes a single research group.

    The flow fetches pages concurrently and passes each group's ``data`` here,
    so every database write still happens in this task, one group at a time
    (spec 017). Called with ``group_info`` alone, it fetches the page itself.
    """
    logger = get_run_logger()
    url = group_info["url"]
    group_id = group_info["id"]
    group_name = group_info["name"]

    logger.info(f"Synchronizing group: {group_name} ({url})")

    adapter = CnpqCrawlerAdapter()
    sync_logic = CnpqSyncLogic()

    # 1. Extract data
    if data is _NOT_FETCHED:
        data = adapter.get_group_data(url)
    if not data:
        logger.error(f"Failed to extract data for {group_name}")
        return {
            "success": False,
            "group_id": group_id,
            "group_name": group_name,
            "url": url,
        }
    source_record = tracking_recorder.record_source_record(
        source_entity_type="cnpq_group_payload",
        payload=data,
        source_record_id=str(group_id),
        source_file=url,
        source_path=url,
    )

    # 2. Sync group info
    sync_logic.sync_group(
        group_id,
        data,
        source_record_id=getattr(source_record, "id", None),
    )

    # 3. Extract and sync members
    members = adapter.extract_members(data)

    # 3.1 Extract and merge Leaders
    leaders = adapter.extract_leaders(data)
    if leaders:
        logger.info(f"Found {len(leaders)} leaders to sync.")
        for leader_name in leaders:
            # Check if leader is already in members list to avoid duplication (though sync_members handles it)
            # We want to ensure they get the 'Líder' role if desired, or just ensure existence.
            # If we add them as 'Líder', they might have double roles (Researcher + Leader), which is fine.
            members.append(
                {
                    "name": leader_name,
                    "role": "Líder",
                    "data_inicio": None,  # Leaders usually started with the group, but we don't have specific data here
                    "data_fim": None,
                }
            )

    from collections import Counter

    roles_count = Counter(m.get("role") for m in members)
    logger.info(
        f"Extracted {len(members)} members for {group_name}: {dict(roles_count)}"
    )
    if researcher_index is None:
        sync_logic.sync_members(group_id, members, source_file=url)
    else:
        sync_logic.sync_members(
            group_id, members, source_file=url, researcher_index=researcher_index
        )

    # 4. Extract and sync Research Lines (Knowledge Areas)
    lines = adapter.extract_research_lines(data)
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


@flow(name="Sync CNPq Research Groups", **telegram_flow_state_handlers())
def sync_cnpq_groups_flow(campus_name: Optional[str] = None):
    """
    Prefect flow to synchronize research groups with CNPq DGP mirror.
    """
    logger = get_run_logger()
    logger.info(f"Starting CNPq Synchronization Flow (Filter: {campus_name or 'None'})")

    to_sync = get_groups_to_sync(campus_name=campus_name)
    groups = to_sync["valid"]
    invalid_groups = to_sync["invalid"]

    # Pages are fetched concurrently (the portal wait was 71% of the phase);
    # every database write stays here, one group at a time, in the original
    # order — SQLite allows a single writer (spec 017).
    workers = resolve_workers(os.getenv("HORIZON_CNPQ_WORKERS"))

    # One read of the researcher register per phase, not per group (TD-008):
    # same researchers, same id order as ResearcherController().get_all().
    CnpqSyncLogic.reset_researcher_counters()
    session = None
    try:
        session = ResearcherController()._service._repository._session
    except Exception:
        logger.warning("Could not reach the DB session; researcher index is empty.")
    researcher_index = load_researcher_index(session)
    researcher_index_loaded = len(researcher_index)

    results = []
    outcomes = []
    batch = fetch_all(groups, CnpqCrawlerAdapter, workers, sleep=_SLEEP)
    try:
        with tracking_recorder.run_context(
            source_system="cnpq_sync", flow_name="cnpq_sync"
        ):
            for i, g_info in enumerate(groups):
                outcome = batch.outcome(i)
                outcomes.append(outcome)
                # quote(): Prefect would otherwise walk the ~7.6k-entry index
                # (and the payload) on every task call.
                res = sync_single_group(
                    g_info,
                    data=quote(outcome.data),
                    researcher_index=quote(researcher_index),
                )
                results.append(res)
    finally:
        batch.close()

    counters = CnpqSyncLogic.researcher_counters
    summary_logger.info(
        f"CNPq fetch: workers={workers} "
        f"fetched={sum(1 for o in outcomes if o.data)} "
        f"retries={sum(o.attempts - 1 for o in outcomes)} "
        f"failed_after_retries={sum(1 for o in outcomes if not o.data)} "
        f"concurrency_reductions={batch.gate.reductions} "
        f"researcher_index_loaded={researcher_index_loaded} "
        f"researcher_hits={counters['hits']} "
        f"researcher_created={counters['created']}"
    )

    success_count = sum(1 for r in results if r.get("success"))
    summary = build_cnpq_sync_summary(results, invalid_groups)
    logger.info(
        f"Flow finished. Successfully synchronized {success_count}/{len(groups)} groups."
    )
    return summary


if __name__ == "__main__":
    sync_cnpq_groups_flow()
