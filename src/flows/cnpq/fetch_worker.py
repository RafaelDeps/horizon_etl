"""Lean CNPq page-fetch task, isolated from the database/ORM/tracking stack.

This module deliberately imports only ``prefect`` and
``src.adapters.sources.cnpq_crawler``. It exists so that a
``ProcessPoolTaskRunner`` worker (which reconstructs a submitted task by
importing its defining module in a freshly spawned interpreter -- see
specs/012-cnpq-concurrent-fetch/research.md R3) never has to import
``research_domain``, ``CnpqSyncLogic``, or ``tracking_recorder`` just to fetch
a page. Keep it that way: nothing outside ``src.adapters.sources.cnpq_crawler``
belongs in this file's import list.
"""

from typing import Any, Dict

from prefect import task

from src.adapters.sources.cnpq_crawler import CnpqCrawlerAdapter


@task(name="fetch_cnpq_group")
def fetch_group(group_info: Dict[str, Any]) -> Dict[str, Any]:
    """Fetches and parses one CNPq group's page. No database access.

    Returns a plain dict (cloudpickle-safe, required by
    ``ProcessPoolTaskRunner``) bundling everything the serial write step
    needs: on success, the raw group ``data``, the merged ``members`` list
    (leaders included, with role "Líder" -- the same merge
    ``sync_single_group`` used to do inline), and ``research_lines``. On
    failure, just enough to report which group failed, matching the shape
    ``sync_single_group`` already returns today for a failed fetch.
    """
    url = group_info["url"]
    group_id = group_info["id"]
    group_name = group_info["name"]

    adapter = CnpqCrawlerAdapter()
    data = adapter.get_group_data(url)
    if not data:
        return {
            "success": False,
            "group_id": group_id,
            "group_name": group_name,
            "url": url,
        }

    members = adapter.extract_members(data)

    leaders = adapter.extract_leaders(data)
    for leader_name in leaders:
        members.append(
            {
                "name": leader_name,
                "role": "Líder",
                "data_inicio": None,
                "data_fim": None,
            }
        )

    research_lines = adapter.extract_research_lines(data)

    return {
        "success": True,
        "group_id": group_id,
        "group_name": group_name,
        "url": url,
        "data": data,
        "members": members,
        "research_lines": research_lines,
    }
