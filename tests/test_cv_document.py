"""Spec 021, US3: a Lattes CV that cannot be read or identified fails before
any transaction is opened, so it can never look like a CV whose items were
all removed (research R4)."""

import json

import pytest

from src.core.ports.document_state_store import DocumentFailed
from src.flows.lattes.cv_document import read_cv

LATTES_ID = "1191009329970047"
GOOD = {"informacoes_pessoais": {"nome_completo": "Maria da Silva"}}


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return str(path)


def _reason(path):
    with pytest.raises(DocumentFailed) as exc:
        read_cv(path)
    return exc.value.reason


def test_a_named_cv_with_its_lattes_id_is_read(tmp_path):
    path = _write(tmp_path, f"12_Maria-da-Silva_{LATTES_ID}.json", GOOD)
    assert read_cv(path) == GOOD


def test_a_file_that_does_not_load_or_is_empty_is_unparsable(tmp_path):
    assert _reason(_write(tmp_path, f"1_A_{LATTES_ID}.json", "{")) == "unparsable"
    assert _reason(_write(tmp_path, f"2_A_{LATTES_ID}.json", "{}")) == "unparsable"


def test_a_placeholder_name_in_the_file_or_the_json_is_unidentified(tmp_path):
    in_file = _write(tmp_path, f"130_Nome-nao-identificado_{LATTES_ID}.json", GOOD)
    assert _reason(in_file) == "unidentified"
    placeholder = {"informacoes_pessoais": {"nome_completo": "[Nome-nao-identificado]"}}
    in_json = _write(tmp_path, f"7_Maria_{LATTES_ID}.json", placeholder)
    assert _reason(in_json) == "unidentified"


def test_a_file_name_without_a_lattes_id_is_unidentified(tmp_path):
    assert _reason(_write(tmp_path, "Maria-da-Silva.json", GOOD)) == "unidentified"
    assert _reason(_write(tmp_path, "3_Maria_12345.json", GOOD)) == "unidentified"
