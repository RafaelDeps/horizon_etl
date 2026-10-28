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
    assert table["id"].dtype == "Int64"  # numeric ids are still pinned
    assert table["horizon_id"].tolist() == [r["horizon_id"] for r in ids]
    assert not is_integer_dtype(table["parent_horizon_id"])
    alias_table = pd.read_parquet(dst / "horizon_id_aliases_canonical.parquet")
    # An all-null horizon_id column must not become an integer column.
    assert not is_integer_dtype(alias_table["horizon_id"])
    assert alias_table["alias_horizon_id"].tolist() == ["person:h:3f9a0c1b2d4e"]
    meta = json.loads((dst / "horizon_ids_canonical.meta.json").read_text())
    assert meta == {"rule_version": 1, "generated_at": "t"}
