import os
import time

from loguru import logger


def lattes_id_from_path(file_path: str) -> str:
    """CV files are named ``<n>_<Name>_<lattes id>.json``; keep only the id."""
    return os.path.basename(file_path).replace(".json", "").split("_")[-1]


def log_cv_duration(
    phase: str, position: int, total: int, file_path: str, started: float
) -> None:
    """One INFO line per CV (spec 015, FR-014).

    INFO, not DEBUG: dgp_cnpq_lib resets loguru to INFO when app.py imports it,
    so DEBUG lines never reach the weekly log. The CV is identified by its
    Lattes id, never by the file name, which embeds the person's name.
    """
    logger.info(
        f"Lattes {phase} CV {position}/{total} "
        f"lattes_id={lattes_id_from_path(file_path)} "
        f"took {time.perf_counter() - started:.1f}s"
    )
