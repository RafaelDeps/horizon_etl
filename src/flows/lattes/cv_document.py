"""A Lattes CV as a source document (spec 021)."""

import json
import os
from typing import List, Optional

from src.core.logic.horizon_identity import lattes_id_from_cv_path
from src.core.ports.document_state_store import DocumentFailed

# The name scriptLattes writes when it could not read the CV (TD-022): such a
# file carries no items, so processing it could only look like a total loss.
UNIDENTIFIED_NAME = "Nome-nao-identificado"


def read_cv(json_file: str) -> dict:
    """The CV's JSON, or ``DocumentFailed``: ``unparsable`` for a file that
    does not load, ``unidentified`` for a CV without a name or a Lattes id.
    Both are failed downloads, never a CV whose items were all removed, and
    both are detected before the document's transaction is opened."""
    name = os.path.basename(json_file)
    if UNIDENTIFIED_NAME in name or not lattes_id_from_cv_path(name):
        raise DocumentFailed("unidentified", name)
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise DocumentFailed("unparsable", f"{json_file}: {e}")
    if not data or not isinstance(data, dict):
        raise DocumentFailed("unparsable", f"{json_file}: empty")
    info = data.get("informacoes_pessoais") or {}
    json_name = data.get("nome") or data.get("name") or info.get("nome_completo")
    if json_name and UNIDENTIFIED_NAME in json_name:
        raise DocumentFailed("unidentified", name)
    return data


LATTES_LIST = os.path.join("data", "lattes_run", "lattes.list")


def listed_lattes_ids(list_path: str = LATTES_LIST) -> Optional[List[str]]:
    """The Lattes ids of ``lattes.list`` (``<id>,<name>`` per line), the
    listing of the Lattes documents (research R8). None when the file is
    missing or empty: the run then cannot tell a removed CV from one that was
    not downloaded, so no status changes."""
    if not os.path.exists(list_path):
        return None
    ids = []
    with open(list_path, "r", encoding="utf-8") as f:
        for line in f:
            lattes_id = line.split(",", 1)[0].strip()
            if lattes_id.isdigit() and len(lattes_id) == 16:
                ids.append(lattes_id)
    return ids or None


def finish_lattes_listing(skip, json_files: List[str]) -> None:
    """After the CVs of a Lattes phase: a listed id with no JSON file is a
    failed download (its stored data is kept), and the listing marks CVs
    gone from ``lattes.list`` as inactive (research R4, R8)."""
    from loguru import logger

    listed = listed_lattes_ids()
    present = {lattes_id_from_cv_path(p) for p in json_files}
    if listed is None:
        logger.warning(
            "{} missing or empty: no Lattes document changes status", LATTES_LIST
        )
        skip.finish(sorted(k for k in present if k), complete=False)
        return
    for lattes_id in listed:
        if lattes_id in present:
            continue
        with skip.document(lattes_id):
            raise DocumentFailed("download", f"no JSON file for {lattes_id}")
    skip.finish(listed, complete=True)


def retry_unidentified(skip, manifest) -> int:
    """Spec 023: a curriculum the portal served as "Nome-nao-identificado" is
    not a good download, even if the download itself succeeded. Dropping its
    date makes it the oldest item of the next rotation, so it is downloaded
    again on the next run instead of in about four weeks. The share still
    bounds how many curricula a run downloads. Returns how many were dropped."""
    keys = sorted(
        {key for key, reason, _d in skip.failures if reason == "unidentified"}
    )
    dates = manifest.dates()
    dropped = [key for key in keys if dates.get(key)]
    for key in dropped:
        manifest.forget(key)
    if dropped:
        manifest.save()
    return len(dropped)
