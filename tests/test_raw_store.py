"""Spec 023: the Lattes download manifest and the stored CNPq pages."""

import json
import os

from src.adapters.sources.raw_store import FileCnpqPageStore, JsonDownloadManifest

A, B, C = "0059221043399777", "0061058205075393", "0064380963494664"


def _cache(tmp_path, *ids):
    cache = tmp_path / "cache"
    cache.mkdir()
    for i in ids:
        (cache / i).write_text("<html/>")
    (cache / "not-an-id.txt").write_text("x")
    return cache


def test_manifest_round_trip_and_undated_cache_files(tmp_path):
    cache = _cache(tmp_path, A, B)
    path = tmp_path / "raw" / "lattes" / "download_manifest.json"
    manifest = JsonDownloadManifest(str(path), str(cache))
    assert manifest.dates() == {A: None, B: None}
    manifest.record(A, "2026-11-05T02:00:00Z")
    manifest.record(C, "2026-11-05T02:00:01Z")  # not cached: kept, not listed
    manifest.save()
    again = JsonDownloadManifest(str(path), str(cache))
    assert again.dates() == {A: "2026-11-05T02:00:00Z", B: None}
    assert json.loads(path.read_text())["version"] == 1
    assert [p for p in os.listdir(path.parent) if p.startswith(".tmp-")] == []


def test_unreadable_manifest_makes_every_curriculum_undated(tmp_path):
    cache = _cache(tmp_path, A)
    path = tmp_path / "manifest.json"
    path.write_text("{not json")
    assert JsonDownloadManifest(str(path), str(cache)).dates() == {A: None}


def test_page_store(tmp_path):
    store = FileCnpqPageStore(str(tmp_path / "cnpq"))
    assert store.stored() == {} and store.load(A) is None
    store.save(
        A,
        f"http://dgp.cnpq.br/dgp/espelhogrupo/{A}",
        {"nome": "G"},
        "2026-11-05T02:00:00Z",
    )
    assert store.stored() == {A: "2026-11-05T02:00:00Z"}
    assert store.load(A)["page"] == {"nome": "G"}
    # Invalid and empty pages count as not stored.
    (tmp_path / "cnpq" / f"{B}.json").write_text("{broken")
    (tmp_path / "cnpq" / f"{C}.json").write_text(json.dumps({"page": {}}))
    assert store.stored() == {A: "2026-11-05T02:00:00Z"}
    assert store.load(B) is None and store.load(C) is None
    assert [p for p in os.listdir(tmp_path / "cnpq") if p.startswith(".tmp-")] == []
