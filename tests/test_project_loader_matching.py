from unittest.mock import MagicMock, patch

from eo_lib import Initiative
from research_domain.domain.entities import Advisorship

from src.core.logic.project_loader import ProjectLoader


def test_resolve_existing_initiative_prefers_same_model_when_identity_hits_wrong_type():
    loader = ProjectLoader.__new__(ProjectLoader)
    loader.adv_controller = MagicMock()
    loader.controller = MagicMock()

    research_project = MagicMock()
    research_project.id = 1338

    advisorship = MagicMock(spec=Advisorship)
    advisorship.id = 113

    loader.adv_controller.get_by_id.side_effect = [
        None,
        advisorship,
    ]

    existing = loader._resolve_existing_initiative(
        existing_by_name={
            "Instrumentação de um robô móvel para serviços de vigilância.": advisorship
        },
        existing_by_identity={
            "instrumentacao de um robo movel para servicos de vigilancia": research_project
        },
        model_class=Advisorship,
        identity_key="instrumentacao de um robo movel para servicos de vigilancia",
        title="Instrumentação de um robô móvel para serviços de vigilância.",
    )

    assert existing is advisorship


def test_register_existing_initiative_keeps_parent_mapping_when_child_shares_title():
    loader = ProjectLoader.__new__(ProjectLoader)
    loader.adv_controller = MagicMock()
    loader.adv_controller.get_by_id.return_value = None

    parent_project = MagicMock()
    parent_project.id = 258

    child_advisorship = MagicMock(spec=Advisorship)
    child_advisorship.id = 999

    existing_by_name = {
        "Desenvolvimento de uma plataforma de aquisição de sinais cerebrais para projetos orientados a robótica": parent_project
    }

    loader._register_existing_initiative(
        existing_by_name=existing_by_name,
        title="Desenvolvimento de uma plataforma de aquisição de sinais cerebrais para projetos orientados a robótica",
        initiative=child_advisorship,
        model_class=Advisorship,
    )

    assert (
        existing_by_name[
            "Desenvolvimento de uma plataforma de aquisição de sinais cerebrais para projetos orientados a robótica"
        ]
        is parent_project
    )


# ---------------------------------------------------------------------------
# Proteção contra fusão indevida (feature 008-guard-participant-merge)
#
# Contexto, para quem mexer aqui daqui a seis meses: casar iniciativas por nome
# normalizado eliminou 57 projetos duplicados do catálogo — mas, aplicado também
# a orientações, fundiu 100 delas e destruiu 200 vínculos de orientador. Em
# orientação o nome é o título do TRABALHO, e o mesmo trabalho aparece no
# currículo do orientador e no do coorientador, com participantes diferentes; a
# linha sobrevivente ficava só com os de quem gravou por último.
#
# Nenhum dos 283 testes existentes reprovou. Todos verificavam o mecanismo de
# correspondência; nenhum verificava se os participantes sobreviviam. Estes
# testes existem para que a reintrodução do defeito reprove em segundos, em vez
# de exigir uma execução de 75 minutos comparando contagens.
# ---------------------------------------------------------------------------


def _loader_sem_banco():
    """ProjectLoader utilizável sem __init__.

    O __init__ real instancia sete controllers presos a uma sessão global do
    eo_lib. Aqui só o que o caminho exercitado toca.
    """
    loader = ProjectLoader.__new__(ProjectLoader)
    loader.adv_controller = MagicMock()
    loader.controller = MagicMock()
    loader.controller._service._repository._session.execute.return_value.fetchone.return_value = (
        None
    )
    return loader


def _candidato_orientacao(identificador):
    """spec=Advisorship faz o isinstance de _candidate_matches_model responder
    verdadeiro sem consultar o controller — mesmo mecanismo dos testes acima."""
    candidato = MagicMock(spec=Advisorship)
    candidato.id = identificador
    return candidato


def _candidato_projeto(identificador, nome="Projeto"):
    candidato = MagicMock()
    candidato.id = identificador
    candidato.name = nome
    return candidato


# --- US1: orientação nunca casa por nome aproximado ------------------------


def test_orientacao_nao_casa_por_nome_normalizado():
    """R1 do contrato — o caso real que custou 200 vínculos.

    Duas orientações do mesmo trabalho, grafias diferentes, orientadores
    diferentes. Reconhecê-las como a mesma apaga um dos orientadores.
    """
    loader = _loader_sem_banco()
    loader.adv_controller.get_by_id.return_value = None
    ja_existente = _candidato_orientacao(4014)

    existing = loader._resolve_existing_initiative(
        existing_by_name={},
        existing_by_identity={},
        model_class=Advisorship,
        identity_key=None,
        title="ANÁLISE COMPARATIVA DE DESEMPENHO DE CONTROLADORES",
        existing_by_norm_name={
            "analise comparativa de desempenho de controladores": ja_existente
        },
    )

    assert existing is None, (
        "orientação casou por nome aproximado: é a fusão que destruiu 200 "
        "vínculos de orientador numa execução completa"
    )


def test_segunda_orientacao_de_mesmo_titulo_e_criada_e_nao_atualizada():
    """A consequência, que é o que os 283 testes anteriores não verificavam.

    Não basta o resolvedor devolver None: o que importa é a segunda orientação
    chegar ao handler SEM iniciativa existente — ou seja, virar linha nova.
    """
    loader = _loader_sem_banco()
    loader.adv_controller.get_by_id.return_value = None

    handler = MagicMock()
    criadas = []

    def cria(**kwargs):
        nova = _candidato_orientacao(1000 + len(criadas))
        # O nome REAL importa: é ele que vira chave do índice normalizado em
        # _process_row. Sem isto o índice recebe uma chave sem sentido, a
        # segunda linha nunca encontra a primeira, e o teste passa sem
        # exercitar o caminho que deveria proteger.
        nova.name = kwargs["project_data"]["title"]
        criadas.append(kwargs)
        return nova

    handler.create_or_update.side_effect = cria
    loader.handlers = {Initiative: handler, Advisorship: handler}
    loader.mapping_strategy = MagicMock()
    loader.entity_manager = MagicMock()
    loader.initiative_type = MagicMock(id=2, name="Advisorship")
    loader.org_id = 1
    loader.linker = MagicMock()

    titulo = "Análise Comparativa de Desempenho de Controladores"
    loader.mapping_strategy.map_row.side_effect = [
        {"title": titulo, "model_class": Advisorship, "identity_key": "bolsa|1"},
        {
            "title": titulo.upper(),
            "model_class": Advisorship,
            "identity_key": "bolsa|2",
        },
    ]

    existing_by_name, existing_by_identity, existing_by_norm_name = {}, {}, {}
    stats = {
        "created": 0,
        "updated": 0,
        "skipped_not_approved": 0,
        "skipped_no_title": 0,
        "failed": 0,
        "teams": 0,
        "skipped_reasons": {},
    }

    with patch("src.core.logic.project_loader.tracking_recorder") as rastreio:
        rastreio.record_source_record.return_value = None
        for linha in (
            {"orientador": "Marco Cuadros"},
            {"orientador": "Cassius Resende"},
        ):
            loader._process_row(
                linha,
                existing_by_name,
                existing_by_identity,
                stats,
                source_file="teste.xlsx",
                existing_by_norm_name=existing_by_norm_name,
            )

    assert len(criadas) == 2, "o handler foi chamado menos de duas vezes"
    assert criadas[1]["existing_initiative"] is None, (
        "a segunda orientação foi tratada como atualização da primeira — é "
        "exatamente a fusão que apaga os participantes do registro anterior"
    )
    assert stats["created"] == 2
    assert stats["updated"] == 0


# --- US2: projeto continua casando ----------------------------------------


def test_projeto_casa_por_nome_normalizado():
    """R2 — a deduplicação que a proteção não pode reabrir (57 duplicatas)."""
    loader = _loader_sem_banco()
    loader.adv_controller.get_by_id.return_value = None
    ja_existente = _candidato_projeto(65, "Recuperação de Conhecimento em Documentos")

    existing = loader._resolve_existing_initiative(
        existing_by_name={},
        existing_by_identity={},
        model_class=Initiative,
        identity_key=None,
        title="RECUPERAÇÃO DE CONHECIMENTO EM DOCUMENTOS",
        existing_by_norm_name={
            "recuperacao de conhecimento em documentos": ja_existente
        },
    )

    assert existing is ja_existente


def test_correspondencia_exata_tem_precedencia_sobre_a_normalizada():
    """R3 — havendo as duas, a exata vence."""
    loader = _loader_sem_banco()
    loader.adv_controller.get_by_id.return_value = None
    exato = _candidato_projeto(1, "Projeto X")
    aproximado = _candidato_projeto(2, "PROJETO X")

    existing = loader._resolve_existing_initiative(
        existing_by_name={"Projeto X": exato},
        existing_by_identity={},
        model_class=Initiative,
        identity_key=None,
        title="Projeto X",
        existing_by_norm_name={"projeto x": aproximado},
    )

    assert existing is exato


def test_indice_ausente_ou_titulo_vazio_nao_quebram():
    """R5 — degradação silenciosa, nunca exceção."""
    loader = _loader_sem_banco()
    loader.adv_controller.get_by_id.return_value = None

    for indice, titulo in ((None, "Projeto X"), ({}, "Projeto X"), ({"x": 1}, "")):
        assert (
            loader._resolve_existing_initiative(
                existing_by_name={},
                existing_by_identity={},
                model_class=Initiative,
                identity_key=None,
                title=titulo,
                existing_by_norm_name=indice,
            )
            is None
        )


# --- US3: o nome persistido prevalece --------------------------------------


def test_reconhecer_por_grafia_diferente_nao_renomeia_o_registro():
    """R4 — renomear é o que produzia UNIQUE constraint e descarte da linha."""
    loader = _loader_sem_banco()
    loader.adv_controller.get_by_id.return_value = None

    nome_persistido = "Recuperação de Conhecimento em Documentos"
    ja_existente = _candidato_projeto(65, nome_persistido)

    handler = MagicMock()
    handler.create_or_update.return_value = ja_existente
    loader.handlers = {Initiative: handler, Advisorship: handler}
    loader.mapping_strategy = MagicMock()
    loader.mapping_strategy.map_row.return_value = {
        "title": nome_persistido.upper(),
        "model_class": Initiative,
        "identity_key": None,
    }
    loader.entity_manager = MagicMock()
    loader.initiative_type = MagicMock(id=1, name="Research Project")
    loader.org_id = 1
    loader.linker = MagicMock()

    stats = {
        "created": 0,
        "updated": 0,
        "skipped_not_approved": 0,
        "skipped_no_title": 0,
        "failed": 0,
        "teams": 0,
        "skipped_reasons": {},
    }

    with patch("src.core.logic.project_loader.tracking_recorder") as rastreio:
        rastreio.record_source_record.return_value = None
        loader._process_row(
            {"Titulo": nome_persistido.upper()},
            {},
            {},
            stats,
            source_file="teste.xlsx",
            existing_by_norm_name={
                "recuperacao de conhecimento em documentos": ja_existente
            },
        )

    enviado = handler.create_or_update.call_args[1]
    assert enviado["existing_initiative"] is ja_existente
    assert enviado["project_data"]["title"] == nome_persistido, (
        "o registro seria renomeado para a grafia do que chegou, disputando um "
        "nome que outra linha pode ocupar"
    )
