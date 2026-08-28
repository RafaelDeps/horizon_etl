import re
from typing import Optional

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task
from research_domain import CampusController, ResearchGroupController

from src.adapters.sources.cnpq_crawler import CnpqCrawlerAdapter, normalize_cnpq_url
from src.core.logic.strategies.cnpq_sync import CnpqSyncLogic
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder

load_dotenv()

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
            return []

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


@task
def sync_single_group(group_info: dict):
    """
    Synchronizes a single research group.
    """
    logger = get_run_logger()
    url = group_info["url"]
    group_id = group_info["id"]
    group_name = group_info["name"]

    logger.info(f"Synchronizing group: {group_name} ({url})")

    adapter = CnpqCrawlerAdapter()
    sync_logic = CnpqSyncLogic()

    # 1. Extract data
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
    sync_logic.sync_members(group_id, members, source_file=url)

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

    results = []
    with tracking_recorder.run_context(
        source_system="cnpq_sync", flow_name="cnpq_sync"
    ):
        for g_info in groups:
            res = sync_single_group(g_info)
            results.append(res)

    success_count = sum(1 for r in results if r.get("success"))
    summary = build_cnpq_sync_summary(results, invalid_groups)
    logger.info(
        f"Flow finished. Successfully synchronized {success_count}/{len(groups)} groups."
    )
    return summary


if __name__ == "__main__":
    sync_cnpq_groups_flow()
