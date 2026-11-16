"""
Convert the JSON canonical exports into the Parquet layout, as loose files.

Manual utility. The weekly publishes the same layout as ``exports_parquet.zip``
(spec 038, ``src/flows/exports/parquet_archive.py``); both use the layout and
the column rule of ``src/core/logic/parquet_layout.py``:

* array-of-objects file  ->  ``<name>.parquet`` (+ ``<name>.cols.json`` sidecar).
* wrapped table          ->  ``<name>.parquet`` + ``<name>.cols.json``
  + ``<name>.meta.json``.
* node-link graph file   ->  ``<name>.nodes.parquet`` + ``<name>.edges.parquet``
  (+ their ``.cols.json`` sidecars) + ``<name>.meta.json``.
* other object (marts, summaries, ``_meta``)  ->  copied as ``<name>.json``.

Every file it can convert is written; a file that cannot be converted is
logged by name and makes the command exit 1. Usage::

    python -m src.scripts.export_parquet --src data/exports --dst data/exports_parquet
"""

import argparse
import glob
import os
import sys

from loguru import logger

from src.core.logic.parquet_layout import WRAPPED_TABLES, layout_members

__all__ = ["WRAPPED_TABLES", "convert_dir", "convert_file", "main"]


def convert_file(path: str, dst_dir: str) -> str:
    """Writes the layout of one JSON file; returns table, graph or json."""
    name = os.path.basename(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    members = layout_members(name, raw)
    for member, data in members:
        with open(os.path.join(dst_dir, member), "wb") as fh:
            fh.write(data)
    names = {member for member, _ in members}
    if any(n.endswith(".nodes.parquet") for n in names):
        return "graph"
    if any(n.endswith(".parquet") for n in names):
        return "table"
    return "json"


def convert_dir(src: str, dst: str) -> dict:
    os.makedirs(dst, exist_ok=True)
    stats = {"table": 0, "graph": 0, "json": 0, "error": 0}
    for path in sorted(glob.glob(os.path.join(src, "*.json"))):
        try:
            stats[convert_file(path, dst)] += 1
        except Exception as exc:  # keep going; report at the end
            logger.error("Failed converting {}: {}", os.path.basename(path), exc)
            stats["error"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert JSON exports to Parquet layout."
    )
    parser.add_argument("--src", default="data/exports")
    parser.add_argument("--dst", default="data/exports_parquet")
    args = parser.parse_args()
    stats = convert_dir(args.src, args.dst)
    logger.info("Parquet conversion complete: {} -> {}", stats, args.dst)
    if stats["error"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
