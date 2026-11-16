from src.core.logic.initiative_identity import build_identity_key
from src.core.logic.strategies.sigpesq_projects import SigPesqProjectMappingStrategy


def test_sigpesq_project_mapping_uses_project_id_as_sigpesq_identity_code():
    strategy = SigPesqProjectMappingStrategy()

    mapped = strategy.map_row(
        {
            "Id": "PJ      8748",
            "Titulo": "Desenvolvimento de um Modulo de Hidroponia Autonomo",
            "ParecerDiretoria": "Aprovado",
            "Inicio": "01-08-26",
            "Coordenador": "Docente Coordenador",
        }
    )

    assert mapped["identity_key"] == build_identity_key(["sigpesq_project", "8748"])
    assert mapped["metadata"]["sigpesq_project_code"] == "8748"


# --- Spec 036: the order of the name lists is not a change ---


def _row(**changes):
    row = {
        "Id": "PJ 8748",
        "Titulo": "Módulo de Hidroponia",
        "Pesquisadores": "Ana Lima; Bruno Costa; Carla Dias",
        "Estudantes": "Davi Rocha; Eva Melo",
        "ParecerDiretoria": "Aprovado",
    }
    row.update(changes)
    return row


def _hash(row):
    from src.tracking.recorder import stable_hash

    return stable_hash(SigPesqProjectMappingStrategy().change_content(row))


def test_reordered_name_lists_are_the_same_content():
    assert _hash(_row(Estudantes="Eva Melo; Davi Rocha")) == _hash(_row())
    assert _hash(_row(Pesquisadores="Carla Dias; Ana Lima; Bruno Costa")) == _hash(
        _row()
    )
    assert _hash(_row(Estudantes=" Eva Melo ;Davi Rocha ; ")) == _hash(_row())


def test_a_name_added_or_removed_or_another_column_is_a_change():
    assert _hash(_row(Estudantes="Davi Rocha; Eva Melo; Fabio Reis")) != _hash(_row())
    assert _hash(_row(Estudantes="Davi Rocha")) != _hash(_row())
    assert _hash(_row(Pesquisadores="Ana Lima; Bruno Costa")) != _hash(_row())
    assert _hash(_row(Titulo="Outro título")) != _hash(_row())


def test_change_content_gives_lists_and_keeps_the_row():
    strategy = SigPesqProjectMappingStrategy()
    row = _row(Estudantes=float("nan"))
    del row["Pesquisadores"]
    before = dict(row)

    content = strategy.change_content(row)

    assert content["Estudantes"] == []
    assert content["Pesquisadores"] == []
    assert content["Titulo"] == "Módulo de Hidroponia"
    assert set(row) == set(before) and row["Id"] == before["Id"]
    assert "Pesquisadores" not in row
