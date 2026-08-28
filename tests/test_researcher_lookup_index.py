"""Índice leve de correspondência de pesquisadores (feature 007).

O objetivo da feature é desempenho **sem** mudança de comportamento, então os
testes que importam aqui são os de equivalência: a escolha feita sobre um
registro leve tem de ser a mesma feita sobre a entidade completa.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.core.logic.researcher_resolution import (
    ResearcherRef,
    load_researcher_index,
    resolve_or_create_researcher,
    resolve_researcher_by_name,
    resolve_researcher_from_lattes,
    sync_researcher_ref,
)


@pytest.fixture
def session():
    """Banco em memória com as duas tabelas que o índice lê."""
    engine = create_engine("sqlite://")
    with Session(engine) as sess:
        sess.execute(
            text(
                "CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, "
                "identification_id TEXT, birthday DATE)"
            )
        )
        sess.execute(
            text(
                "CREATE TABLE researchers (id INTEGER PRIMARY KEY, cnpq_url TEXT, "
                "google_scholar_url TEXT, resume TEXT, citation_names TEXT)"
            )
        )
        sess.commit()
        yield sess


def _insert(
    session,
    id_,
    name,
    cnpq_url=None,
    resume=None,
    citation_names=None,
    identification_id=None,
):
    session.execute(
        text(
            "INSERT INTO persons (id, name, identification_id) "
            "VALUES (:id, :name, :ident)"
        ),
        {"id": id_, "name": name, "ident": identification_id},
    )
    session.execute(
        text(
            "INSERT INTO researchers (id, cnpq_url, resume, citation_names) "
            "VALUES (:id, :url, :resume, :cit)"
        ),
        {"id": id_, "url": cnpq_url, "resume": resume, "cit": citation_names},
    )
    session.commit()


# --------------------------------------------------------------------------
# T006 — carregamento
# --------------------------------------------------------------------------


def test_index_carrega_um_registro_por_pesquisador(session):
    _insert(session, 1, "Ana Souza", cnpq_url="http://lattes.cnpq.br/111")
    _insert(session, 2, "Bruno Lima", resume="pesquisador", citation_names="LIMA, B.")

    index = load_researcher_index(session)

    assert len(index) == 2
    ana = next(r for r in index if r.id == 1)
    assert ana.name == "Ana Souza"
    assert ana.cnpq_url == "http://lattes.cnpq.br/111"
    bruno = next(r for r in index if r.id == 2)
    assert bruno.resume == "pesquisador"
    assert bruno.citation_names == "LIMA, B."


def test_index_emite_uma_unica_consulta(session):
    for i in range(25):
        _insert(session, i + 1, f"Pesquisador {i}")

    consultas = []
    from sqlalchemy import event

    @event.listens_for(session.get_bind(), "after_cursor_execute")
    def _conta(conn, cursor, statement, *a, **k):
        consultas.append(statement)

    index = load_researcher_index(session)

    assert len(index) == 25
    assert len(consultas) == 1, (
        "O índice existe para trocar N leituras por uma; mais de uma consulta "
        f"aqui significa que a otimização não aconteceu: {consultas}"
    )


# --------------------------------------------------------------------------
# T005 — degradação segura
# --------------------------------------------------------------------------


def test_index_vazio_sem_sessao():
    assert load_researcher_index(None) == []


def test_index_vazio_quando_tabelas_nao_existem():
    engine = create_engine("sqlite://")
    with Session(engine) as sess:
        assert load_researcher_index(sess) == []


# --------------------------------------------------------------------------
# T013 — equivalência: registro leve escolhe o mesmo que a entidade
# --------------------------------------------------------------------------


def _entidades():
    """Candidatos como a entidade ORM aparece para o algoritmo.

    O algoritmo lê tudo por ``getattr``; do ponto de vista dele, uma entidade
    é este conjunto de atributos.
    """
    return [
        SimpleNamespace(
            id=1,
            name="Ana Souza",
            identification_id="hash-abc",
            cnpq_url="http://lattes.cnpq.br/111",
            resume=None,
            citation_names=None,
        ),
        SimpleNamespace(
            id=2,
            name="Ana Souza",
            identification_id=None,
            cnpq_url=None,
            resume="tem currículo textual",
            citation_names="SOUZA, A.",
        ),
        SimpleNamespace(
            id=3,
            name="Bruno Lima",
            identification_id=None,
            cnpq_url=None,
            resume=None,
            citation_names=None,
        ),
    ]


def _refs():
    return [
        ResearcherRef(
            id=e.id,
            name=e.name,
            identification_id=e.identification_id,
            cnpq_url=e.cnpq_url,
            resume=e.resume,
            citation_names=e.citation_names,
        )
        for e in _entidades()
    ]


@pytest.mark.parametrize(
    "lattes_id, json_name",
    [
        ("111", "Ana Souza"),  # casa por cnpq_url
        (None, "Ana Souza"),  # empate de nome, desempate por resume
        (None, "ANA SOUZA"),  # diferença de caixa
        (None, "Bruno Lima"),  # nome único
        ("999", "Inexistente"),  # ninguém casa
    ],
)
def test_equivalencia_registro_leve_versus_entidade(lattes_id, json_name):
    escolha_entidade = resolve_researcher_from_lattes(
        _entidades(), lattes_id=lattes_id, json_name=json_name, session=None
    )
    escolha_registro = resolve_researcher_from_lattes(
        _refs(), lattes_id=lattes_id, json_name=json_name, session=None
    )

    assert getattr(escolha_entidade, "id", None) == getattr(
        escolha_registro, "id", None
    ), "índice e entidade divergiram na escolha do dono do currículo"


def test_equivalencia_com_desempate_por_dados_vinculados(session):
    """O desempate que consulta o banco também precisa valer para os dois."""
    _insert(session, 1, "Ana Souza")
    _insert(session, 2, "Ana Souza")
    session.execute(
        text("CREATE TABLE advisorship_members (person_id INTEGER, role_name TEXT)")
    )
    session.execute(text("CREATE TABLE academic_educations (researcher_id INTEGER)"))
    session.execute(text("CREATE TABLE article_authors (researcher_id INTEGER)"))
    session.execute(text("INSERT INTO article_authors VALUES (2)"))
    session.commit()

    entidades = [
        SimpleNamespace(
            id=1,
            name="Ana Souza",
            identification_id=None,
            cnpq_url=None,
            resume=None,
            citation_names=None,
        ),
        SimpleNamespace(
            id=2,
            name="Ana Souza",
            identification_id=None,
            cnpq_url=None,
            resume=None,
            citation_names=None,
        ),
    ]
    refs = load_researcher_index(session)

    por_entidade = resolve_researcher_from_lattes(
        entidades, lattes_id=None, json_name="Ana Souza", session=session
    )
    por_registro = resolve_researcher_from_lattes(
        refs, lattes_id=None, json_name="Ana Souza", session=session
    )

    assert por_entidade.id == por_registro.id == 2


# --------------------------------------------------------------------------
# T017/T018 — criação durante o laço e compatibilidade retroativa
# --------------------------------------------------------------------------


def test_recem_criado_entra_no_indice_e_e_encontrado_depois():
    index = [ResearcherRef(id=1, name="Ana Souza")]
    ctrl = MagicMock()
    criado = MagicMock()
    criado.id = 42
    criado.name = "Carlos Dias"
    criado.identification_id = None
    criado.cnpq_url = None
    criado.resume = None
    criado.citation_names = None
    ctrl.create_researcher.return_value = criado

    primeiro = resolve_or_create_researcher(ctrl, index, name="Carlos Dias")

    assert primeiro is criado
    assert len(index) == 2
    assert isinstance(index[1], ResearcherRef)
    assert index[1].id == 42

    segundo = resolve_or_create_researcher(ctrl, index, name="Carlos Dias")

    assert getattr(segundo, "id", None) == 42
    assert len(index) == 2, "criou de novo alguém que já estava no índice"
    assert ctrl.create_researcher.call_count == 1


def test_lista_de_entidades_continua_recebendo_entidades():
    """cnpq_sync e sigpesq_excel passam entidades; nada pode mudar para eles."""
    existente = SimpleNamespace(
        id=1,
        name="Ana Souza",
        identification_id=None,
        cnpq_url=None,
        resume=None,
        citation_names=None,
    )
    lista = [existente]
    ctrl = MagicMock()
    criado = MagicMock()
    criado.id = 42
    criado.name = "Carlos Dias"
    ctrl.create_researcher.return_value = criado

    resolve_or_create_researcher(ctrl, lista, name="Carlos Dias")

    assert lista[1] is criado
    assert not isinstance(lista[1], ResearcherRef)


def test_sync_reflete_no_indice_o_que_foi_gravado():
    index = [ResearcherRef(id=7, name="Ana Souza")]
    entidade = SimpleNamespace(
        id=7,
        name="Ana Souza",
        identification_id=None,
        cnpq_url="http://lattes.cnpq.br/777",
        resume="novo resumo",
        citation_names="SOUZA, A.",
    )

    sync_researcher_ref(index, entidade)

    assert index[0].cnpq_url == "http://lattes.cnpq.br/777"
    assert index[0].resume == "novo resumo"
    assert index[0].citation_names == "SOUZA, A."


# --------------------------------------------------------------------------
# T020 — critérios de pontuação vigentes
# --------------------------------------------------------------------------


def test_cnpq_url_vence_correspondencia_por_nome():
    candidatos = [
        ResearcherRef(id=1, name="Ana Souza"),
        ResearcherRef(id=2, name="Outro Nome", cnpq_url="http://lattes.cnpq.br/111"),
    ]

    escolha = resolve_researcher_from_lattes(
        candidatos, lattes_id="111", json_name="Ana Souza", session=None
    )

    assert escolha.id == 2


def test_brand_id_nao_influencia_mais_a_escolha():
    """O ramo removido pontuava 500 num campo que não existe no cadastro.

    Um candidato que exponha ``brand_id`` não pode mais ganhar por causa dele —
    caso contrário a remoção teria mudado comportamento em vez de apenas
    eliminar código que nunca disparava.
    """
    com_brand = SimpleNamespace(
        id=1,
        name="Nome Que Nao Casa",
        identification_id=None,
        brand_id="111",
        cnpq_url=None,
        resume=None,
        citation_names=None,
    )
    por_nome = ResearcherRef(id=2, name="Ana Souza")

    escolha = resolve_researcher_from_lattes(
        [com_brand, por_nome], lattes_id="111", json_name="Ana Souza", session=None
    )

    assert escolha.id == 2


def test_ninguem_casa_devolve_none():
    assert (
        resolve_researcher_from_lattes(
            _refs(), lattes_id="000", json_name="Fulano Inexistente", session=None
        )
        is None
    )


def test_resolve_by_name_delegates_to_shared_participant_key(monkeypatch):
    from src.core.logic import researcher_resolution

    original = researcher_resolution.normalize_participant_name
    calls = []

    def spy(name, canonical_particles=True):
        calls.append(name)
        return original(name, canonical_particles=canonical_particles)

    monkeypatch.setattr(researcher_resolution, "normalize_participant_name", spy)

    index = [ResearcherRef(id=7, name="Israel Magalhães do Carmo")]
    escolha = resolve_researcher_by_name(index, name="ISRAEL MAGALHÃES DO CARMO")

    assert escolha is not None and escolha.id == 7
    assert calls, "resolve_researcher_by_name must compare names through the shared key"
