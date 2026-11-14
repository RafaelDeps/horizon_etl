"""exports_parquet.zip: the Parquet layout of the canonical exports (spec 038).

Built from the top-level members of the ``exports_canonical.zip`` the same run
has just written, so every value already went through the safety net of
spec 029 and the Parquet archive carries nothing the JSON archive does not.
The JSON archive's manifest is copied as it is, so the same publishing gate
applies to both archives. The ETL never reads this archive back.

The archive is written to a temporary file with fixed member dates, in name
order, and replaces the previous one only when complete: the same JSON
archive gives the same bytes, and a failure keeps the previous archive.
"""

import hashlib
import json
import os
import time
import zipfile
from typing import Optional

from loguru import logger
from prefect import flow, task

from src.core.logic.parquet_layout import layout_members
from src.notifications.telegram import telegram_flow_state_handlers

JSON_ARCHIVE_NAME = "exports_canonical.zip"
PARQUET_ARCHIVE_NAME = "exports_parquet.zip"
MANIFEST_NAME = "export_manifest.json"
REPORT_PATH = "data/reports/parquet_archive_report.json"

# The archive is committed to git: same limit as the JSON archive (spec 029),
# for the archive and for every member.
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024

_MEMBER_DATE = (1980, 1, 1, 0, 0, 0)
EARLIER_RUN_WARNING = (
    "exports_parquet.zip is now from an earlier run than exports_canonical.zip"
)


class ParquetArchiveError(Exception):
    """The Parquet archive could not be built."""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_member(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ParquetArchiveError(
            f"member {name} is {len(data)} bytes, over the {MAX_ARCHIVE_BYTES} limit"
        )
    info = zipfile.ZipInfo(name, date_time=_MEMBER_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def _write_report(report: dict, report_path: str) -> None:
    try:
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError as exc:
        logger.warning("Parquet archive report not written: {}", exc)


def build_parquet_archive(output_dir: str, report_path: Optional[str] = None) -> dict:
    """Builds ``exports_parquet.zip`` in ``output_dir`` from the JSON archive
    there; returns the report (status ``built`` or ``failed``). Never raises
    for a failed build: the previous archive is kept and the report says why."""
    report_path = report_path or REPORT_PATH
    json_path = os.path.join(output_dir, JSON_ARCHIVE_NAME)
    parquet_path = os.path.join(output_dir, PARQUET_ARCHIVE_NAME)
    tmp_path = parquet_path + ".tmp"
    started = time.monotonic()
    report = {
        "status": "failed",
        "reason": None,
        "failed_member": None,
        "json_archive_sha256": None,
        "members": 0,
        "archive_bytes": None,
        "largest_member": None,
        "largest_member_bytes": None,
        "seconds": 0.0,
    }
    current = None
    try:
        report["json_archive_sha256"] = _sha256(json_path)
        with zipfile.ZipFile(json_path) as source:
            names = source.namelist()
            if MANIFEST_NAME not in names:
                raise ParquetArchiveError(f"{JSON_ARCHIVE_NAME} has no {MANIFEST_NAME}")
            top_level = sorted(
                n
                for n in names
                if "/" not in n and n.endswith(".json") and n != MANIFEST_NAME
            )
            members = []
            for name in top_level:
                current = name
                members.extend(layout_members(name, source.read(name)))
            current = MANIFEST_NAME
            manifest = source.read(MANIFEST_NAME)
        current = None
        members.sort(key=lambda m: m[0])
        members.append((MANIFEST_NAME, manifest))
        with zipfile.ZipFile(tmp_path, "w") as zf:
            for name, data in members:
                current = name
                _write_member(zf, name, data)
        current = None
        size = os.path.getsize(tmp_path)
        if size > MAX_ARCHIVE_BYTES:
            raise ParquetArchiveError(
                f"the archive is {size} bytes, over the {MAX_ARCHIVE_BYTES} limit"
            )
        os.replace(tmp_path, parquet_path)
        largest = max(members, key=lambda m: len(m[1]))
        report.update(
            status="built",
            members=len(members),
            archive_bytes=size,
            largest_member=largest[0],
            largest_member_bytes=len(largest[1]),
        )
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        report.update(reason=str(exc), failed_member=current)
    report["seconds"] = round(time.monotonic() - started, 2)
    _write_report(report, report_path)
    if report["status"] == "built":
        logger.info(
            "Parquet archive built: {} members, {} bytes, largest {} ({}), {} s",
            report["members"],
            report["archive_bytes"],
            report["largest_member"],
            report["largest_member_bytes"],
            report["seconds"],
        )
    else:
        logger.error(
            "Parquet archive not built (member {}): {}",
            report["failed_member"],
            report["reason"],
        )
        logger.warning(EARLIER_RUN_WARNING)
    return report


@task(name="parquet_archive_task")
def parquet_archive_task(output_dir: str) -> dict:
    return build_parquet_archive(output_dir)


@flow(name="Parquet Archive Flow", **telegram_flow_state_handlers())
def parquet_archive_flow(output_dir: str = "data/exports") -> dict:
    """Builds exports_parquet.zip from exports_canonical.zip (spec 038); fails
    when the build fails, so the weekly records the phase as failed."""
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.getcwd(), output_dir)
    report = parquet_archive_task(output_dir)
    if report["status"] != "built":
        raise ParquetArchiveError(report["reason"])
    return report


if __name__ == "__main__":
    parquet_archive_flow()
