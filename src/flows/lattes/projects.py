import faulthandler
import gc
import glob
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

faulthandler.enable()

from eo_lib import InitiativeController, PersonController, TeamController
from loguru import logger
from prefect import flow, task
from prefect.cache_policies import NO_CACHE
from prefect.utilities.annotations import quote
from research_domain.controllers import (
    AcademicEducationController,
    ArticleController,
    ProductionTypeController,
    ProfessionalActivityController,
    ResearcherController,
    ResearchProductionController,
)
from research_domain.domain.entities.researcher import Researcher
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.adapters.sources.lattes_parser import LattesParser
from src.core.logic.document_skip import carry, current, mark_partial
from src.core.logic.entity_manager import EntityManager
from src.core.logic.horizon_identity import (
    canonical,
    dedupe_same_document,
    lattes_article_key,
    lattes_education_key,
    lattes_id_from_cv_path,
)
from src.core.logic.initiative_identity import normalize_text
from src.core.logic.pii_anonymizer import scrub_pii_deep
from src.core.logic.project_loader import ProjectLoader
from src.core.logic.researcher_resolution import (
    ResearcherRef,
    load_researcher_index,
    log_researcher_resolution_summary,
    resolve_or_create_researcher,
    resolve_researcher_from_lattes,
    sync_researcher_ref,
)
from src.core.logic.strategies.lattes_projects import LattesProjectMappingStrategy
from src.core.ports.document_state_store import DocumentFailed
from src.flows.document_phase import document_phase
from src.flows.lattes.cv_document import finish_lattes_listing, read_cv
from src.flows.lattes.cv_timing import log_cv_duration
from src.notifications.telegram import telegram_flow_state_handlers
from src.tracking.recorder import tracking_recorder


def _resolve_sqlalchemy_engine(init_ctrl: InitiativeController) -> Engine:
    """Resolve the SQLAlchemy engine across eo-lib client variants."""
    session = None
    try:
        session = init_ctrl._service._repository._session
    except Exception:
        session = None

    if session is not None:
        try:
            bind = session.get_bind()
            if bind is not None:
                return bind
        except Exception:
            pass

    client = getattr(init_ctrl, "client", None)
    for attr in ("engine", "_engine"):
        engine = getattr(client, attr, None)
        if engine is not None:
            return engine

    from eo_lib.infrastructure.database.postgres_client import PostgresClient

    repo = PostgresClient()
    for attr in ("engine", "_engine"):
        engine = getattr(repo, attr, None)
        if engine is not None:
            return engine

    raise RuntimeError("Could not resolve SQLAlchemy engine for Lattes ingestion")


def _expire_lattes_sessions(session):
    """Release ORM identity-map references after each ingested CV file.

    Keeps peak memory bounded across the 125-file loop. Ignores sessions that
    cannot be expired so a partial ingest never aborts the phase.
    """
    for candidate in (session,):
        if candidate is None:
            continue
        try:
            candidate.expire_all()
        except Exception:
            pass


def _hydrate_researcher(researcher_ctrl: ResearcherController, match):
    """Carrega a entidade completa do vencedor da correspondência.

    O índice devolve um registro leve, suficiente para decidir de quem é o
    currículo. Daí para a frente a ingestão grava atributos, persiste e vincula
    — para isso precisa da entidade, e apenas dela: um registro por currículo,
    não os 1060 do cadastro.
    """
    if not isinstance(match, ResearcherRef):
        return match  # caminho de criação: já veio entidade

    try:
        return researcher_ctrl.get_by_id(match.id)
    except Exception as exc:
        logger.warning(f"Could not load researcher {match.id}: {exc}")
        return None


def _ingest_researcher_file(
    file_path: str,
    entity_manager: EntityManager,
    parser: LattesParser,
    researcher_index: List[ResearcherRef],
    project_loader: "ProjectLoader",
    data: Optional[dict] = None,
):
    try:
        filename = os.path.basename(file_path)
        lattes_id = filename.replace(".json", "").split("_")[-1]

        if not lattes_id or not lattes_id.isdigit():
            logger.info(f"Skipping file {filename}: Could not extract Lattes ID.")
            return

        if data is None:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load JSON {file_path}: {e}")
                return

        personal_info = parser.parse_personal_info(data)

        json_name = data.get("nome") or data.get("name")
        if not json_name:
            info = data.get("informacoes_pessoais", {})
            json_name = info.get("nome_completo")
        json_name = personal_info.get("name") or json_name

        researcher_ctrl = ResearcherController()
        # O índice chega pronto do flow. Reconstruí-lo aqui custaria 7,8 s por
        # currículo — 875 s por execução — para devolver sempre a mesma lista.
        all_researchers = researcher_index
        session = None
        try:
            session = researcher_ctrl._service._repository._session
        except Exception:
            pass

        match = resolve_researcher_from_lattes(
            all_researchers,
            lattes_id=lattes_id,
            json_name=json_name,
            session=session,
        )

        if not match:
            # identification_id is a CPF-like column (LGPD-hashed on write);
            # a hashed lattes_id there never matches raw lookups. The stable
            # Lattes identity lives in cnpq_url, set right below.
            match = resolve_or_create_researcher(
                researcher_ctrl,
                all_researchers,
                name=json_name,
            )
        if not match:
            raise RuntimeError(
                f"Unable to resolve or create researcher for Lattes ID {lattes_id}."
            )

        target_researcher = _hydrate_researcher(researcher_ctrl, match)
        if not target_researcher:
            raise RuntimeError(
                f"Unable to load researcher entity for Lattes ID {lattes_id}."
            )
        # The CV's own subject (spec 021): left out of the total-loss count.
        carry("researcher", target_researcher.id, is_subject=True)

        # Guarantee the Lattes URL identity so future runs resolve by cnpq_url.
        if lattes_id and not personal_info.get("cnpq_url"):
            personal_info["cnpq_url"] = f"http://lattes.cnpq.br/{lattes_id}"

        # 1. Update Personal Info
        if personal_info.get("resume"):
            # LGPD: the resume is free text that can embed personal e-mails
            # and phone numbers. Scrub it before persisting, so the column,
            # the tracking payloads and the change log never carry raw PII.
            personal_info["resume"] = scrub_pii_deep(personal_info["resume"])
        profile_fields = ("citation_names", "cnpq_url", "resume")
        # Only the fields whose stored value really differs are written and
        # logged (spec 020, FR-022): a rerun over the same CV changes nothing.
        before = {f: getattr(target_researcher, f, None) for f in profile_fields}
        changed = [
            f
            for f in profile_fields
            if personal_info.get(f)
            and canonical(personal_info[f]) != canonical(before[f])
        ]

        if any(personal_info.get(f) for f in profile_fields):
            try:
                for field in changed:
                    setattr(target_researcher, field, personal_info[field])
                if changed:
                    researcher_ctrl.update(target_researcher)
                source_record = tracking_recorder.record_source_record(
                    source_entity_type="researcher_profile",
                    payload=personal_info,
                    source_record_id=lattes_id,
                    source_file=file_path,
                    source_path=file_path,
                )
                tracking_recorder.record_entity_match(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="researcher",
                    canonical_entity_id=target_researcher.id,
                    match_strategy="lattes_id_exact",
                    match_confidence=1.0,
                )
                tracking_recorder.record_attribute_assertions(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="researcher",
                    canonical_entity_id=target_researcher.id,
                    selected_attributes={
                        "citation_names": personal_info.get("citation_names"),
                        "cnpq_url": personal_info.get("cnpq_url"),
                        "resume": personal_info.get("resume"),
                    },
                    selection_reason="lattes_personal_info_selected_values",
                )
                if changed:
                    tracking_recorder.record_change(
                        source_record_id=getattr(source_record, "id", None),
                        canonical_entity_type="researcher",
                        canonical_entity_id=target_researcher.id,
                        operation="update",
                        changed_fields=changed,
                        before={f: before[f] for f in changed},
                        after={f: personal_info.get(f) for f in changed},
                        reason="Updated from Lattes personal info",
                    )
            except Exception as e:
                logger.warning(f"Failed to update researcher data for {lattes_id}: {e}")
                mark_partial(f"personal info: {e}")

        # O índice é lido uma vez só, então precisa acompanhar o que esta
        # ingestão acabou de gravar — currículos seguintes pontuam sobre ele.
        sync_researcher_ref(all_researchers, target_researcher)

        logger.info(
            f"Processing data for researcher: {target_researcher.name} (Lattes: {lattes_id})"
        )

        # 2. Extract Projects
        projects = []
        projects.extend(parser.parse_research_projects(data))
        projects.extend(parser.parse_extension_projects(data))
        projects.extend(parser.parse_development_projects(data))

        # Deduplicate projects by normalized name. A project entered twice in
        # the same CV is processed once, always the same version (spec 020,
        # FR-020): the one with the smallest canonical hash.
        for p in projects:
            p["name"] = (p.get("name") or "").strip()
        unique_projects, dropped = dedupe_same_document(
            [p for p in projects if p["name"]],
            lambda p: normalize_text(p["name"]),
        )
        if dropped:
            logger.info(f"Dropped {dropped} duplicate projects in {filename}")

        if unique_projects:
            logger.info(
                f"Ingesting {len(unique_projects)} projects with ProjectLoader for {target_researcher.name}"
            )
            # Identify researcher roles prior to loading
            researcher_roles = {p["name"]: p.get("role") for p in unique_projects}

            mapping_strategy = LattesProjectMappingStrategy(
                target_researcher.name, researcher_roles
            )
            project_loader.mapping_strategy = mapping_strategy

            project_loader.process_records(unique_projects, source_file=file_path)

        # 3. Handle Articles
        articles = []
        articles.extend(parser.parse_articles(data))
        articles.extend(parser.parse_conference_papers(data))
        articles, dropped = dedupe_same_document(
            articles, lambda art: lattes_article_key(file_path, art)
        )
        if dropped:
            logger.info(f"Dropped {dropped} duplicate articles in {filename}")
        if articles:
            ingest_articles_task(
                articles, target_researcher, all_researchers, parser, file_path
            )

        # 4. Handle Academic Education
        education_list, dropped = dedupe_same_document(
            parser.parse_academic_education(data),
            lambda edu: lattes_education_key(file_path, edu),
        )
        if dropped:
            logger.info(f"Dropped {dropped} duplicate educations in {filename}")
        if education_list:
            ingest_education_task(
                education_list,
                target_researcher,
                all_researchers,
                entity_manager,
                researcher_ctrl,
                file_path,
            )

        # 5. Awards, languages, professional activities, technical productions.
        # Idempotent: each is deduped by natural key so re-runs don't duplicate.
        # Each section is isolated so one failure never aborts the others.
        for section_name, parse_fn, ingest_fn in (
            ("awards", parser.parse_awards, ingest_awards_task),
            ("languages", parser.parse_languages, ingest_languages_task),
            (
                "professional_activities",
                parser.parse_professional_activities,
                ingest_professional_activities_task,
            ),
            (
                "technical_productions",
                parser.parse_technical_productions,
                ingest_technical_productions_task,
            ),
        ):
            try:
                items = parse_fn(data)
                if items:
                    ingest_fn(items, target_researcher, session)
            except Exception as exc:
                logger.warning(
                    f"Failed to ingest {section_name} for {target_researcher.name}: {exc}"
                )
                mark_partial(f"{section_name}: {exc}")

    except Exception as e:
        logger.error(f"Failed to process file {file_path}: {e}")
        if current() is not None:
            # Inside a document (spec 021) the CV is rolled back whole.
            raise DocumentFailed("partial", f"{type(e).__name__}: {e}") from e


@task(name="Ingest Lattes Researcher Data", cache_policy=NO_CACHE)
def ingest_researcher_data(
    file_path: str,
    entity_manager: EntityManager,
    parser: LattesParser,
    researcher_index: List[ResearcherRef],
    project_loader: "ProjectLoader",
    data: Optional[dict] = None,
):
    _ingest_researcher_file(
        file_path, entity_manager, parser, researcher_index, project_loader, data
    )


@task(name="Ingest Lattes Researcher File", cache_policy=NO_CACHE)
def ingest_file_task(file_path: str, entity_manager: EntityManager):
    """Compatibility wrapper kept for scripts/tests that still call this symbol.

    Builds its own index because it is invoked for a single file, outside the
    flow that would otherwise provide one.
    """
    parser = LattesParser()
    session = None
    try:
        session = ResearcherController()._service._repository._session
    except Exception:
        pass
    from src.core.logic.project_loader import ProjectLoader

    project_loader = ProjectLoader(mapping_strategy=None)
    _ingest_researcher_file(
        file_path,
        entity_manager,
        parser,
        load_researcher_index(session),
        project_loader,
    )


# Filled on an existing article when it has no value and a CV gives one.
_ARTICLE_FILL_FIELDS = ("doi", "journal_conference", "volume", "pages")


def _fill_missing_article_fields(session, paper_id, art, source_record_id) -> None:
    """The same work listed in several CVs: an empty field of the stored
    article takes the value of a later CV, never overwriting one. Without it
    the result depended on which CV came first (spec 020: the DOI of 8
    articles was lost when the CVs were processed in a fixed order)."""
    row = session.execute(
        text(
            "SELECT doi, journal_conference, volume, pages FROM articles "
            "WHERE id = :id"
        ),
        {"id": paper_id},
    ).fetchone()
    if row is None:
        return
    current = dict(zip(_ARTICLE_FILL_FIELDS, row))
    filled = {
        field: art.get(field)
        for field in _ARTICLE_FILL_FIELDS
        if canonical(current[field]) is None and canonical(art.get(field)) is not None
    }
    if not filled:
        return
    session.execute(
        text(
            "UPDATE articles SET "
            + ", ".join(f"{field} = :{field}" for field in filled)
            + " WHERE id = :id"
        ),
        {**filled, "id": paper_id},
    )
    session.commit()
    tracking_recorder.record_change(
        source_record_id=source_record_id,
        canonical_entity_type="article",
        canonical_entity_id=paper_id,
        operation="update",
        changed_fields=sorted(filled),
        before={field: current[field] for field in filled},
        after=filled,
        reason="Filled missing article fields from Lattes",
    )


def ingest_articles_task(
    articles: List[Dict],
    target_researcher: Researcher,
    all_researchers: List[ResearcherRef],
    parser: LattesParser,
    source_file: str,
):
    logger.info(f"Processing {len(articles)} articles for {target_researcher.name}...")
    article_ctrl = ArticleController()
    session = article_ctrl._service._repository._session

    for art in articles:
        try:
            title = art["title"]
            year = art["year"]
            doi = art.get("doi")
            source_record = tracking_recorder.record_source_record(
                source_entity_type="article",
                payload=art,
                # Source-native key (spec 020): the CV it came from plus the
                # fields that tell two works apart.
                source_record_id=lattes_article_key(source_file, art),
                source_file=source_file,
                source_path=source_file,
            )

            # Column-only lookups. The Article.authors relationship is
            # lazy="joined" and Researcher carries several more lazy="joined"
            # relationships, so an ORM query collapses into a combinatorial
            # LEFT OUTER JOIN that crashes native psycopg2/libpq with SIGSEGV
            # on PostgreSQL (see export_canonical for the same root cause).
            # Fetch only the row id so the author graph is never materialized.
            paper_id = None
            if doi:
                paper_id = session.execute(
                    text("SELECT id FROM articles WHERE doi = :doi LIMIT 1"),
                    {"doi": doi},
                ).scalar()
            if paper_id is None:
                paper_id = session.execute(
                    text(
                        "SELECT id FROM articles "
                        "WHERE title = :t AND year = :y LIMIT 1"
                    ),
                    {"t": title, "y": year},
                ).scalar()

            if paper_id is None:
                paper = article_ctrl.create_article(
                    title=title,
                    year=year,
                    type=art["type"],
                    doi=doi,
                    journal_conference=art.get("journal_conference"),
                    volume=art.get("volume"),
                    pages=art.get("pages"),
                )
                paper_id = paper.id
                tracking_recorder.record_change(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="article",
                    canonical_entity_id=paper_id,
                    operation="create",
                    changed_fields=[
                        "title",
                        "year",
                        "doi",
                        "journal_conference",
                        "volume",
                        "pages",
                    ],
                    after={
                        "title": title,
                        "year": year,
                        "doi": doi,
                        "journal_conference": art.get("journal_conference"),
                        "volume": art.get("volume"),
                        "pages": art.get("pages"),
                    },
                    reason="Created article from Lattes",
                )
            else:
                _fill_missing_article_fields(
                    session, paper_id, art, getattr(source_record, "id", None)
                )

            tracking_recorder.record_entity_match(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type="article",
                canonical_entity_id=paper_id,
                match_strategy="doi_exact" if doi else "title_year",
                match_confidence=1.0 if doi else 0.8,
            )
            tracking_recorder.record_attribute_assertions(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type="article",
                canonical_entity_id=paper_id,
                selected_attributes={
                    "title": title,
                    "year": year,
                    "doi": doi,
                    "journal_conference": art.get("journal_conference"),
                    "volume": art.get("volume"),
                    "pages": art.get("pages"),
                },
                selection_reason="lattes_article_selected_values",
            )

            # Link primary author via the association table, never the ORM
            # graph (which would rebuild the crashing joined query).
            already_linked = session.execute(
                text(
                    "SELECT 1 FROM article_authors "
                    "WHERE article_id = :a AND researcher_id = :r LIMIT 1"
                ),
                {"a": paper_id, "r": target_researcher.id},
            ).scalar()
            carry("article_author", f"{paper_id}:{target_researcher.id}")
            if not already_linked:
                try:
                    session.execute(
                        text(
                            "INSERT INTO article_authors (article_id, researcher_id) "
                            "VALUES (:a, :r)"
                        ),
                        {"a": paper_id, "r": target_researcher.id},
                    )
                    session.commit()
                except Exception as link_err:
                    session.rollback()
                    logger.warning(
                        f"Failed to link article '{title}' to researcher {target_researcher.id}: {link_err}"
                    )
                    mark_partial(f"article link: {link_err}")

        except Exception as art_err:
            logger.error(f"Failed to ingest article {art.get('title')}: {art_err}")
            mark_partial(f"article: {art_err}")


def ingest_education_task(
    education_list: List[Dict],
    target_researcher: Researcher,
    all_researchers: List[ResearcherRef],
    entity_manager: EntityManager,
    researcher_ctrl: ResearcherController,
    source_file: str,
):
    logger.info(
        f"Processing {len(education_list)} education entries for {target_researcher.name}..."
    )
    session = researcher_ctrl._service._repository._session

    for edu_data in education_list:
        try:
            source_record = tracking_recorder.record_source_record(
                source_entity_type="academic_education",
                payload=edu_data,
                # The CV's lattes_id, never researchers.id: a person merge
                # must not make the same education look new (spec 020).
                source_record_id=lattes_education_key(source_file, edu_data),
                source_file=source_file,
                source_path=source_file,
            )
            inst_name = edu_data.get("institution") or "Unknown Institution"
            org_id = entity_manager.ensure_organization(name=inst_name)
            if not org_id:
                continue

            type_name = edu_data.get("degree") or "Unknown"
            type_id = entity_manager.ensure_education_type(name=type_name)
            if not type_id:
                continue

            advisor_id = None
            co_advisor_id = None
            description = edu_data.get("description", "")

            if description:
                adv_match = re.search(
                    r"Orientador:\s*([^.;)]+)", description, re.IGNORECASE
                )
                if adv_match:
                    adv_name = adv_match.group(1).strip()
                    adv_res = resolve_or_create_researcher(
                        researcher_ctrl,
                        all_researchers,
                        name=adv_name,
                    )
                    if adv_res:
                        advisor_id = getattr(adv_res, "id")

                co_match = re.search(
                    r"Co-?orientador:\s*([^.;)]+)", description, re.IGNORECASE
                )
                if co_match:
                    co_name = co_match.group(1).strip()
                    co_res = resolve_or_create_researcher(
                        researcher_ctrl,
                        all_researchers,
                        name=co_name,
                    )
                    if co_res:
                        co_advisor_id = getattr(co_res, "id")

            start_val = edu_data.get("start_year") or 0
            title = edu_data.get("course_name") or "Untitled"
            thesis_title = edu_data.get("thesis_title")
            end_year = edu_data.get("end_year")

            existing = session.execute(
                text(
                    """
                    SELECT id
                    FROM academic_educations
                    WHERE researcher_id = :researcher_id
                      AND education_type_id = :education_type_id
                      AND institution_id = :institution_id
                      AND title = :title
                      AND start_year = :start_year
                      AND (
                        (end_year IS NULL AND :end_year IS NULL)
                        OR end_year = :end_year
                      )
                      AND (
                        (thesis_title IS NULL AND :thesis_title IS NULL)
                        OR thesis_title = :thesis_title
                      )
                    LIMIT 1
                    """
                ),
                {
                    "researcher_id": target_researcher.id,
                    "education_type_id": type_id,
                    "institution_id": org_id,
                    "title": title,
                    "start_year": start_val,
                    "end_year": end_year,
                    "thesis_title": thesis_title,
                },
            ).fetchone()
            if existing:
                tracking_recorder.record_entity_match(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="academic_education",
                    canonical_entity_id=existing[0],
                    match_strategy="natural_key_exact",
                    match_confidence=1.0,
                )
                continue

            education = (
                entity_manager.academic_edu_controller.create_academic_education(
                    researcher_id=target_researcher.id,
                    education_type_id=type_id,
                    title=title,
                    institution_id=org_id,
                    start_year=start_val,
                    end_year=end_year,
                    thesis_title=thesis_title,
                    advisor_id=advisor_id,
                    co_advisor_id=co_advisor_id,
                )
            )
            tracking_recorder.record_entity_match(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type="academic_education",
                canonical_entity_id=education.id,
                match_strategy="natural_key_exact",
                match_confidence=1.0,
            )
            tracking_recorder.record_attribute_assertions(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type="academic_education",
                canonical_entity_id=education.id,
                selected_attributes={
                    "institution": inst_name,
                    "degree": type_name,
                    "title": title,
                    "start_year": start_val,
                    "end_year": end_year,
                    "thesis_title": thesis_title,
                    "advisor_id": advisor_id,
                    "co_advisor_id": co_advisor_id,
                },
                selection_reason="lattes_education_selected_values",
            )
            tracking_recorder.record_change(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type="academic_education",
                canonical_entity_id=education.id,
                operation="create",
                changed_fields=[
                    "institution",
                    "degree",
                    "title",
                    "start_year",
                    "end_year",
                    "thesis_title",
                    "advisor_id",
                    "co_advisor_id",
                ],
                after={
                    "institution": inst_name,
                    "degree": type_name,
                    "title": title,
                    "start_year": start_val,
                    "end_year": end_year,
                    "thesis_title": thesis_title,
                    "advisor_id": advisor_id,
                    "co_advisor_id": co_advisor_id,
                },
                reason="Created academic education from Lattes",
            )
        except Exception as e:
            logger.warning(f"Failed to ingest education item: {e}")
            mark_partial(f"education: {e}")


def ingest_awards_task(awards, target_researcher, session):
    """Ingests Lattes awards (premios_titulos) into the `awards` table.

    No controller exists for awards, so rows are written via the ORM.
    Deduped by (researcher_id, title, year).
    """
    if session is None:
        logger.warning(
            f"No DB session available; skipping {len(awards)} awards for {target_researcher.name}"
        )
        mark_partial("awards: no DB session")
        return
    from research_domain.domain.entities.award import Award

    created = 0
    kept = []
    for a in awards:
        title, year = a["title"], a.get("year")
        exists = (
            session.query(Award)
            .filter_by(researcher_id=target_researcher.id, title=title, year=year)
            .first()
        )
        if exists:
            kept.append(exists)
            continue
        award = Award(researcher_id=target_researcher.id, title=title, year=year)
        session.add(award)
        kept.append(award)
        created += 1
    if created:
        session.commit()
    for award in kept:  # spec 021: the rows this CV carries
        carry("award", award.id)
    logger.info(f"Awards: {created} created for {target_researcher.name}")


def _proficiency_level(value):
    """Maps a Lattes proficiency word to the ProficiencyLevel enum.

    Lattes scale: Bem / Razoavelmente / Pouco / Nenhum (or empty).
    """
    from research_domain.domain.entities.proficiency import ProficiencyLevel

    key = (value or "").strip().lower()
    return {
        "bem": ProficiencyLevel.ALTO,
        "razoavelmente": ProficiencyLevel.MEDIO,
        "pouco": ProficiencyLevel.BASICO,
    }.get(key, ProficiencyLevel.NAO_SE_APLICA)


def ingest_languages_task(languages, target_researcher, session):
    """Ingests Lattes languages (idiomas) into `languages` + `proficiencies`.

    Language is get-or-created by name; proficiency deduped by
    (researcher_id, language_id).
    """
    if session is None:
        logger.warning(
            f"No DB session available; skipping {len(languages)} languages for {target_researcher.name}"
        )
        mark_partial("languages: no DB session")
        return
    from research_domain.domain.entities.language import Language
    from research_domain.domain.entities.proficiency import (
        Proficiency,
        ProficiencyLevel,
    )

    created = 0
    kept = []
    for lg in languages:
        name = lg["language"]
        language = session.query(Language).filter_by(name=name).first()
        if not language:
            language = Language(name=name)
            session.add(language)
            session.flush()
        exists = (
            session.query(Proficiency)
            .filter_by(researcher_id=target_researcher.id, language_id=language.id)
            .first()
        )
        if exists:
            kept.append(exists)
            continue
        proficiency = Proficiency(
            researcher_id=target_researcher.id,
            language_id=language.id,
            comprehension=_proficiency_level(lg.get("comprehension")),
            speaking=_proficiency_level(lg.get("speaking")),
            reading=_proficiency_level(lg.get("reading")),
            writing=_proficiency_level(lg.get("writing")),
        )
        session.add(proficiency)
        kept.append(proficiency)
        created += 1
    if created:
        session.commit()
    for proficiency in kept:  # spec 021: the rows this CV carries
        carry("proficiency", proficiency.id)
    logger.info(f"Proficiencies: {created} created for {target_researcher.name}")


def ingest_professional_activities_task(activities, target_researcher, session):
    """Ingests Lattes professional activities (atuacao_profissional).

    Deduped by (researcher_id, institution, start_year, activity_type).
    """
    ctrl = ProfessionalActivityController()
    seen = {}  # natural key -> row id
    if session is not None:
        from research_domain.domain.entities.professional_activity import (
            ProfessionalActivity,
        )

        for e in (
            session.query(ProfessionalActivity)
            .filter_by(researcher_id=target_researcher.id)
            .all()
        ):
            seen[(e.institution, e.start_year, e.activity_type)] = e.id

    created = 0
    for act in activities:
        key = (act["institution"], act["start_year"], act["activity_type"])
        if key in seen:
            carry("professional_activity", seen[key])
            continue
        try:
            activity = ctrl.create_professional_activity(
                researcher_id=target_researcher.id, **act
            )
            seen[key] = getattr(activity, "id", None)
            carry("professional_activity", seen[key])
            created += 1
        except Exception as e:
            logger.warning(f"Failed to ingest professional activity: {e}")
            mark_partial(f"professional activity: {e}")
    logger.info(
        f"Professional activities: {created} created for {target_researcher.name}"
    )


def ingest_technical_productions_task(productions, target_researcher, session):
    """Ingests Lattes technical/patent productions (producao_tecnica,
    patentes_registros) into `research_productions`.

    Production type is get-or-created by category name; production deduped by
    (title, year, production_type_id) for this researcher.
    """
    type_ctrl = ProductionTypeController()
    prod_ctrl = ResearchProductionController()

    type_cache = {}
    for t in type_ctrl.get_all():
        name = getattr(t, "name", None)
        if name:
            type_cache[name] = t.id

    created = 0
    for prod in productions:
        title = prod["title"]
        year = prod.get("year")
        category = prod["production_type"]

        type_id = type_cache.get(category)
        if type_id is None:
            try:
                pt = type_ctrl.create_production_type(name=category)
                type_id = pt.id
                type_cache[category] = type_id
            except Exception as e:
                logger.warning(f"Failed to ensure production type '{category}': {e}")
                mark_partial(f"production type: {e}")
                continue

        existing_id = None
        if session is not None:
            # Column-only lookup. ResearchProduction.authors is lazy="joined"
            # and Researcher carries several more lazy="joined" relationships,
            # so an ORM query collapses into a combinatorial LEFT OUTER JOIN
            # that crashes native psycopg2/libpq with SIGSEGV on PostgreSQL
            # (same root cause as Article.authors in the articles task). Fetch
            # only the row id so the author graph is never materialized.
            existing_id = session.execute(
                text(
                    "SELECT id FROM research_productions "
                    "WHERE title = :t AND year = :y AND production_type_id = :pti "
                    "LIMIT 1"
                ),
                {"t": title, "y": year, "pti": type_id},
            ).scalar()

        try:
            if existing_id is None:
                production = prod_ctrl.create_production(
                    title=title, year=year, production_type_id=type_id
                )
                existing_id = production.id
                created += 1
            carry("research_production", existing_id)
            carry("production_author", f"{existing_id}:{target_researcher.id}")
            already_linked = session.execute(
                text(
                    "SELECT 1 FROM production_authors "
                    "WHERE production_id = :p AND researcher_id = :r LIMIT 1"
                ),
                {"p": existing_id, "r": target_researcher.id},
            ).scalar()
            if not already_linked:
                session.execute(
                    text(
                        "INSERT INTO production_authors (production_id, researcher_id) "
                        "VALUES (:p, :r)"
                    ),
                    {"p": existing_id, "r": target_researcher.id},
                )
                session.commit()
        except Exception as e:
            session.rollback()
            logger.warning(f"Failed to ingest technical production '{title}': {e}")
            mark_partial(f"technical production: {e}")
    logger.info(
        f"Technical productions: {created} created for {target_researcher.name}"
    )


@flow(name="Ingest Lattes Projects Flow", **telegram_flow_state_handlers())
def ingest_lattes_projects_flow():
    base_dir = "data/lattes_json"
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(os.getcwd(), base_dir)

    # Sorted: name matching depends on who already exists, so the order must
    # not depend on the filesystem (spec 020, FR-002).
    json_files = sorted(glob.glob(os.path.join(base_dir, "*.json")))
    logger.info(f"Found {len(json_files)} files in {base_dir}")

    if not json_files:
        return

    # Opened before any controller: their sessions must bind to the shared
    # connection of the document transactions (spec 021).
    with document_phase("lattes_projects") as skip:
        _ingest_lattes_projects(json_files, skip)


def _ingest_lattes_projects(json_files: List[str], skip) -> None:
    init_ctrl = InitiativeController()
    person_ctrl = PersonController()
    entity_manager = EntityManager(init_ctrl, person_ctrl)
    parser = LattesParser()

    from eo_lib.domain.base import Base

    engine = _resolve_sqlalchemy_engine(init_ctrl)

    # Ingestion is idempotent (articles dedup by DOI/title+year, educations by
    # natural key), so tables are never dropped here: a partial run must not
    # destroy data ingested for researchers whose JSONs are absent from disk.
    Base.metadata.create_all(engine)

    # Uma leitura do cadastro por execução da fase, não por currículo.
    session = None
    try:
        session = ResearcherController()._service._repository._session
    except Exception:
        logger.warning("Could not reach the DB session; researcher index is empty.")
    researcher_index = load_researcher_index(session)
    logger.info(f"Researcher index loaded with {len(researcher_index)} entries")

    # Build each record's own mapping strategy per file, but reuse ONE
    # ProjectLoader across all files: building it per CV reloads the full
    # initiative + person tables each time (4449 initiatives / 4660 persons),
    # spiking a single heavy file's peak well past runner limits.
    from src.core.logic.project_loader import ProjectLoader

    project_loader = ProjectLoader(mapping_strategy=None)
    # One net change log for the whole phase (spec 020): a project listed in
    # several CVs is logged once, by its real difference.
    project_loader.defer_change_log = True

    def reload_caches():
        # A rolled-back CV may have created researchers, initiatives, persons
        # or teams that the in-memory indexes still point at (spec 021).
        researcher_index[:] = load_researcher_index(session)
        project_loader.reset_caches()

    skip.on_rollback = reload_caches

    with tracking_recorder.run_context(
        source_system="lattes_projects", flow_name="lattes_projects"
    ):
        for position, json_file in enumerate(json_files, start=1):
            started = time.perf_counter()
            key = lattes_id_from_cv_path(json_file) or os.path.basename(json_file)
            with skip.document(key) as doc:
                data = read_cv(json_file)
                if doc.unchanged(data):
                    continue
                doc.begin()
                # quote(): Prefect would otherwise walk these large objects
                # (the ~7.6k-entry researcher index above all) on every call.
                ingest_researcher_data(
                    json_file,
                    quote(entity_manager),
                    quote(parser),
                    quote(researcher_index),
                    quote(project_loader),
                    quote(data),
                )
            # The ORM sessions accumulate every entity created for all 125 CV
            # files in their identity maps; merely committing (done inside the
            # ingest helpers) does not release those references. Expire them
            # after each file so memory is bounded to one researcher at a time,
            # otherwise private-runners OOM (+ signal 11) near the end of the
            # loop. gc.collect() alone cannot reclaim identity-map-held objects.
            _expire_lattes_sessions(session)
            gc.collect()
            log_cv_duration(
                "lattes_projects", position, len(json_files), json_file, started
            )
        project_loader.flush_change_log()
        finish_lattes_listing(skip, json_files)
    project_loader.team_synchronizer.log_lookup_summary("lattes_projects")
    project_loader.person_matcher.log_match_summary("lattes_projects")
    log_researcher_resolution_summary("lattes_projects")


if __name__ == "__main__":
    ingest_lattes_projects_flow()
