"""
Convert the JSON canonical exports into a Parquet layout for storage/consumption.

Layout produced in the destination directory:

* array-of-objects file  ->  ``<name>.parquet`` (+ ``<name>.cols.json`` sidecar).
* node-link graph file    ->  ``<name>.nodes.parquet`` + ``<name>.edges.parquet``
  (+ their ``.cols.json`` sidecars) + ``<name>.meta.json``.
* other small object (marts, summaries, ``_meta``)  ->  copied as ``<name>.json``.

Nested (object/list) fields are stored as JSON strings; the reader revives them.
The ``<name>.cols.json`` sidecar (``{"json_columns": [...]}``) tells the reader
EXACTLY which columns were JSON-encoded, so it never has to guess (see the
dashboard's parquet plugin). Id-like columns are pinned to a nullable integer
dtype so they don't round-trip as floats (e.g. ``4737.0``).

Round-trips losslessly for the homogeneous canonical/graph tables. Usage::

    python -m src.scripts.export_parquet --src data/exports --dst data/exports_parquet
"""

import argparse
import glob
import json
import os
import shutil

import pandas as pd
from loguru import logger

COMPRESSION = "zstd"
NESTED_TYPES = (dict, list)


# Spec 020: object-wrapped tables (file -> key of the row list) converted like
# the canonical arrays; the other keys go to ``<name>.meta.json``.
WRAPPED_TABLES = {
    "horizon_ids_canonical.json": "ids",
    "horizon_id_aliases_canonical.json": "aliases",
}


def _is_id_column(name: str) -> bool:
    # Horizon ids are text (``person:lattes:...``), never an integer column,
    # even when a column is all nulls (FR-017).
    if name.endswith("horizon_id"):
        return False
    return name == "id" or name.endswith("_id")


def _first_non_null(series: pd.Series):
    non_null = series.dropna()
    return non_null.iloc[0] if len(non_null) else None


def _encode_columns(df: pd.DataFrame) -> list:
    """Stringifies nested columns (in place) and pins id-like columns to a nullable
    integer dtype. Returns the list of columns that were JSON-encoded."""
    json_columns = []
    for col in df.columns:
        sample = _first_non_null(df[col])
        if isinstance(sample, NESTED_TYPES):
            df[col] = [
                json.dumps(v, ensure_ascii=False) if isinstance(v, NESTED_TYPES) else v
                for v in df[col]
            ]
            json_columns.append(col)
        elif _is_id_column(col):
            try:
                df[col] = pd.to_numeric(df[col]).astype("Int64")
            except (ValueError, TypeError):
                pass  # non-numeric id (already a string) — leave as is
    return json_columns


def _write_table(rows: list, path: str) -> None:
    df = pd.json_normalize(rows, max_level=0)
    json_columns = _encode_columns(df)
    df.to_parquet(path, compression=COMPRESSION, index=False)
    sidecar = path[: -len(".parquet")] + ".cols.json"
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump({"json_columns": json_columns}, fh, ensure_ascii=False)


def _is_graph(data) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("graph"), dict)
        and "nodes" in data["graph"]
        and "edges" in data["graph"]
    )


def convert_file(path: str, dst_dir: str) -> str:
    name = os.path.basename(path)
    stem = name[:-5] if name.endswith(".json") else name
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, list) and data and isinstance(data[0], dict):
        _write_table(data, os.path.join(dst_dir, f"{stem}.parquet"))
        return "table"

    rows_key = WRAPPED_TABLES.get(name)
    if rows_key and isinstance(data, dict) and data.get(rows_key):
        _write_table(data[rows_key], os.path.join(dst_dir, f"{stem}.parquet"))
        meta = {k: v for k, v in data.items() if k != rows_key}
        with open(
            os.path.join(dst_dir, f"{stem}.meta.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(meta, fh, ensure_ascii=False)
        return "table"

    if _is_graph(data):
        graph = data["graph"]
        _write_table(graph["nodes"], os.path.join(dst_dir, f"{stem}.nodes.parquet"))
        _write_table(graph["edges"], os.path.join(dst_dir, f"{stem}.edges.parquet"))
        meta = {
            "metadata": data.get("metadata"),
            "graph_stats": data.get("graph_stats"),
            "graph": {
                "directed": graph.get("directed"),
                "multigraph": graph.get("multigraph"),
                "graph": graph.get("graph"),
            },
        }
        with open(
            os.path.join(dst_dir, f"{stem}.meta.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(meta, fh, ensure_ascii=False)
        return "graph"

    # small nested object (mart/summary/_meta): keep as JSON
    shutil.copy2(path, os.path.join(dst_dir, name))
    return "json"


def convert_dir(src: str, dst: str) -> dict:
    os.makedirs(dst, exist_ok=True)
    stats = {"table": 0, "graph": 0, "json": 0, "error": 0}
    for path in sorted(glob.glob(os.path.join(src, "*.json"))):
        try:
            stats[convert_file(path, dst)] += 1
        except Exception as exc:  # keep going; report at the end
            logger.warning("Failed converting {}: {}", os.path.basename(path), exc)
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


if __name__ == "__main__":
    main()
