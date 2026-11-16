"""Spec 038: the Parquet layout of one export (column rule, members, read back)."""

import io
import json
import zipfile

import pyarrow.parquet as pq
import pytest

from src.core.logic.parquet_layout import (
    ParquetLayoutError,
    encode_table,
    equal_to_json,
    layout_members,
    read_member_back,
)


def _table(rows):
    data, json_columns = encode_table(rows)
    return pq.read_table(io.BytesIO(data)), json_columns


def _archive(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _round_trip(json_name, value):
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return read_member_back(_archive(layout_members(json_name, raw)), json_name)


@pytest.mark.parametrize(
    "values, arrow_type, listed",
    [
        # mixed text + integer + list + object (value_json of attribute assertions)
        (["a", 3, [1, 2], {"k": "v"}, None], "string", True),
        ([[1], {"a": 1}, None], "string", True),
        ([1, 2, None, 2**60], "int64", False),
        ([1.5, 2, None], "double", False),
        (["x", None, "y"], "string", False),
        ([True, None, False], "bool", False),
        ([None, None], "null", False),
        (["text", 7], "string", True),
        ([True, 1], "string", True),
    ],
)
def test_column_rule(values, arrow_type, listed):
    rows = [{"c": v} for v in values]
    table, json_columns = _table(rows)
    assert str(table.schema.field("c").type) == arrow_type
    assert ("c" in json_columns) is listed
    back = _round_trip("t.json", rows)
    assert equal_to_json(back, rows)
    for got, want in zip([r["c"] for r in back], values):
        assert got == want
        assert type(got) is type(want) or (
            isinstance(want, int) and isinstance(got, float)
        )


def test_text_that_looks_like_json_stays_text_in_a_json_column():
    rows = [{"c": "123"}, {"c": "[1]"}, {"c": [1]}]
    back = _round_trip("t.json", rows)
    assert [r["c"] for r in back] == ["123", "[1]", [1]]


def test_columns_in_first_seen_order_and_missing_key_is_empty():
    rows = [{"b": 1}, {"a": "x", "b": 2}, {"c": True}]
    table, _ = _table(rows)
    assert table.column_names == ["b", "a", "c"]
    back = _round_trip("t.json", rows)
    assert back[0] == {"b": 1, "a": None, "c": None}
    assert equal_to_json(back, rows)


GRAPH = {
    "metadata": {"name": "g"},
    "graph_stats": {"nodes": 2},
    "graph": {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": "a", "kind": "p"}, {"id": "b", "kind": "p"}],
        "edges": [{"source": "a", "target": "b", "relation_types": ["x"]}],
    },
}


@pytest.mark.parametrize(
    "json_name, value, expected",
    [
        ("rows.json", [{"id": 1}], ["rows.cols.json", "rows.parquet"]),
        ("empty.json", [], ["empty.cols.json", "empty.parquet"]),
        (
            "g_graph.json",
            GRAPH,
            [
                "g_graph.edges.cols.json",
                "g_graph.edges.parquet",
                "g_graph.meta.json",
                "g_graph.nodes.cols.json",
                "g_graph.nodes.parquet",
            ],
        ),
        (
            "horizon_ids_canonical.json",
            {"rule_version": 6, "generated_at": "t", "ids": [{"id": 1}]},
            [
                "horizon_ids_canonical.cols.json",
                "horizon_ids_canonical.meta.json",
                "horizon_ids_canonical.parquet",
            ],
        ),
        (
            "horizon_id_aliases_canonical.json",
            {"rule_version": 6, "generated_at": "t", "aliases": []},
            [
                "horizon_id_aliases_canonical.cols.json",
                "horizon_id_aliases_canonical.meta.json",
                "horizon_id_aliases_canonical.parquet",
            ],
        ),
        (
            "source_document_states_canonical.json",
            {"rule_version": 6, "generated_at": "t", "documents": [{"k": "x"}]},
            [
                "source_document_states_canonical.cols.json",
                "source_document_states_canonical.meta.json",
                "source_document_states_canonical.parquet",
            ],
        ),
        ("mart.json", {"a": [1, 2], "b": {"c": 1}}, ["mart.json"]),
    ],
)
def test_layout_members_and_read_back(json_name, value, expected):
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    members = layout_members(json_name, raw)
    assert sorted(name for name, _ in members) == expected
    back = read_member_back(_archive(members), json_name)
    assert equal_to_json(back, value)


def test_plain_object_is_copied_byte_for_byte():
    raw = b'{\n  "b": 1,\n  "a": "\xc3\xa9"\n}'
    assert layout_members("mart.json", raw) == [("mart.json", raw)]


def test_meta_files():
    raw = json.dumps(GRAPH).encode()
    members = dict(layout_members("g.json", raw))
    assert json.loads(members["g.meta.json"]) == {
        "metadata": {"name": "g"},
        "graph_stats": {"nodes": 2},
        "graph": {"directed": False, "multigraph": False, "graph": {}},
    }
    assert json.loads(members["g.edges.cols.json"]) == {
        "json_columns": ["relation_types"]
    }
    wrapped = {"rule_version": 6, "generated_at": "t", "ids": [{"id": 1}]}
    members = dict(
        layout_members("horizon_ids_canonical.json", json.dumps(wrapped).encode())
    )
    assert json.loads(members["horizon_ids_canonical.meta.json"]) == {
        "rule_version": 6,
        "generated_at": "t",
    }


def test_equal_to_json_rejects_differences():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    back = _round_trip("t.json", rows)
    assert equal_to_json(back, rows)
    assert not equal_to_json(back, [{"a": 1, "b": "x"}, {"a": 2, "b": "z"}])
    assert not equal_to_json(back, rows[:1])
    assert not equal_to_json(back, list(reversed(rows)))
    assert not equal_to_json(back, [{"a": 1, "b": "x"}, {"a": 2, "b": "y", "c": 1}])


def test_same_input_gives_same_bytes():
    rows = [{"id": i, "v": ["x", i] if i % 2 else "t", "f": i / 3} for i in range(50)]
    raw = json.dumps(rows).encode()
    assert layout_members("t.json", raw) == layout_members("t.json", raw)


def test_unwritable_value_names_the_member():
    with pytest.raises(ParquetLayoutError, match="broken.json"):
        layout_members("broken.json", b"[{")
