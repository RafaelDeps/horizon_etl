import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from loguru import logger as summary_logger
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from prefect.utilities.annotations import quote
from research_domain import CampusController, ResearchGroupController
from research_domain.controllers import ResearcherController

from src.adapters.sources.cnpq_crawler import CnpqCrawlerAdapter, normalize_cnpq_url
from src.adapters.sources.raw_store import FileCnpqPageStore
from src.core.logic.document_skip import order_free
from src.core.logic.horizon_identity import cnpq_group_id_from_url, cnpq_payload_key
from src.core.logic.initiative_identity import normalize_text
from src.core.logic.raw_rotation import (
    counts_line,
    download_counts,
    plan_downloads,
    refresh_settings,
)
from src.core.logic.researcher_resolution import load_researcher_index
from src.core.logic.strategies.cnpq_sync import CnpqSyncLogic
from src.core.ports.document_state_store import ACTIVE, DocumentFailed
from src.flows.cnpq.concurrent_fetch import FetchOutcome, fetch_all, resolve_workers
from src.flows.document_phase import document_phase
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
        # The CNPq id from the mirror URL, not research_groups.id (spec 020).
        source_record_id=cnpq_payload_key(url),
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


def _sync_group_document(
    skip, g_info: dict, outcome, researcher_index, downloaded_at=None
):
    """One CNPq group page as a source document (spec 021): skipped when the
    page is unchanged, written in one transaction otherwise. A page that could
    not be fetched is a failed download and changes nothing."""
    res = {
        "success": True,
        "group_id": g_info["id"],
        "group_name": g_info["name"],
        "url": g_info["url"],
    }
    with skip.document(
        cnpq_payload_key(g_info["url"]), downloaded_at=downloaded_at
    ) as doc:
        if not outcome.data:
            res["success"] = False
            raise DocumentFailed("download", g_info["url"])
        if doc.unchanged(order_free(outcome.data)):
            res["skipped"] = True
            return res
        doc.begin()
        # The group row is the page's own subject: left out of the total-loss
        # count (spec 021).
        doc.carry("research_group", g_info["id"], is_subject=True)
        res["success"] = False  # stays False if the sync raises (rolled back)
        # quote(): Prefect would otherwise walk the ~7.6k-entry index (and the
        # payload) on every task call.
        res = sync_single_group(
            g_info,
            data=quote(outcome.data),
            researcher_index=quote(researcher_index),
        )
    return res


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

    # Opened before any controller: their sessions must bind to the shared
    # connection of the document transactions (spec 021).
    with document_phase("cnpq_group") as skip:
        return _sync_cnpq_groups(campus_name, skip, logger)


def _active_in_sigpesq(groups: list, skip, logger) -> list:
    """Spec 021 (R8): a group whose SigPesq report row is gone is not fetched
    any more; its CNPq document then becomes inactive by the listing. A group
    with no SigPesq state (a database from before spec 021) is kept."""
    states = skip.store.load("sigpesq_group")
    if not states:
        return groups
    kept = []
    for g in groups:
        state = states.get(normalize_text(g["name"] or ""))
        if state is None or state.status == ACTIVE:
            kept.append(g)
    if len(kept) < len(groups):
        logger.info(
            f"{len(groups) - len(kept)} group(s) inactive in SigPesq: not fetched"
        )
    return kept


def _sigpesq_listing_complete(skip) -> bool:
    """The CNPq listing is complete only when the SigPesq groups report of the
    same weekly was a complete listing: some ``sigpesq_group`` state was seen
    at or after the weekly start (R8). Outside a weekly it is never complete."""
    started = os.getenv("HORIZON_WEEKLY_STARTED_AT")
    if not started:
        return False
    states = skip.store.load("sigpesq_group").values()
    return any((s.last_seen_at or "") >= started for s in states)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sync_cnpq_groups(campus_name: Optional[str], skip, logger):
    to_sync = get_groups_to_sync(campus_name=campus_name)
    groups = _active_in_sigpesq(to_sync["valid"], skip, logger)
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

    def reload_caches():
        # A rolled-back group may have created researchers the index holds.
        researcher_index[:] = load_researcher_index(session)

    skip.on_rollback = reload_caches

    # Spec 023: only new groups plus a rotating share of the stored pages are
    # downloaded; the other groups are processed from their stored page, and
    # so is a group whose download fails (older data is better than none).
    store = FileCnpqPageStore()
    share, full = refresh_settings()
    ids = [cnpq_group_id_from_url(g["url"]) for g in groups]
    plan = plan_downloads(
        ids, store.stored(), share=share, full=full and campus_name is None
    )
    wanted = set(plan.to_download)
    fetch_position = {}
    to_fetch = []
    for g_info, group_id in zip(groups, ids):
        if group_id in wanted and group_id not in fetch_position:
            fetch_position[group_id] = len(to_fetch)
            to_fetch.append(g_info)

    results = []
    outcomes = []
    failed_downloads = []
    now = _now()
    batch = fetch_all(to_fetch, CnpqCrawlerAdapter, workers, sleep=_SLEEP)
    try:
        with tracking_recorder.run_context(
            source_system="cnpq_sync", flow_name="cnpq_sync"
        ):
            for i, g_info in enumerate(groups):
                group_id = ids[i]
                downloaded_at = None
                if group_id in fetch_position:
                    outcome = batch.outcome(fetch_position[group_id])
                    outcomes.append(outcome)
                    if outcome.data:
                        store.save(group_id, g_info["url"], outcome.data, now)
                        downloaded_at = now
                    else:
                        if group_id not in failed_downloads:
                            failed_downloads.append(group_id)
                        stored = store.load(group_id)
                        if stored is not None:
                            outcome = FetchOutcome(
                                i, g_info, stored["page"], outcome.attempts
                            )
                            downloaded_at = stored.get("downloaded_at")
                else:
                    stored = store.load(group_id)
                    outcome = FetchOutcome(
                        i, g_info, stored["page"] if stored else None, 0
                    )
                    downloaded_at = stored.get("downloaded_at") if stored else None
                res = _sync_group_document(
                    skip, g_info, outcome, researcher_index, downloaded_at
                )
                results.append(res)
    finally:
        batch.close()
    counts = download_counts(plan, failed_downloads)
    summary_logger.info(counts_line("cnpq", counts))
    skip.downloads = counts

    # The listing (R8): partial with a campus filter or without a complete
    # SigPesq listing in the same weekly; then no group changes status.
    skip.finish(
        [cnpq_payload_key(g["url"]) for g in groups],
        complete=campus_name is None and _sigpesq_listing_complete(skip),
    )

    counters = CnpqSyncLogic.researcher_counters
    summary_logger.info(
        f"CNPq fetch: workers={workers} "
        f"fetched={sum(1 for o in outcomes if o.data)} "
        f"retries={sum(max(o.attempts - 1, 0) for o in outcomes)} "
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
