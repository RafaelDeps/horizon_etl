from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from loguru import logger
from sqlalchemy import text

from src.adapters.sources.lattes_parser import LattesParser
from src.core.logic.person_identity import normalize_participant_name
from src.core.logic.researcher_creation import create_researcher_with_resume_fallback
from src.research_domain_compat import AdvisorshipRole


@dataclass
class ResearcherRef:
    """Registro leve de pesquisador, usado apenas para achar o dono de um CV.

    Expõe os MESMOS nomes de atributo da entidade ``Researcher`` de propósito: o
    algoritmo de pontuação lê candidatos por ``getattr``, então este registro
    atravessa a correspondência sem que o algoritmo mude — e é a equivalência do
    algoritmo que precisa ser preservada.

    Ao contrário da entidade, este registro NÃO pertence à sessão do SQLAlchemy.
    Ele não expira quando ``ProjectLoader._rollback_session()`` descarta a
    transação. Um índice de entidades ORM, sim: medido em 12,4 s para reidratar
    1061 objetos depois de um único rollback, mesmo com ``lazyload``, porque o
    refresh reexecuta o carregamento padrão do mapper.
    """

    id: Any
    name: Optional[str] = None
    identification_id: Optional[str] = None
    cnpq_url: Optional[str] = None
    resume: Optional[str] = None
    citation_names: Optional[str] = None


_RESEARCHER_INDEX_SQL = text(
    """
    SELECT r.id                AS id,
           p.name              AS name,
           p.identification_id AS identification_id,
           r.cnpq_url          AS cnpq_url,
           r.resume            AS resume,
           r.citation_names    AS citation_names
    FROM researchers r
    JOIN persons p ON p.id = r.id
    """
)


def load_researcher_index(session: Any) -> List[ResearcherRef]:
    """Lê, numa única consulta, o mínimo necessário para casar currículos.

    Substitui ``ResearcherController().get_all()`` nos laços de ingestão do
    Lattes. Aquele traz junto quatro coleções carregadas de forma ansiosa
    (``knowledge_areas``, ``articles``, ``productions``, ``emails``), o que
    transforma 1060 pesquisadores em 828.644 linhas e custa 7,8 s por chamada.
    Esta consulta devolve 1060 linhas de seis colunas em menos de 1 ms.

    Devolve lista vazia — sem levantar — quando não há sessão ou quando as
    tabelas ainda não existem, para que a primeira execução contra um banco
    recém-criado não falhe.
    """
    if session is None:
        logger.warning("No DB session available; researcher index will be empty.")
        return []

    try:
        rows = session.execute(_RESEARCHER_INDEX_SQL).fetchall()
    except Exception as exc:
        logger.warning(f"Could not load researcher index: {exc}")
        return []

    return [
        ResearcherRef(
            id=row.id,
            name=row.name,
            identification_id=row.identification_id,
            cnpq_url=row.cnpq_url,
            resume=row.resume,
            citation_names=row.citation_names,
        )
        for row in rows
    ]


def researcher_ref(researcher: Any) -> ResearcherRef:
    """Converte uma entidade (ou objeto compatível) num registro do índice."""
    return ResearcherRef(
        id=getattr(researcher, "id", None),
        name=getattr(researcher, "name", None),
        identification_id=getattr(researcher, "identification_id", None),
        cnpq_url=getattr(researcher, "cnpq_url", None),
        resume=getattr(researcher, "resume", None),
        citation_names=getattr(researcher, "citation_names", None),
    )


def sync_researcher_ref(candidates: Iterable[Any], researcher: Any) -> None:
    """Reflete no índice os campos que a ingestão acabou de atualizar.

    ``projects.py`` grava ``citation_names``, ``cnpq_url`` e ``resume`` do dono
    do currículo. Sem isto, currículos processados em seguida pontuariam sobre
    um estado velho — o índice é lido uma vez só, então ele precisa acompanhar.
    """
    researcher_id = getattr(researcher, "id", None)
    if researcher_id is None:
        return
    for candidate in candidates:
        if not isinstance(candidate, ResearcherRef) or candidate.id != researcher_id:
            continue
        candidate.name = getattr(researcher, "name", candidate.name)
        candidate.cnpq_url = getattr(researcher, "cnpq_url", candidate.cnpq_url)
        candidate.resume = getattr(researcher, "resume", candidate.resume)
        candidate.citation_names = getattr(
            researcher, "citation_names", candidate.citation_names
        )
        return


def resolve_researcher_from_lattes(
    all_researchers: Iterable[Any],
    *,
    lattes_id: Optional[str] = None,
    json_name: Optional[str] = None,
    session: Any = None,
) -> Optional[Any]:
    """Find the best existing Researcher for a Lattes curriculum.

    The dataset may contain duplicates that differ only by accents/casing.
    We score candidates using stable identifiers first, then normalized name,
    and finally prefer the record that already has linked data in the DB.

    Accepts either ORM entities or ``ResearcherRef`` records — candidates are
    read exclusively through ``getattr``, so both behave identically.

    What actually matches, in practice: ``cnpq_url`` carries the Lattes ID and
    is the stable identifier that fires. ``identification_id`` is anonymized on
    write, so a raw Lattes ID never equals it. Name comparison covers the rest.
    A ``brand_id`` branch used to sit here scoring 500 — the heaviest rule in
    the function — but that column exists neither in ``persons`` nor in
    ``researchers``, nor as a mapped attribute, so it never once fired. It was
    removed rather than left implying a robustness that was not there.
    """

    parser = LattesParser()
    json_name_norm = parser.normalize_title(json_name) if json_name else ""

    best = None
    best_score = float("-inf")

    for researcher in all_researchers:
        score = _score_candidate(
            researcher,
            lattes_id=lattes_id,
            json_name=json_name,
            json_name_norm=json_name_norm,
            session=session,
        )
        if score > best_score:
            best = researcher
            best_score = score

    if best_score <= 0:
        return None

    logger.debug(
        "Resolved Lattes researcher '{}' (Lattes ID: {}) to DB ID {} with score {}.",
        json_name,
        lattes_id,
        getattr(best, "id", None),
        best_score,
    )
    return best


def resolve_researcher_by_name(
    all_researchers: Iterable[Any],
    *,
    name: Optional[str],
    identification_id: Optional[str] = None,
) -> Optional[Any]:
    if not name:
        return None

    target_norm = normalize_participant_name(name)

    best = None
    best_score = float("-inf")
    for researcher in all_researchers:
        score = 0
        res_name = getattr(researcher, "name", None) or ""
        res_identification = getattr(researcher, "identification_id", None) or ""

        if (
            identification_id
            and res_identification
            and str(res_identification).casefold() == str(identification_id).casefold()
        ):
            score += 200
        if res_name and res_name.casefold() == name.casefold():
            score += 150
        elif normalize_participant_name(res_name) == target_norm:
            score += 100

        if score > best_score:
            best = researcher
            best_score = score

    return best if best_score > 0 else None


def resolve_or_create_researcher(
    researcher_ctrl: Any,
    all_researchers: list[Any],
    *,
    name: Optional[str],
    identification_id: Optional[str] = None,
    emails: Optional[list[str]] = None,
) -> Optional[Any]:
    researcher = resolve_researcher_by_name(
        all_researchers,
        name=name,
        identification_id=identification_id,
    )
    if researcher:
        return researcher

    if not name:
        return None

    researcher = create_researcher_with_resume_fallback(
        researcher_ctrl,
        name=name,
        identification_id=identification_id,
        emails=emails,
    )
    if researcher:
        # O índice de correspondência recebe um registro leve; listas de
        # entidades ORM (cnpq_sync, sigpesq_excel) continuam recebendo a
        # entidade, como antes. O algoritmo lê tudo por getattr, então os dois
        # formatos convivem sem que ele precise saber a diferença.
        if all_researchers and isinstance(all_researchers[0], ResearcherRef):
            all_researchers.append(researcher_ref(researcher))
        else:
            all_researchers.append(researcher)
    return researcher


def _score_candidate(
    researcher: Any,
    *,
    lattes_id: Optional[str],
    json_name: Optional[str],
    json_name_norm: str,
    session: Any,
) -> int:
    parser = LattesParser()

    score = 0
    matched = False
    name = getattr(researcher, "name", None) or ""
    identification_id = getattr(researcher, "identification_id", None) or ""
    cnpq_url = getattr(researcher, "cnpq_url", None) or ""

    if lattes_id:
        if str(identification_id) == lattes_id:
            score += 400
            matched = True
        if lattes_id in str(cnpq_url):
            score += 350
            matched = True

    if json_name:
        if name.casefold() == json_name.casefold():
            score += 200
            matched = True
        elif parser.normalize_title(name) == json_name_norm:
            score += 150
            matched = True

    if not matched:
        return 0

    score += _linked_data_score(getattr(researcher, "id", None), session)

    if getattr(researcher, "resume", None):
        score += 25
    if getattr(researcher, "citation_names", None):
        score += 10

    return score


def _linked_data_score(person_id: Optional[int], session: Any) -> int:
    if not person_id or session is None:
        return 0

    try:
        row = session.execute(
            text(
                """
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM advisorship_members
                        WHERE role_name = :supervisor_role
                          AND person_id = :pid
                    ) +
                    (SELECT COUNT(*) FROM academic_educations WHERE researcher_id = :pid) +
                    (SELECT COUNT(*) FROM article_authors WHERE researcher_id = :pid)
                """
            ),
            {
                "pid": person_id,
                "supervisor_role": AdvisorshipRole.SUPERVISOR.value,
            },
        ).fetchone()
        return int(row[0] or 0) * 20 if row else 0
    except Exception:
        try:
            row = session.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT COUNT(*)
                            FROM advisorships
                            WHERE supervisor_id = :pid
                        ) +
                        (SELECT COUNT(*) FROM academic_educations WHERE researcher_id = :pid) +
                        (SELECT COUNT(*) FROM article_authors WHERE researcher_id = :pid)
                    """
                ),
                {"pid": person_id},
            ).fetchone()
            return int(row[0] or 0) * 20 if row else 0
        except Exception:
            return 0
