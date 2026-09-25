"""
Gera a planilha de fornecimento de dados do PNP (Plano Nacional de
Pós-Graduação) no formato .xlsx, uma aba por template PARCIAL (9 abas).

Fonte única: os JSON canônicos de ``data/exports/``. Nenhum banco, nenhum
pipeline, nenhuma fonte externa (SigPesq, Lattes e CNPq são lidos apenas na
forma já materializada nos exports). O SRC ETL não é consultado: os campos
que só existem lá (processo, tipo de ação, grande área, público, times de
extensão) ficam **nulos**.

Colunas PNP sem equivalente nos exports (código de estrutura, código CNPq de
área, subeixo tecnológico, CPF, valores financeiros) são gravadas como nulo
de verdade (célula vazia), nunca preenchidas com valores inventados. Use
``--null-text`` para gravar um texto literal no lugar do nulo.

Datas do Lattes são ano apenas: o export traz ``AAAA-01-01``. Nessas linhas
``data_inicio_derivada`` = ``sim``, para que o consumidor não trate a data
como coletada.

Abas geradas (nesta ordem):
  1. projetos_pesquisa                  2. acoes_extensao
  3. pessoas_envolvidas_projeto_76e8    4. projetos_ensino
  5. projetos_gestao_di                 6. producao_intelectual
  7. pessoas_envolvidas_acoes_e_5c1d    8. pessoas_atendidas_acoes_ex_986a
  9. programa

Referência: data/reports/viabilidade-planilha-pnp.md

Uso:
  python -m src.scripts.export_pnp_xlsx
  python -m src.scripts.export_pnp_xlsx --out data/reports/pnp.xlsx
  python -m src.scripts.export_pnp_xlsx --null-text "null"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORTS_DIR = REPO_ROOT / "data" / "exports"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "reports" / "planilha-pnp-parcial.xlsx"

SHEET_TITLES = (
    "projetos_pesquisa",
    "acoes_extensao",
    "pessoas_envolvidas_projeto_76e8",
    "projetos_ensino",
    "projetos_gestao_di",
    "producao_intelectual",
    "pessoas_envolvidas_acoes_e_5c1d",
    "pessoas_atendidas_acoes_ex_986a",
    "programa",
)

# Campos sem nenhuma fonte nos exports do Horizon ETL: todos gravados como
# nulo. Mantidos como constantes para deixar a lacuna explícita no código.
AUSENTE = None

# "01-08-22" (SigPesq: DD-MM-AA)
_SIGPESQ_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})$")
_DASHES = re.compile(r"[\u2010-\u2015\-]")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


# ---------------------------------------------------------------------------
# Helpers de normalização
# ---------------------------------------------------------------------------


def _norm_key(name: str | None) -> str:
    """Chave de comparação de títulos (sem acento, pontuação ou hífen).

    SigPesq, Lattes e a deduplicação gravam o mesmo projeto com grafias
    diferentes (vírgula final, hífen tipográfico, reticências), então a
    comparação literal perderia casamentos legítimos.
    """
    text = (name or "").lower()
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = _DASHES.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _join(values: Any, sep: str = "; ") -> str | None:
    """Junta uma lista em string única, ignorando vazios; None se tudo vazio."""
    if values is None:
        return None
    if isinstance(values, str):
        parts = [values.strip()]
    else:
        parts = [str(value).strip() for value in values if str(value or "").strip()]
    parts = [part for part in parts if part]
    return sep.join(parts) if parts else None


def _date(value: Any) -> str | None:
    """Normaliza data para ``AAAA-MM-DD``; devolve None quando não há data.

    Aceita ISO (``2022-08-01T00:00:00``) e o formato do SigPesq (``01-08-22``).
    Não completa nem inventa partes ausentes.
    """
    text = str(value or "").strip()
    if not text:
        return None
    match = _SIGPESQ_DATE.match(text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        year += 2000 if year < 70 else 1900
        return f"{year:04d}-{month:02d}-{day:02d}"
    head = text.replace("T", " ").split(" ")[0]
    return head if re.match(r"^\d{4}-\d{2}-\d{2}$", head) else None


def _date_only(value: Any) -> str | None:
    """``AAAA-MM-DD`` a partir de um campo de data canônico (ou None)."""
    return _date(value)


def _year(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _name_of(node: Any) -> str | None:
    """Nome de uma referência (`{id, name}`) ou string simples."""
    if isinstance(node, dict):
        return node.get("name")
    return node


def _load(path: Path) -> list[dict]:
    """Lê um JSON canônico (lista de registros)."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _campus_of(record: dict) -> str | None:
    return _name_of(record.get("campus"))


def _knowledge_areas(record: dict) -> str | None:
    return _join([area.get("name") for area in record.get("knowledge_areas") or []])


# ---------------------------------------------------------------------------
# Carga das fontes (somente data/exports/*.json)
# ---------------------------------------------------------------------------


class Sources:
    """Carregamento sob demanda dos JSON canônicos usados pelas 9 abas."""

    def __init__(self, exports_dir: Path) -> None:
        self.exports_dir = exports_dir
        self._cache: dict[str, list[dict]] = {}

    def get(self, name: str) -> list[dict]:
        if name not in self._cache:
            self._cache[name] = _load(self.exports_dir / f"{name}.json")
        return self._cache[name]

    # -- entidades ---------------------------------------------------------

    @property
    def initiatives(self) -> list[dict]:
        return self.get("initiatives_canonical")

    @property
    def source_records(self) -> list[dict]:
        return self.get("source_records_canonical")

    @property
    def researchers(self) -> list[dict]:
        return self.get("researchers_canonical")

    @property
    def advisorships(self) -> list[dict]:
        return self.get("advisorships_canonical")

    @property
    def production_authors(self) -> list[dict]:
        return self.get("production_authors_canonical")


def build_initiative_index(
    sources: Sources,
) -> tuple[dict[tuple[str, str], dict], dict[str, list[dict]]]:
    """Índices de ``initiatives_canonical`` para casar com as fontes brutas.

    O modelo canônico colapsa os três tipos de projeto do Lattes em
    ``Research Project`` (``project_loader.py`` fixa o tipo), então a
    tipagem real (pesquisa / extensão / desenvolvimento) só existe em
    ``source_records_canonical.raw_payload_json.initiative_type_name``.
    Para recuperar as linhas corretas é preciso casar as duas bases.
    """
    by_name_year: dict[tuple[str, str], dict] = {}
    by_name: dict[str, list[dict]] = defaultdict(list)
    for initiative in sources.initiatives:
        key = _norm_key(initiative.get("name"))
        year = (initiative.get("start_date") or "")[:4]
        by_name_year.setdefault((key, year), initiative)
        by_name[key].append(initiative)
    return by_name_year, dict(by_name)


def match_initiative(
    payload: dict,
    title_field: str,
    by_name_year: dict[tuple[str, str], dict],
    by_name: dict[str, list[dict]],
) -> dict | None:
    """Casa um registro bruto (Lattes/SigPesq) com sua iniciativa canônica."""
    key = _norm_key(payload.get(title_field))
    if not key:
        return None
    year = _year(payload.get("start_year"))
    if year is None:
        year = _year(_date(payload.get("Inicio")))
    if year is not None:
        hit = by_name_year.get((key, f"{year:04d}"))
        if hit is not None:
            return hit
    candidates = by_name.get(key) or []
    return candidates[0] if len(candidates) == 1 else None


# ---------------------------------------------------------------------------
# Situação
# ---------------------------------------------------------------------------


def _is_year_derived(date_value: str | None) -> bool:
    """True quando a data canônica é ``AAAA-01-01``, assinatura do Lattes.

    O Lattes informa apenas o ano; ``lattes_projects.py`` grava
    ``AAAA-01-01``. Datas SigPesq nunca caem nesse padrão.
    """
    return bool(date_value) and date_value.endswith("-01-01")


def _situacao_pnp(initiative: dict | None, parecer: str | None) -> str | None:
    """Situação do registro no enum do PNP (derivada das datas do export).

    Derivação, não dado coletado: ``Planejado`` quando a início ainda não
    ocorreu, ``Encerrado`` quando o fim já passou e ``Em andamento`` entre os
    dois. Registros sem nenhuma data caem em ``Em andamento`` apenas se o
    parecer SigPesq for de aprovação; caso contrário ficam nulos.
    """
    if initiative is None:
        return None
    start = _date_only(initiative.get("start_date"))
    end = _date_only(initiative.get("end_date"))
    today = date.today().isoformat()
    if start and start > today:
        return "Planejado"
    if end and end < today:
        return "Encerrado"
    if start or end:
        return "Em andamento"
    if parecer:
        return "Em andamento" if "aprov" in parecer.lower() else None
    return None


# ---------------------------------------------------------------------------
# 1. projetos_pesquisa
# ---------------------------------------------------------------------------

COLS_PROJETOS_PESQUISA = (
    "estrutura",
    "campus_nome",
    "codigo_projeto",
    "titulo",
    "resumo",
    "data_inicio",
    "data_fim",
    "data_inicio_derivada",
    "situacao",
    "situacao_pnp",
    "natureza",
    "area_conhecimento_nome",
    "area_conhecimento_cnpq",
    "subeixo_tecnologico",
    "grupo_pesquisa",
    "linha_pesquisa",
    "palavras_chave",
    "coordenador_nome",
    "coordenador_cpf",
    "papeis_equipe",
    "n_integrantes",
    "parceiro_demandante",
    "financiadores",
    "valor_investimento",
    "origem",
    "initiative_id",
    "fonte_arquivo",
)


def _coordinator(initiative: dict | None) -> str | None:
    if not initiative:
        return None
    for member in initiative.get("team") or []:
        if "Coordinator" in (member.get("roles") or []):
            return member.get("person_name")
    return None


def _roles(initiative: dict | None) -> str | None:
    if not initiative:
        return None
    roles: list[str] = []
    for member in initiative.get("team") or []:
        roles.extend(member.get("roles") or [])
    return _join(sorted(set(roles)))


def _enrichment(initiative: dict | None, field: str) -> Any:
    if not initiative:
        return None
    enrichment = initiative.get("enrichment") or {}
    return enrichment.get(field)


def _resumo(initiative: dict | None) -> str | None:
    """Texto de resumo do projeto: descrição canônica ou objetivo do enrich.

    A descrição canônica é o texto do documento de projeto; quando o projeto
    não tem documento, sobra o objetivo geral extraído do enrichment.
    """
    if not initiative:
        return None
    description = initiative.get("description")
    if description and description.strip():
        return description.strip()
    objetivos = _enrichment(initiative, "objetivos") or {}
    geral = objetivos.get("geral") if isinstance(objetivos, dict) else None
    return geral.strip() if isinstance(geral, str) and geral.strip() else None


def _keywords(value: Any) -> str | None:
    if isinstance(value, list):
        return _join(
            [item.get("palavra") if isinstance(item, dict) else item for item in value]
        )
    if isinstance(value, str):
        return _join([part for part in re.split(r"[;\n]", value)])
    return None


def build_projetos_pesquisa(sources: Sources) -> list[list[Any]]:
    """Projetos de pesquisa: SigPesq aprovado + Lattes ``Research Project``."""
    by_name_year, by_name = build_initiative_index(sources)
    rows: list[list[Any]] = []

    sigpesq = [
        record
        for record in sources.source_records
        if record["source_system"] == "sigpesq_research_projects"
        and (record.get("raw_payload_json") or {}).get("Titulo")
    ]
    for record in sorted(sigpesq, key=lambda item: item["id"]):
        payload = record["raw_payload_json"]
        parecer = payload.get("ParecerDiretoria")
        if not str(parecer or "").lower().startswith("aprovado"):
            continue
        initiative = match_initiative(payload, "Titulo", by_name_year, by_name)
        team = initiative.get("team") if initiative else None
        rows.append(
            [
                AUSENTE,  # estrutura (código PNP)
                payload.get("CampusExecucao") or _campus_of(initiative or {}),
                payload.get("Id"),
                payload.get("Titulo"),
                _resumo(initiative),
                _date(payload.get("Inicio")),
                _date(payload.get("Fim")),
                "nao",
                parecer,
                _situacao_pnp(initiative, parecer),
                payload.get("Natureza"),
                _join(
                    [
                        payload.get("AreaConhecimento"),
                        _knowledge_areas(initiative or {}),
                    ],
                    sep=" | ",
                ),
                AUSENTE,  # area_conhecimento_cnpq
                AUSENTE,  # subeixo_tecnologico
                payload.get("GrupoPesquisa"),
                payload.get("LinhaPesquisa"),
                _keywords(payload.get("PalavraChave"))
                or _keywords(_enrichment(initiative, "palavras_chave")),
                payload.get("Coordenador") or _coordinator(initiative),
                AUSENTE,  # cpf
                _roles(initiative),
                len(team) if team else None,
                _join(payload.get("ParceiroDemandante")),
                None,  # financiadores (SigPesq não traz financiadores)
                AUSENTE,  # valor_investimento
                "sigpesq",
                (initiative or {}).get("id"),
                record.get("source_file"),
            ]
        )

    lattes = [
        record
        for record in sources.source_records
        if record["source_system"] == "lattes_projects"
        and (record.get("raw_payload_json") or {}).get("initiative_type_name")
        == "Research Project"
    ]
    for record in sorted(lattes, key=lambda item: item["id"]):
        payload = record["raw_payload_json"]
        initiative = match_initiative(payload, "name", by_name_year, by_name)
        team = initiative.get("team") if initiative else None
        rows.append(
            [
                AUSENTE,  # estrutura
                _campus_of(initiative or {}),
                AUSENTE,  # codigo_projeto (Lattes não tem número de projeto)
                payload.get("name") or (initiative or {}).get("name"),
                payload.get("description") or (initiative or {}).get("description"),
                _date_only((initiative or {}).get("start_date"))
                or _year(payload.get("start_year")),
                _date_only((initiative or {}).get("end_date"))
                or _year(payload.get("end_year")),
                "sim",  # ano apenas no Lattes -> AAAA-01-01
                payload.get("status") or (initiative or {}).get("status"),
                _situacao_pnp(initiative, None),
                AUSENTE,  # natureza (Lattes não tem o campo)
                _knowledge_areas(initiative or {}),
                AUSENTE,  # area_conhecimento_cnpq
                AUSENTE,  # subeixo_tecnologico
                _name_of((initiative or {}).get("research_group")),
                _enrichment(initiative, "linha_pesquisa"),
                _enrichment(initiative, "palavras_chave"),
                _coordinator(initiative),
                AUSENTE,  # cpf
                _roles(initiative),
                len(team) if team else None,
                None,  # parceiro_demandante
                _join(payload.get("raw_sponsors")),
                AUSENTE,  # valor_investimento
                "lattes",
                (initiative or {}).get("id"),
                record.get("source_file"),
            ]
        )
    return rows


# ---------------------------------------------------------------------------
# 2 / 5. acoes_extensao e projetos_gestao_di (mesmo formato de projeto)
# ---------------------------------------------------------------------------

COLS_PROJETOS_ACAO = (
    "estrutura",
    "campus_nome",
    "numero_processo",
    "titulo",
    "resumo",
    "tipo_acao",
    "area_tematica_cnpq",
    "grande_area_nome",
    "data_inicio",
    "data_fim",
    "data_inicio_derivada",
    "situacao",
    "situacao_pnp",
    "coordenador_nome",
    "equipe_nomes",
    "n_equipe",
    "programa_vinculante",
    "fomento_nomes",
    "valor_investimento",
    "publico_atendido",
    "coordenador_cpf",
    "origem",
    "initiative_id",
    "fonte_arquivo",
)


def _build_acao_rows(
    sources: Sources, lattes_type: str, origem: str
) -> list[list[Any]]:
    """Ações de um tipo Lattes (`Extension Project` / `Development Project`).

    Os campos que o PNP exige e que só o SRC ETL possui (processo, tipo de
    ação, área temática, grande área, programa vinculante, público) ficam
    nulos: esta planilha é montada só com JSON do Horizon ETL.
    """
    by_name_year, by_name = build_initiative_index(sources)
    records = [
        record
        for record in sources.source_records
        if record["source_system"] == "lattes_projects"
        and (record.get("raw_payload_json") or {}).get("initiative_type_name")
        == lattes_type
    ]
    rows: list[list[Any]] = []
    for record in sorted(records, key=lambda item: item["id"]):
        payload = record["raw_payload_json"]
        initiative = match_initiative(payload, "name", by_name_year, by_name)
        members = payload.get("raw_members") or []
        rows.append(
            [
                AUSENTE,  # estrutura
                _campus_of(initiative or {}),
                AUSENTE,  # numero_processo (só o SRC tem)
                payload.get("name") or (initiative or {}).get("name"),
                payload.get("description") or (initiative or {}).get("description"),
                AUSENTE,  # tipo_acao (enum SRC)
                AUSENTE,  # area_tematica_cnpq
                _knowledge_areas(initiative or {}),
                _date_only((initiative or {}).get("start_date"))
                or _year(payload.get("start_year")),
                _date_only((initiative or {}).get("end_date"))
                or _year(payload.get("end_year")),
                "sim",  # Lattes informa apenas o ano
                payload.get("status") or (initiative or {}).get("status"),
                _situacao_pnp(initiative, None),
                _coordinator(initiative),
                _join([member.get("nome") for member in members]),
                len(members) or None,
                AUSENTE,  # programa_vinculante (Ação vinculante é SRC)
                _join(payload.get("raw_sponsors")),
                AUSENTE,  # valor_investimento
                AUSENTE,  # publico_atendido
                AUSENTE,  # cpf
                origem,
                (initiative or {}).get("id"),
                record.get("source_file"),
            ]
        )
    return rows


# ---------------------------------------------------------------------------
# 3. pessoas_envolvidas_projeto_76e8
# ---------------------------------------------------------------------------

COLS_PESSOAS_PROJETO = (
    "nome",
    "cpf",
    "categoria",
    "categoria_origem",
    "estrutura",
    "campus_nome",
    "initiative_id",
    "projeto_nome",
    "tipo_projeto_origem",
    "data_inicio_participacao",
    "data_inicio_derivada",
    "data_fim_participacao",
    "origem",
)


def build_pessoas_envolvidas_projeto(sources: Sources) -> list[list[Any]]:
    """Equipe das iniciativas do modelo canônico (papel, categoria, período).

    ``data_inicio_participacao`` é a data de início do projeto
    (``initiative_linker.py``), não a data de ingresso da pessoa: por isso
    ``data_inicio_derivada`` = ``sim``. ``data_fim_participacao`` é nulo em
    100% das linhas (o export nunca grava o fim da participação).
    """
    types = {
        record["id"]: record["name"]
        for record in sources.get("initiative_types_canonical")
    }
    rows: list[list[Any]] = []
    for initiative in sorted(sources.initiatives, key=lambda item: item["id"]):
        campus = _campus_of(initiative)
        for member in initiative.get("team") or []:
            rows.append(
                [
                    member.get("person_name"),
                    AUSENTE,  # cpf (0 de 9.907 pesquisadores com identification_id)
                    AUSENTE,  # categoria PNP (tradução de papéis não validada)
                    _join(member.get("roles")),
                    AUSENTE,  # estrutura
                    campus,
                    initiative.get("id"),
                    initiative.get("name"),
                    types.get(initiative.get("initiative_type_id")),
                    _date_only(member.get("start_date")),
                    "sim",
                    _date_only(member.get("end_date")),
                    "horizon_canonical",
                ]
            )
    return rows


# ---------------------------------------------------------------------------
# 7. pessoas_envolvidas_acoes_e_5c1d
# ---------------------------------------------------------------------------

COLS_PESSOAS_ACAO = (
    "nome",
    "cpf",
    "categoria",
    "categoria_origem",
    "estrutura",
    "campus_nome",
    "acao_nome",
    "numero_processo",
    "papel_acao",
    "data_inicio_acao",
    "data_fim_acao",
    "data_inicio_derivada",
    "origem",
)


def build_pessoas_envolvidas_acoes(sources: Sources) -> list[list[Any]]:
    """Equipe (``raw_members``) das ações de extensão do Lattes.

    A equipe de execução das ações do SRC não é gerada aqui: ``data/participacoes/``
    está vazio no repositório do SRC ETL e nada de CPF foi coletado.
    """
    by_name_year, by_name = build_initiative_index(sources)
    records = [
        record
        for record in sources.source_records
        if record["source_system"] == "lattes_projects"
        and (record.get("raw_payload_json") or {}).get("initiative_type_name")
        == "Extension Project"
    ]
    rows: list[list[Any]] = []
    for record in sorted(records, key=lambda item: item["id"]):
        payload = record["raw_payload_json"]
        initiative = match_initiative(payload, "name", by_name_year, by_name)
        campus = _campus_of(initiative or {})
        for member in payload.get("raw_members") or []:
            rows.append(
                [
                    member.get("nome"),
                    AUSENTE,  # cpf
                    AUSENTE,  # categoria PNP
                    member.get("papel"),
                    AUSENTE,  # estrutura
                    campus,
                    payload.get("name") or (initiative or {}).get("name"),
                    AUSENTE,  # numero_processo
                    member.get("papel"),
                    _date_only((initiative or {}).get("start_date"))
                    or _year(payload.get("start_year")),
                    _date_only((initiative or {}).get("end_date"))
                    or _year(payload.get("end_year")),
                    "sim",
                    "lattes_extension",
                ]
            )
    return rows


# ---------------------------------------------------------------------------
# 4 / 8. abas sem fonte no Horizon ETL
# ---------------------------------------------------------------------------

COLS_PROJETOS_ENSINO = COLS_PROJETOS_ACAO

COLS_PESSOAS_ATENDIDAS = (
    "nome",
    "cpf",
    "categoria",
    "categoria_origem",
    "estrutura",
    "campus_nome",
    "acao_nome",
    "numero_processo",
    "data_participacao",
    "qtd_participacoes",
    "aprovados",
    "certificados",
    "origem",
)


# ---------------------------------------------------------------------------
# 6. producao_intelectual
# ---------------------------------------------------------------------------

COLS_PRODUCAO = (
    "tipo_producao",
    "titulo",
    "ano",
    "data",
    "autores",
    "n_autores",
    "cpf_autores",
    "doi",
    "revista_conferencia",
    "volume",
    "paginas",
    "isbn",
    "editora",
    "link",
    "versao",
    "plataforma",
    "area_conhecimento",
    "area_conhecimento_cnpq",
    "estrutura",
    "campus_nome",
    "registro_patente",
    "producao_id",
    "origem",
)


def build_producao_intelectual(sources: Sources) -> list[list[Any]]:
    """Artigos + produções técnicas.

    ``registro_patente`` é nulo: o bloco ``patentes_registros`` dos 126
    currículos Lattes está vazio (0 patentes, 0 desenhos industriais, 0
    programas de computador), e não há outro campo de registro no export.
    Autores só existem para ``research_productions_canonical``
    (``production_authors_canonical``); os 2.425 artigos não têm vínculo de
    autor nos exports, então a coluna fica nula nessas linhas.
    """
    names = {person["id"]: person.get("name") for person in sources.researchers}
    authors_by_production: dict[int, list[int]] = defaultdict(list)
    for link in sources.production_authors:
        authors_by_production[link["production_id"]].append(link["researcher_id"])
    type_names = {
        record["id"]: record["name"]
        for record in sources.get("production_types_canonical")
    }

    rows: list[list[Any]] = []
    for article in sorted(
        sources.get("articles_canonical"), key=lambda item: item["id"]
    ):
        rows.append(
            [
                article.get("type") or "Artigo",
                article.get("title"),
                article.get("year"),
                None,  # data (artigo tem ano, não data)
                None,  # autores: sem vínculo nos exports
                None,
                None,  # cpf
                article.get("doi"),
                article.get("journal_conference"),
                article.get("volume"),
                article.get("pages"),
                None,  # isbn
                None,  # editora
                None,  # link
                None,  # versao
                None,  # plataforma
                None,  # area_conhecimento
                None,  # area_conhecimento_cnpq
                None,  # estrutura
                _campus_of(article),
                None,  # registro_patente
                article.get("id"),
                "articles_canonical",
            ]
        )

    for production in sorted(
        sources.get("research_productions_canonical"), key=lambda item: item["id"]
    ):
        author_ids = authors_by_production.get(production["id"], [])
        authors = _join([names.get(pid) for pid in author_ids])
        rows.append(
            [
                type_names.get(production.get("production_type_id")),
                production.get("title"),
                production.get("year"),
                None,  # data
                authors,
                len(author_ids) or None,
                None,  # cpf
                None,  # doi
                None,  # revista_conferencia
                None,  # volume
                production.get("pages"),
                production.get("isbn"),
                production.get("publisher"),
                production.get("link"),
                production.get("version"),
                production.get("platform"),
                None,  # area_conhecimento
                None,  # area_conhecimento_cnpq
                None,  # estrutura
                _campus_of(production),
                None,  # registro_patente
                production.get("id"),
                "research_productions_canonical",
            ]
        )
    return rows


# ---------------------------------------------------------------------------
# 9. programa
# ---------------------------------------------------------------------------

COLS_PROGRAMA = (
    "nome_programa",
    "estrutura",
    "campus_nome",
    "codigo_programa",
    "area_tematica_cnpq",
    "areas_conhecimento",
    "tipo_programa",
    "n_projetos_vinculados",
    "n_integrantes",
    "n_orientandos",
    "coordenador_nome",
    "data_inicio",
    "data_fim",
    "data_inicio_derivada",
    "situacao",
    "situacao_pnp",
    "ref_id",
    "origem",
)


def build_programa(sources: Sources) -> list[list[Any]]:
    """Programas: agenda SigPesq (iniciativa pai) + programas de bolsa.

    ``codigo_programa`` e ``area_tematica_cnpq`` ficam nulos: o PNP espera
    códigos e o export só tem nomes.
    """
    initiatives = sources.initiatives
    by_id = {initiative["id"]: initiative for initiative in initiatives}
    children: dict[int, list[dict]] = defaultdict(list)
    for initiative in initiatives:
        if initiative.get("parent_id"):
            children[initiative["parent_id"]].append(initiative)

    rows: list[list[Any]] = []
    for parent_id in sorted(children):
        parent = by_id.get(parent_id)
        if parent is None:
            continue
        linked = children.get(parent_id, [])
        start = _date_only(parent.get("start_date"))
        rows.append(
            [
                parent.get("name"),
                AUSENTE,  # estrutura
                _campus_of(parent),
                AUSENTE,  # codigo_programa
                AUSENTE,  # area_tematica_cnpq
                _knowledge_areas(parent),
                "Programa de pesquisa (SigPesq)",
                len(linked) or None,
                len(parent.get("team") or []) or None,
                AUSENTE,  # n_orientandos (agenda não orienta)
                _coordinator(parent),
                start,
                _date_only(parent.get("end_date")),
                "sim" if _is_year_derived(start) else "nao",
                parent.get("status"),
                _situacao_pnp(parent, None),
                parent.get("id"),
                "initiatives_canonical (parent_id)",
            ]
        )

    oriented: dict[str, list[dict]] = defaultdict(list)
    for record in sources.advisorships:
        for advisorship in record.get("advisorships") or []:
            program = advisorship.get("program")
            if program:
                oriented[str(program).strip()].append(advisorship)
    for program, items in sorted(oriented.items()):
        years = [item["year"] for item in items if item.get("year")]
        start = f"{min(years)}-01-01" if years else None
        rows.append(
            [
                program,
                AUSENTE,  # estrutura
                None,  # campus_nome (orientações não trazem campus no export)
                AUSENTE,  # codigo_programa
                AUSENTE,  # area_tematica_cnpq
                None,  # areas_conhecimento
                "Programa de bolsa / orientação",
                None,  # n_projetos_vinculados
                None,  # n_integrantes
                len(items),  # n_orientandos
                _join(
                    sorted(
                        {
                            item.get("supervisor_name")
                            for item in items
                            if item.get("supervisor_name")
                        }
                    )
                ),
                start,
                f"{max(years)}-12-31" if years else None,
                "sim" if years else "nao",  # anos são o único dado de período
                None,  # situacao
                None,  # situacao_pnp
                None,  # ref_id
                "advisorships_canonical (program)",
            ]
        )
    return rows


# ---------------------------------------------------------------------------
# Escrita do .xlsx
# ---------------------------------------------------------------------------

_HEADER_FILL = PatternFill("solid", fgColor="1F3864")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def _cell(value: Any, null_text: str | None) -> Any:
    """Valor para célula: vazio vira nulo (None) ou o texto configurado."""
    if value is None:
        return null_text
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else null_text
    if isinstance(value, (list, tuple, set)):
        joined = _join(value)
        return joined if joined else null_text
    return value


def _autosize(sheet: openpyxl.worksheet.worksheet.Worksheet, max_width: int) -> None:
    """Largura por coluna, limitada para não abrir a planilha enorme."""
    widths: dict[int, int] = {}
    for column_cells in sheet.iter_cols():
        letter_index = column_cells[0].column
        longest = 0
        for cell in column_cells[:200]:
            if cell.value is None:
                continue
            longest = max(longest, min(len(str(cell.value)), max_width))
        widths[letter_index] = min(max(longest + 2, 10), max_width)
    for index, width in widths.items():
        sheet.column_dimensions[get_column_letter(index)].width = width


def write_sheet(
    workbook: openpyxl.Workbook,
    title: str,
    columns: tuple[str, ...],
    rows: list[list[Any]],
    null_text: str | None,
) -> int:
    """Grava uma aba com cabeçalho fixo, autofiltro e valores normalizados."""
    sheet = workbook.create_sheet(title=title)
    sheet.append(list(columns))
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        sheet.append([_cell(value, null_text) for value in row])
    sheet.freeze_panes = "A2"
    if sheet.max_row >= 1:
        sheet.auto_filter.ref = (
            f"A1:{get_column_letter(len(columns))}{max(sheet.max_row, 1)}"
        )
    _autosize(sheet, 60)
    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_workbook(
    sources: Sources, null_text: str | None, empty_template_row: bool
) -> tuple[openpyxl.Workbook, dict[str, int]]:
    """Monta o workbook com as 9 abas PARCIAL (na ordem do relatório)."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)

    builders: list[tuple[str, tuple[str, ...], list[list[Any]]]] = [
        ("projetos_pesquisa", COLS_PROJETOS_PESQUISA, build_projetos_pesquisa(sources)),
        (
            "acoes_extensao",
            COLS_PROJETOS_ACAO,
            _build_acao_rows(sources, "Extension Project", "lattes_extension"),
        ),
        (
            "pessoas_envolvidas_projeto_76e8",
            COLS_PESSOAS_PROJETO,
            build_pessoas_envolvidas_projeto(sources),
        ),
        ("projetos_ensino", COLS_PROJETOS_ENSINO, []),
        (
            "projetos_gestao_di",
            COLS_PROJETOS_ACAO,
            _build_acao_rows(sources, "Development Project", "lattes_development"),
        ),
        (
            "producao_intelectual",
            COLS_PRODUCAO,
            build_producao_intelectual(sources),
        ),
        (
            "pessoas_envolvidas_acoes_e_5c1d",
            COLS_PESSOAS_ACAO,
            build_pessoas_envolvidas_acoes(sources),
        ),
        ("pessoas_atendidas_acoes_ex_986a", COLS_PESSOAS_ATENDIDAS, []),
        ("programa", COLS_PROGRAMA, build_programa(sources)),
    ]

    if [name for name, _, _ in builders] != list(SHEET_TITLES):
        raise AssertionError("ordem das abas divergiu de SHEET_TITLES")

    counts: dict[str, int] = {}
    for title, columns, rows in builders:
        if not rows and empty_template_row:
            rows = [[None] * len(columns)]
        counts[title] = write_sheet(workbook, title, columns, rows, null_text)
    return workbook, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Gera a planilha do PNP (.xlsx) com as 9 abas PARCIAL a partir "
            "dos JSON de data/exports."
        )
    )
    parser.add_argument(
        "--exports-dir",
        type=Path,
        default=DEFAULT_EXPORTS_DIR,
        help=f"Diretório dos JSON canônicos (padrão: {DEFAULT_EXPORTS_DIR})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Arquivo .xlsx de saída (padrão: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--null-text",
        default=None,
        help=(
            "Texto a gravar no lugar do nulo. Sem a opção, a célula fica "
            "vazia (nulo de verdade)."
        ),
    )
    parser.add_argument(
        "--empty-tabs-template-row",
        action="store_true",
        help=(
            "Grava uma linha inteiramente nula nas abas sem fonte "
            "(projetos_ensino, pessoas_atendidas_acoes_ex_986a)."
        ),
    )
    args = parser.parse_args(argv)

    exports_dir = args.exports_dir
    if not exports_dir.is_dir():
        parser.error(f"diretório de exports não encontrado: {exports_dir}")

    missing = [
        name
        for name in (
            "initiatives_canonical",
            "source_records_canonical",
            "researchers_canonical",
            "advisorships_canonical",
            "production_authors_canonical",
            "articles_canonical",
            "research_productions_canonical",
            "production_types_canonical",
            "initiative_types_canonical",
        )
        if not (exports_dir / f"{name}.json").is_file()
    ]
    if missing:
        parser.error(
            "JSON canônicos ausentes em "
            f"{exports_dir}: {', '.join(missing)}. Rode `make export-canonical`."
        )

    sources = Sources(exports_dir)
    workbook, counts = build_workbook(
        sources, args.null_text, args.empty_tabs_template_row
    )

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out_path)

    print(f"Planilha PNP gerada: {out_path}")
    print(f"Fonte: {exports_dir} (JSON canônicos)")
    print(f"Nulos: {args.null_text if args.null_text else 'célula vazia (None)'}")
    print("-" * 64)
    for title in SHEET_TITLES:
        count = counts[title]
        note = "" if count else "  <- sem fonte no Horizon ETL"
        print(f"{title:<40} {count:>6} linhas{note}")
    print("-" * 64)
    print(f"{'total':<40} {sum(counts.values()):>6} linhas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
