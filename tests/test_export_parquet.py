"""Spec 020 (FR-017): the Parquet mirror keeps horizon ids as text."""

import json

import pandas as pd
from pandas.api.types import is_integer_dtype

from src.scripts.export_parquet import convert_dir


def test_horizon_files_convert_with_text_ids(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    ids = [
        {
            "entity_type": "person",
            "id": 7,
            "horizon_id": "person:lattes:9860697624155451",
            "rule": "lattes_id",
            "natural_key": None,
            "parent_horizon_id": None,
        },
        {
            "entity_type": "award",
            "id": 8,
            "horizon_id": "person:lattes:9860697624155451/award:h:0a1b2c3d4e5f",
            "rule": "parent+title+year",
            "natural_key": "premio|2020",
            "parent_horizon_id": "person:lattes:9860697624155451",
        },
    ]
    aliases = [
        {
            "alias_horizon_id": "person:h:3f9a0c1b2d4e",
            "horizon_id": None,
            "reason": "retired",
            "created_at": "2026-10-27T00:00:00Z",
        }
    ]
    (src / "horizon_ids_canonical.json").write_text(
        json.dumps({"rule_version": 1, "generated_at": "t", "ids": ids})
    )
    (src / "horizon_id_aliases_canonical.json").write_text(
        json.dumps({"rule_version": 1, "generated_at": "t", "aliases": aliases})
    )

    stats = convert_dir(str(src), str(dst))

    assert stats == {"table": 2, "graph": 0, "json": 0, "error": 0}
    table = pd.read_parquet(dst / "horizon_ids_canonical.parquet")
    # numeric ids are still integers (spec 038: whole numbers are written as
    # 64-bit integers by the column rule, so pandas reads them as int64)
    assert is_integer_dtype(table["id"])
    assert table["horizon_id"].tolist() == [r["horizon_id"] for r in ids]
    assert not is_integer_dtype(table["parent_horizon_id"])
    alias_table = pd.read_parquet(dst / "horizon_id_aliases_canonical.parquet")
    # An all-null horizon_id column must not become an integer column.
    assert not is_integer_dtype(alias_table["horizon_id"])
    assert alias_table["alias_horizon_id"].tolist() == ["person:h:3f9a0c1b2d4e"]
    meta = json.loads((dst / "horizon_ids_canonical.meta.json").read_text())
    assert meta == {"rule_version": 1, "generated_at": "t"}


def test_a_mixed_column_converts_and_a_bad_file_is_counted(tmp_path):
    # Spec 038: the manual command uses the archive's column rule, converts
    # every file it can, and counts the one it cannot.
    from src.core.logic.parquet_layout import equal_to_json

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    rows = [{"value_json": "t"}, {"value_json": 3}, {"value_json": [1]}]
    (src / "attribute_assertions_canonical.json").write_text(json.dumps(rows))
    (src / "broken.json").write_text("[{")

    stats = convert_dir(str(src), str(dst))

    assert stats == {"table": 1, "graph": 0, "json": 0, "error": 1}
    import pyarrow.parquet as pq

    back = pq.read_table(dst / "attribute_assertions_canonical.parquet").to_pylist()
    cols = json.loads((dst / "attribute_assertions_canonical.cols.json").read_text())
    assert cols == {"json_columns": ["value_json"]}
    revived = [{"value_json": json.loads(r["value_json"])} for r in back]
    assert equal_to_json(revived, rows)
    assert not (dst / "broken.parquet").exists()


def test_main_exits_1_and_names_the_failed_file(tmp_path, monkeypatch):
    import sys

    from loguru import logger

    from src.scripts import export_parquet

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / "ok.json").write_text(json.dumps([{"a": 1}]))
    (src / "broken.json").write_text("[{")
    monkeypatch.setattr(
        sys, "argv", ["export_parquet", "--src", str(src), "--dst", str(dst)]
    )
    messages = []
    sink = logger.add(lambda m: messages.append(str(m)))
    try:
        try:
            export_parquet.main()
            code = 0
        except SystemExit as exc:
            code = exc.code
    finally:
        logger.remove(sink)

    assert code == 1
    assert any("broken.json" in m for m in messages)
    assert (dst / "ok.parquet").exists()
