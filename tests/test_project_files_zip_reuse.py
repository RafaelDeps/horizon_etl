"""The extraction step reuses documents from the latest export archive.

For a project with no local JSON, ``extract_json`` restores
``project_sigpesq_files_json/<stem>.json`` from the previous run's
``exports_canonical.zip`` (living next to the corpus) instead of paying for a
new extraction. Rules R11-R15 of contracts/export_zip_rules.md:
local-exists wins, hit reuses with zero extractor calls, exact stem matching,
``force`` bypasses reuse, and any doubt falls back to normal extraction.
"""

import json
import os
import zipfile

import pytest
from agent_sigpesq.extraction import Projeto

from src.adapters.sources.sigpesq.project_files import SigPesqProjectFilesAdapter


class FakeExtractor:
    """Counts constructions and calls; returns a minimal valid Projeto."""

    constructed = 0
    calls = []

    def __init__(self):
        type(self).constructed += 1

    def extract_project(self, pdf_path: str) -> Projeto:
        stem = os.path.splitext(os.path.basename(pdf_path))[0]
        type(self).calls.append(stem)
        return Projeto.model_validate(
            {
                "codigo": stem.replace("_", " "),
                "titulo": f"extracted {stem}",
                "_meta": {"arquivo": f"{stem}.pdf"},
            }
        )


@pytest.fixture(autouse=True)
def reset_fake():
    FakeExtractor.constructed = 0
    FakeExtractor.calls = []
    yield


@pytest.fixture
def extractor_cls(monkeypatch):
    monkeypatch.setattr("agent_sigpesq.extraction.ProjectExtractor", FakeExtractor)
    return FakeExtractor


def make_adapter(tmp_path):
    return SigPesqProjectFilesAdapter(
        pdf_root=str(tmp_path / "pdfs"),
        json_dir=str(tmp_path / "exports" / "project_sigpesq_files_json"),
    )


@pytest.fixture
def adapter(tmp_path):
    return make_adapter(tmp_path)


def make_pdf(adapter, stem):
    os.makedirs(adapter.pdf_dir, exist_ok=True)
    path = os.path.join(adapter.pdf_dir, f"{stem}.pdf")
    open(path, "wb").write(b"%PDF-1.4 fake")
    return path


def make_archive(adapter, entries, *, corrupt=False):
    """Writes exports_canonical.zip next to the corpus (R13 location)."""
    archive_path = os.path.join(
        os.path.dirname(adapter.json_dir), "exports_canonical.zip"
    )
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    if corrupt:
        open(archive_path, "wb").write(b"not a zip at all")
        return archive_path
    with zipfile.ZipFile(archive_path, "w") as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return archive_path


def test_local_json_wins_without_archive(adapter, extractor_cls):
    """R11: an existing local JSON is skipped; the archive is not needed."""
    make_pdf(adapter, "PJ_9760")
    os.makedirs(adapter.json_dir, exist_ok=True)
    open(os.path.join(adapter.json_dir, "PJ_9760.json"), "w").write("{}")

    stats = adapter.extract_json()

    assert stats["skipped"] == 1
    assert stats["reused"] == 0
    assert stats["extracted"] == 0
    assert extractor_cls.constructed == 0, "no extractor needed at all"


def test_archive_hit_reuses_without_extractor_call(adapter, extractor_cls):
    """R12: archived copy is restored; zero paid calls; reused counted."""
    make_pdf(adapter, "PJ_9760")
    archived = {
        "codigo": "PJ 9760",
        "titulo": "archived",
        "_meta": {"arquivo": "PJ_9760.pdf"},
    }
    make_archive(
        adapter,
        {"project_sigpesq_files_json/PJ_9760.json": json.dumps(archived)},
    )

    stats = adapter.extract_json()

    assert stats["reused"] == 1
    assert stats["extracted"] == 0
    assert stats["errors"] == 0
    assert extractor_cls.constructed == 0, "reuse must not build an extractor"
    assert extractor_cls.calls == []

    out_path = os.path.join(adapter.json_dir, "PJ_9760.json")
    with open(out_path, encoding="utf-8") as fh:
        restored = json.load(fh)
    assert restored == archived, "archived content is restored verbatim"
    with open(out_path, encoding="utf-8") as fh:
        assert fh.readlines()[1].startswith("  "), "standard indent=2 formatting"


def test_archive_miss_falls_back_to_extraction(adapter, extractor_cls):
    """R15: no entry for the stem -> normal extraction."""
    make_pdf(adapter, "PJ_9760")
    make_archive(adapter, {"project_sigpesq_files_json/PJ_9999.json": "{}"})

    stats = adapter.extract_json()

    assert stats["reused"] == 0
    assert stats["extracted"] == 1
    assert extractor_cls.calls == ["PJ_9760"]


def test_malformed_entry_falls_back_to_extraction(adapter, extractor_cls):
    """R15: an unusable archived copy is not trusted."""
    make_pdf(adapter, "PJ_9760")
    make_archive(adapter, {"project_sigpesq_files_json/PJ_9760.json": "{bad json"})

    stats = adapter.extract_json()

    assert stats["reused"] == 0
    assert stats["extracted"] == 1
    assert extractor_cls.calls == ["PJ_9760"]


def test_corrupt_archive_falls_back_to_extraction(adapter, extractor_cls):
    """R15: an unreadable archive must not crash the run."""
    make_pdf(adapter, "PJ_9760")
    make_archive(adapter, {}, corrupt=True)

    stats = adapter.extract_json()

    assert stats["reused"] == 0
    assert stats["extracted"] == 1
    assert extractor_cls.calls == ["PJ_9760"]


def test_missing_archive_falls_back_to_extraction(adapter, extractor_cls):
    """R15: no archive at all behaves exactly as before."""
    make_pdf(adapter, "PJ_9760")

    stats = adapter.extract_json()

    assert "reused" in stats
    assert stats["reused"] == 0
    assert stats["extracted"] == 1


def test_force_bypasses_reuse(adapter, extractor_cls):
    """R14: force=True extracts every project even when archived copies exist."""
    make_pdf(adapter, "PJ_9760")
    archived = {"codigo": "PJ 9760", "_meta": {"arquivo": "PJ_9760.pdf"}}
    make_archive(
        adapter,
        {"project_sigpesq_files_json/PJ_9760.json": json.dumps(archived)},
    )

    stats = adapter.extract_json(force=True)

    assert stats["reused"] == 0
    assert stats["extracted"] == 1
    assert extractor_cls.calls == ["PJ_9760"]


def test_mixed_batch_reuses_and_extracts(adapter, extractor_cls):
    """One run: reuse what the archive has, pay only for what is new."""
    make_pdf(adapter, "PJ_9760")
    make_pdf(adapter, "PJ_9761")
    make_pdf(adapter, "PJ_9762")
    archived = {"codigo": "PJ 9760", "_meta": {"arquivo": "PJ_9760.pdf"}}
    make_archive(
        adapter,
        {
            "project_sigpesq_files_json/PJ_9760.json": json.dumps(archived),
            "project_sigpesq_files_json/PJ_9761.json": json.dumps(archived),
        },
    )

    stats = adapter.extract_json()

    assert stats["reused"] == 2
    assert stats["extracted"] == 1
    assert extractor_cls.calls == ["PJ_9762"]


def test_local_json_wins_over_archive(adapter, extractor_cls):
    """R11 + R13 together: an existing local JSON is never re-extracted nor
    re-copied from the archive in the same batch."""
    make_pdf(adapter, "PJ_9760")
    os.makedirs(adapter.json_dir, exist_ok=True)
    local = {"titulo": "local version"}
    open(os.path.join(adapter.json_dir, "PJ_9760.json"), "w").write(json.dumps(local))
    make_archive(
        adapter,
        {
            "project_sigpesq_files_json/PJ_9760.json": json.dumps(
                {"titulo": "archived version"}
            )
        },
    )

    stats = adapter.extract_json()

    assert stats["skipped"] == 1
    assert stats["reused"] == 0
    with open(os.path.join(adapter.json_dir, "PJ_9760.json"), encoding="utf-8") as fh:
        assert json.load(fh) == local, "local file is untouched"
