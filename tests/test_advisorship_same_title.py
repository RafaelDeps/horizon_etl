"""Spec 035: advisorships that share a title. An item of another student, or
of the same student in another year, is a new advisorship; the same work
listed twice stays one. The loader is built without a database, as in
tests/test_project_loader_matching.py; the handler is a stub that names new
advisorships the way AdvisorshipHandler does."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from eo_lib import Initiative
from research_domain.domain.entities import Advisorship

from src.core.logic.advisorship_matching import SUFFIX_MARK, base_title
from src.core.logic.initiative_identity import normalize_text
from src.core.logic.project_loader import ProjectLoader
from src.core.logic.strategies.lattes_advisorships import (
    LattesAdvisorshipMappingStrategy,
)
from src.core.logic.strategies.sigpesq_advisorships import (
    SigPesqAdvisorshipMappingStrategy,
)

TITLE = "Estágio Supervisionado Obrigatório"


class _Handler:
    """Stands in for AdvisorshipHandler: no database, same naming."""

    def __init__(self, loader):
        self.loader = loader
        self.calls = []
        self.created = {}

    def item_student(self, project_data):
        names = project_data.get("student_names") or [None]
        return None, normalize_text(names[0])

    def find_existing(self, project_data):
        return None

    def create_or_update(self, **kwargs):
        self.calls.append(kwargs)
        existing = kwargs["existing_initiative"]
        if existing is not None:
            return existing
        data = kwargs["project_data"]
        title = data["title"]
        advisorship = MagicMock(spec=Advisorship)
        advisorship.id = 1000 + len(self.created)
        if self.loader._advisorship_index.get(base_title(title)):
            student = (data.get("student_names") or [""])[0]
            year = data["start_date"].year if data.get("start_date") else ""
            advisorship.name = f"{title}{SUFFIX_MARK} {student} | {year}"
        else:
            advisorship.name = title
        self.created[advisorship.id] = advisorship
        return advisorship

    @property
    def creations(self):
        return [c for c in self.calls if c["existing_initiative"] is None]

    @property
    def updates(self):
        return [c for c in self.calls if c["existing_initiative"] is not None]


def _loader(stored_rows=None, claims=None):
    loader = ProjectLoader.__new__(ProjectLoader)
    loader.controller = MagicMock()
    session = loader.controller._service._repository._session

    def execute(statement, *args, **kwargs):
        result = MagicMock()
        result.fetchone.return_value = None
        claimed = "source_field_claims" in str(statement)
        result.fetchall.return_value = (claims if claimed else stored_rows) or []
        return result

    session.execute.side_effect = execute
    loader._advisorship_index = None
    handler = _Handler(loader)
    loader.adv_controller = MagicMock()
    loader.adv_controller.get_by_id.side_effect = handler.created.get
    loader.handlers = {Initiative: handler, Advisorship: handler}
    loader.entity_manager = MagicMock()
    loader.initiative_type = MagicMock(id=2, name="Advisorship")
    loader.org_id = 1
    loader.linker = MagicMock()
    loader._initiative_states = lambda ids: {}
    loader.maps = ({}, {}, {})
    loader.stats = {
        "created": 0,
        "updated": 0,
        "skipped_not_approved": 0,
        "skipped_no_title": 0,
        "failed": 0,
        "teams": 0,
        "skipped_reasons": {},
    }
    return loader, handler


def _process(loader, strategy, row):
    by_name, by_identity, by_norm = loader.maps
    loader.mapping_strategy = strategy
    with patch("src.core.logic.project_loader.tracking_recorder") as tracking:
        tracking.record_source_record.return_value = None
        loader._process_row(
            row,
            by_name,
            by_identity,
            loader.stats,
            source_file="cv.json",
            existing_by_norm_name=by_norm,
        )


def _lattes(student, year, title=TITLE):
    return {
        "title": title,
        "student_name": student,
        "start_year": year,
        "end_year": year,
        "type_name": "Trabalho de conclusão de curso de graduação",
        "nature": "Orientações concluídas",
        "status": "Concluded",
    }


def _sigpesq(row_id, student, start, end, cancelled=False, title=TITLE):
    return {
        "Id": row_id,
        "CodPT": "PT 5475",
        "CodPJ": "PJ 77",
        "TituloPT": title,
        "Orientado": student,
        "OrientadoEmail": f"{normalize_text(student).replace(' ', '.')}@exemplo.org",
        "Orientador": "Orientadora Exemplo",
        "OrientadorEmail": "orientadora@exemplo.org",
        "Inicio": start,
        "Fim": end,
        "Cancelado": cancelled,
        "Programa": "PIBIC",
    }


ADVISOR = LattesAdvisorshipMappingStrategy("Orientadora Exemplo")
CO_ADVISOR = LattesAdvisorshipMappingStrategy("Coorientador Exemplo")
SIGPESQ = SigPesqAdvisorshipMappingStrategy()


def _students(loader, title=TITLE):
    return sorted(entry.student_name for entry in loader._advisorship_index[title])


# --- US1: different students ----------------------------------------------


def test_alunos_diferentes_viram_orientacoes_diferentes():
    loader, handler = _loader()
    for number in range(49):
        _process(loader, ADVISOR, _lattes(f"Aluno Número {number}", 2020))

    assert len(handler.creations) == 49
    assert handler.updates == []
    assert loader.stats["created"] == 49
    assert len(loader._advisorship_index[TITLE]) == 49
    assert len(set(_students(loader))) == 49


def test_o_primeiro_fica_com_o_titulo_e_os_outros_com_nome_distinto():
    loader, handler = _loader()
    for number in range(49):
        _process(loader, ADVISOR, _lattes(f"Aluno Número {number}", 2020))

    names = [advisorship.name for advisorship in handler.created.values()]
    assert names.count(TITLE) == 1
    assert sum(SUFFIX_MARK in name for name in names) == 48
    assert len(set(names)) == 49


def test_segundo_item_do_mesmo_aluno_atualiza():
    loader, handler = _loader()
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))

    assert len(handler.creations) == 1
    assert len(handler.updates) == 1
    assert handler.updates[0]["existing_initiative"] is handler.created[1000]
    assert loader.stats["updated"] == 1


def test_item_de_outro_aluno_nao_toca_a_orientacao_existente():
    loader, handler = _loader()
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))
    _process(loader, ADVISOR, _lattes("Bia Estudante", 2020))
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))

    assert [c["project_data"]["student_names"] for c in handler.creations] == [
        ["Ana Estudante"],
        ["Bia Estudante"],
    ]
    # The third item goes back to Ana's advisorship, not to the last written.
    assert handler.updates[0]["existing_initiative"] is handler.created[1000]


# --- US2: SigPesq, a replaced student --------------------------------------


def _cancelled_claims(claims):
    return {
        call.args[1]: call.args[3]
        for call in claims.call_args_list
        if call.args[0] == "advisorship" and call.args[2] == "cancelled"
    }


def test_aluno_substituido_e_cancelado_ficam_com_orientacoes_proprias():
    loader, handler = _loader()
    with patch("src.core.logic.project_loader.claim") as claims:
        _process(
            loader, SIGPESQ, _sigpesq(1, "Ana Cancelada", "01-08-25", "31-07-26", True)
        )
        _process(loader, SIGPESQ, _sigpesq(2, "Bia Substituta", "01-02-26", "31-07-26"))

    assert len(handler.creations) == 2
    assert handler.updates == []
    assert [c["project_data"]["cancelled"] for c in handler.creations] == [True, False]
    assert _cancelled_claims(claims) == {1000: True, 1001: False}
    assert _students(loader) == ["ana cancelada", "bia substituta"]


def test_ordem_das_linhas_nao_muda_o_resultado():
    loader, handler = _loader()
    with patch("src.core.logic.project_loader.claim") as claims:
        _process(loader, SIGPESQ, _sigpesq(2, "Bia Substituta", "01-02-26", "31-07-26"))
        _process(
            loader, SIGPESQ, _sigpesq(1, "Ana Cancelada", "01-08-25", "31-07-26", True)
        )

    assert len(handler.creations) == 2
    assert sorted(_cancelled_claims(claims).values()) == [False, True]
    assert _students(loader) == ["ana cancelada", "bia substituta"]


def test_mesmo_aluno_cancelado_e_reativado_fica_em_uma_orientacao():
    loader, handler = _loader()
    _process(
        loader, SIGPESQ, _sigpesq(1, "Ana Estudante", "01-08-25", "31-07-26", True)
    )
    _process(loader, SIGPESQ, _sigpesq(2, "Ana Estudante", "01-02-26", "31-07-26"))

    assert len(handler.creations) == 1
    assert len(handler.updates) == 1


# --- US3: the same work stays one advisorship ------------------------------


def test_orientador_e_coorientador_ficam_em_uma_orientacao():
    loader, handler = _loader()
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))
    _process(loader, CO_ADVISOR, _lattes("ANA ESTUDANTE", 2020))

    assert len(handler.creations) == 1
    assert len(handler.updates) == 1


def test_lattes_e_sigpesq_do_mesmo_aluno_ficam_em_uma_orientacao():
    loader, handler = _loader()
    _process(loader, SIGPESQ, _sigpesq(1, "ANA ESTUDANTE", "01-08-25", "31-07-26"))
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2026))

    assert len(handler.creations) == 1
    assert len(handler.updates) == 1


def test_anos_diferentes_do_mesmo_aluno_viram_duas():
    loader, handler = _loader()
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2019))
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))

    assert len(handler.creations) == 2
    assert len(handler.updates) == 1
    assert handler.updates[0]["existing_initiative"] is handler.created[1001]
    assert [e.years for e in loader._advisorship_index[TITLE]] == [
        (2019, 2019),
        (2020, 2020),
    ]


def test_item_sem_ano_fica_na_orientacao_existente():
    loader, handler = _loader()
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2020))
    _process(loader, ADVISOR, _lattes("Ana Estudante", None))

    assert len(handler.creations) == 1
    assert len(handler.updates) == 1
    assert loader._advisorship_index[TITLE][0].years == (2020, 2020)


def test_o_indice_e_carregado_do_banco():
    distinct = f"{TITLE}{SUFFIX_MARK} Bia Estudante | 2020"
    loader, handler = _loader(
        stored_rows=[
            (
                1,
                TITLE,
                datetime(2020, 1, 1),
                datetime(2020, 12, 31),
                71,
                "Ana Estudante",
            ),
            (2, distinct, "2020-01-01 00:00:00", None, 72, "Bia Estudante"),
            (3, "Outro Trabalho", None, None, None, None),
        ]
    )
    for ident, name in ((1, TITLE), (2, distinct), (3, "Outro Trabalho")):
        handler.created[ident] = MagicMock(spec=Advisorship, id=ident)
        handler.created[ident].name = name

    index = loader._ensure_advisorship_index()
    assert [(e.id, e.student_id, e.student_name, e.years) for e in index[TITLE]] == [
        (1, 71, "ana estudante", (2020, 2020)),
        (2, 72, "bia estudante", (2020, 2020)),
    ]
    assert index["Outro Trabalho"][0].student_name == ""

    _process(loader, ADVISOR, _lattes("Bia Estudante", 2020))
    assert handler.creations == []
    assert handler.updates[0]["existing_initiative"] is handler.created[2]

    _process(loader, ADVISOR, _lattes("Carla Estudante", 2020))
    assert len(handler.creations) == 1


def test_os_anos_guardados_incluem_as_datas_que_cada_fonte_informou():
    """Found in the second local run (T024): a SigPesq row of 08/2015-07/2016
    and the curriculum's items of 2015 and 2016 are one advisorship, but the
    field merge stores the dates of the newest document (2016 only). The
    curriculum's 2015 item must still match when it is processed again."""
    loader, handler = _loader(
        stored_rows=[
            (
                143,
                TITLE,
                "2016-01-01 00:00:00",
                "2016-12-31 00:00:00",
                71,
                "Ana Estudante",
            ),
            (144, "Outro Trabalho", "2016-01-01 00:00:00", None, 72, "Bia Estudante"),
        ],
        claims=[
            (143, '"2015-08-01"'),
            (143, '"2016-07-31"'),
            (143, '"2016-01-01"'),
            (143, '"2016-12-31"'),
            (144, "null"),
            (999, '"2001-01-01"'),
        ],
    )
    for ident, name in ((143, TITLE), (144, "Outro Trabalho")):
        handler.created[ident] = MagicMock(spec=Advisorship, id=ident)
        handler.created[ident].name = name

    index = loader._ensure_advisorship_index()
    assert index[TITLE][0].years == (2015, 2016)
    assert index["Outro Trabalho"][0].years == (2016, 2016)

    _process(loader, ADVISOR, _lattes("Ana Estudante", 2015))
    assert handler.creations == []
    assert handler.updates[0]["existing_initiative"] is handler.created[143]

    # A year outside everything the sources informed is still another one.
    _process(loader, ADVISOR, _lattes("Ana Estudante", 2018))
    assert len(handler.creations) == 1
