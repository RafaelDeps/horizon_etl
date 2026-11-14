"""Parquet layout of the canonical exports (spec 038, branch 038).

One JSON export becomes these members of ``exports_parquet.zip``:

* a list of rows       -> ``<name>.parquet`` + ``<name>.cols.json``;
* a wrapped table      -> ``<name>.parquet`` + ``<name>.cols.json``
  + ``<name>.meta.json`` (the other keys of the object);
* a node-link graph    -> ``<name>.nodes.parquet`` + ``<name>.edges.parquet``,
  their ``.cols.json``, and ``<name>.meta.json``;
* any other value      -> ``<name>.json``, the bytes unchanged.

Column rule: a column whose non-empty values are nested (list or object) or
of more than one kind (text, number, boolean) is written as JSON text, every
value encoded (text values too), and named in ``<name>.cols.json`` as
``{"json_columns": [...]}``; a reader decodes exactly those columns and gets
every value back with its original kind. Whole numbers are 64-bit integers,
other numbers floats, text stays text, booleans stay booleans.

The dashboard reader (``parquet-plugin.mjs`` of horizon_dashboard) follows
this layout. Pure: no file or database access besides the archive object
given to :func:`read_member_back`.
"""

import io
import json
import math
from typing import Any, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

COMPRESSION = "zstd"

# Object-wrapped tables (spec 020/021): file -> key of the row list; the other
# keys go to ``<name>.meta.json``.
WRAPPED_TABLES = {
    "horizon_ids_canonical.json": "ids",
    "horizon_id_aliases_canonical.json": "aliases",
    "source_document_states_canonical.json": "documents",
}

_TEXT, _NUMBER, _BOOLEAN, _NESTED = "text", "number", "boolean", "nested"


class ParquetLayoutError(Exception):
    """An export that cannot be written in the Parquet layout."""


def _kind(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return _BOOLEAN
    if isinstance(value, (int, float)):
        return _NUMBER
    if isinstance(value, str):
        return _TEXT
    return _NESTED


def _columns(rows: list) -> list:
    columns: dict = {}
    for row in rows:
        for key in row:
            columns.setdefault(key, None)
    return list(columns)


def encode_table(rows: list) -> Tuple[bytes, List[str]]:
    """Parquet bytes of ``rows`` and the columns written as JSON text."""
    columns = _columns(rows)
    data = {}
    json_columns = []
    for column in columns:
        values = [row.get(column) for row in rows]
        kinds = {_kind(v) for v in values} - {None}
        if _NESTED in kinds or len(kinds) > 1:
            json_columns.append(column)
            array = pa.array(
                [
                    None if v is None else json.dumps(v, ensure_ascii=False)
                    for v in values
                ],
                type=pa.string(),
            )
        elif kinds == {_NUMBER} and all(
            isinstance(v, int) for v in values if v is not None
        ):
            array = pa.array(values, type=pa.int64())
        elif kinds == {_NUMBER}:
            array = pa.array(
                [None if v is None else float(v) for v in values], type=pa.float64()
            )
        elif kinds == {_TEXT}:
            array = pa.array(values, type=pa.string())
        elif kinds == {_BOOLEAN}:
            array = pa.array(values, type=pa.bool_())
        else:
            array = pa.nulls(len(values))
        data[column] = array
    table = pa.table(data) if columns else pa.table({})
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression=COMPRESSION)
    return buffer.getvalue(), json_columns


def _dump(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _table_members(stem: str, rows: list) -> List[Tuple[str, bytes]]:
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("a row is not an object")
    data, json_columns = encode_table(rows)
    return [
        (f"{stem}.parquet", data),
        (f"{stem}.cols.json", _dump({"json_columns": json_columns})),
    ]


def _is_graph(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("graph"), dict)
        and isinstance(value["graph"].get("nodes"), list)
        and isinstance(value["graph"].get("edges"), list)
    )


def layout_members(json_name: str, raw: bytes) -> List[Tuple[str, bytes]]:
    """Members of the Parquet archive for the export ``json_name``."""
    stem = json_name[: -len(".json")] if json_name.endswith(".json") else json_name
    try:
        value = json.loads(raw)
        if isinstance(value, list) and all(isinstance(v, dict) for v in value):
            return _table_members(stem, value)
        rows_key = WRAPPED_TABLES.get(json_name)
        if (
            rows_key
            and isinstance(value, dict)
            and isinstance(value.get(rows_key), list)
        ):
            meta = {k: v for k, v in value.items() if k != rows_key}
            return _table_members(stem, value[rows_key]) + [
                (f"{stem}.meta.json", _dump(meta))
            ]
        if _is_graph(value):
            graph = value["graph"]
            meta = {
                "metadata": value.get("metadata"),
                "graph_stats": value.get("graph_stats"),
                "graph": {
                    "directed": graph.get("directed"),
                    "multigraph": graph.get("multigraph"),
                    "graph": graph.get("graph"),
                },
            }
            return (
                _table_members(f"{stem}.nodes", graph["nodes"])
                + _table_members(f"{stem}.edges", graph["edges"])
                + [(f"{stem}.meta.json", _dump(meta))]
            )
        return [(json_name, raw)]
    except Exception as exc:
        raise ParquetLayoutError(f"{json_name}: {exc}") from exc


def _read_table(archive, stem: str) -> list:
    table = pq.read_table(io.BytesIO(archive.read(f"{stem}.parquet")))
    json_columns = set(json.loads(archive.read(f"{stem}.cols.json"))["json_columns"])
    rows = table.to_pylist()
    if json_columns:
        for row in rows:
            for column in json_columns:
                if row[column] is not None:
                    row[column] = json.loads(row[column])
    return rows


def read_member_back(archive, json_name: str) -> Any:
    """The export ``json_name`` rebuilt from an open Parquet archive."""
    stem = json_name[: -len(".json")] if json_name.endswith(".json") else json_name
    names = set(archive.namelist())
    if json_name in names:
        return json.loads(archive.read(json_name))
    meta_name = f"{stem}.meta.json"
    if f"{stem}.nodes.parquet" in names:
        meta = json.loads(archive.read(meta_name))
        return {
            "metadata": meta.get("metadata"),
            "graph_stats": meta.get("graph_stats"),
            "graph": {
                **(meta.get("graph") or {}),
                "nodes": _read_table(archive, f"{stem}.nodes"),
                "edges": _read_table(archive, f"{stem}.edges"),
            },
        }
    rows = _read_table(archive, stem)
    if meta_name in names:
        return {**json.loads(archive.read(meta_name)), WRAPPED_TABLES[json_name]: rows}
    return rows


def _same(rebuilt: Any, original: Any) -> bool:
    if isinstance(original, dict):
        if not isinstance(rebuilt, dict):
            return False
        keys = set(original) | set(rebuilt)
        return all(_same(rebuilt.get(k), original.get(k)) for k in keys)
    if isinstance(original, list):
        return (
            isinstance(rebuilt, list)
            and len(rebuilt) == len(original)
            and all(_same(a, b) for a, b in zip(rebuilt, original))
        )
    if isinstance(original, float) and isinstance(rebuilt, float):
        return rebuilt == original or (math.isnan(rebuilt) and math.isnan(original))
    if isinstance(original, bool) or isinstance(rebuilt, bool):
        return type(original) is type(rebuilt) and rebuilt == original
    return rebuilt == original


def equal_to_json(rebuilt: Any, original: Any) -> bool:
    """Spec 038 equality: same values in order, a missing key equals an empty
    value, integers compare as integers (and equal to the same float)."""
    return _same(rebuilt, original)


__all__ = [
    "COMPRESSION",
    "WRAPPED_TABLES",
    "ParquetLayoutError",
    "encode_table",
    "equal_to_json",
    "layout_members",
    "read_member_back",
]
