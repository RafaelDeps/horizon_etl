import faulthandler
import gc
import glob
import json
import os
import re
from typing import Any, Dict, List

faulthandler.enable()

from eo_lib import InitiativeController, PersonController, TeamController
from loguru import logger
from prefect import flow, task
from prefect.cache_policies import NO_CACHE
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
from src.core.logic.entity_manager import EntityManager
from src.core.logic.project_loader import ProjectLoader
from src.core.logic.researcher_resolution import (
    ResearcherRef,
    load_researcher_index,
    resolve_or_create_researcher,
    resolve_researcher_from_lattes,
    sync_researcher_ref,
)
from src.core.logic.strategies.lattes_projects import LattesProjectMappingStrategy
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
):
    try:
        filename = os.path.basename(file_path)
        lattes_id = filename.replace(".json", "").split("_")[-1]

        if not lattes_id or not lattes_id.isdigit():
            logger.info(f"Skipping file {filename}: Could not extract Lattes ID.")
            return

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

        # Guarantee the Lattes URL identity so future runs resolve by cnpq_url.
        if lattes_id and not personal_info.get("cnpq_url"):
            personal_info["cnpq_url"] = f"http://lattes.cnpq.br/{lattes_id}"

        # 1. Update Personal Info
        needs_update = False
        if personal_info.get("citation_names"):
            target_researcher.citation_names = personal_info["citation_names"]
            needs_update = True
        if personal_info.get("cnpq_url"):
            target_researcher.cnpq_url = personal_info["cnpq_url"]
            needs_update = True
        if personal_info.get("resume"):
            target_researcher.resume = personal_info["resume"]
            needs_update = True

        if needs_update:
            try:
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
                tracking_recorder.record_change(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="researcher",
                    canonical_entity_id=target_researcher.id,
                    operation="update",
                    changed_fields=[
                        key
                        for key in ("citation_names", "cnpq_url", "resume")
                        if personal_info.get(key)
                    ],
                    after={
                        "citation_names": personal_info.get("citation_names"),
                        "cnpq_url": personal_info.get("cnpq_url"),
                        "resume": personal_info.get("resume"),
                    },
                    reason="Updated from Lattes personal info",
                )
            except Exception as e:
                logger.warning(f"Failed to update researcher data for {lattes_id}: {e}")

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

        # Deduplicate projects by name
        seen_names = set()
        unique_projects = []
        for p in projects:
            p_name = (p.get("name") or "").strip()
            if p_name and p_name not in seen_names:
                p["name"] = p_name
                unique_projects.append(p)
                seen_names.add(p_name)

        if unique_projects:
            logger.info(
                f"Ingesting {len(unique_projects)} projects with ProjectLoader for {target_researcher.name}"
            )
            # Identify researcher roles prior to loading
            researcher_roles = {p["name"]: p.get("role") for p in unique_projects}

            mapping_strategy = LattesProjectMappingStrategy(
                target_researcher.name, researcher_roles
            )
            loader = ProjectLoader(mapping_strategy=mapping_strategy)

            loader.process_records(unique_projects, source_file=file_path)

        # 3. Handle Articles
        articles = []
        articles.extend(parser.parse_articles(data))
        articles.extend(parser.parse_conference_papers(data))
        if articles:
            ingest_articles_task(
                articles, target_researcher, all_researchers, parser, file_path
            )

        # 4. Handle Academic Education
        education_list = parser.parse_academic_education(data)
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

    except Exception as e:
        logger.error(f"Failed to process file {file_path}: {e}")


@task(name="Ingest Lattes Researcher Data", cache_policy=NO_CACHE)
def ingest_researcher_data(
    file_path: str,
    entity_manager: EntityManager,
    parser: LattesParser,
    researcher_index: List[ResearcherRef],
):
    _ingest_researcher_file(file_path, entity_manager, parser, researcher_index)


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
    _ingest_researcher_file(
        file_path, entity_manager, parser, load_researcher_index(session)
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
    researcher_ctrl = ResearcherController()

    for art in articles:
        try:
            title = art["title"]
            year = art["year"]
            doi = art.get("doi")
            source_record = tracking_recorder.record_source_record(
                source_entity_type="article",
                payload=art,
                source_record_id=(doi or f"{parser.normalize_title(title)}|{year}"),
                source_file=source_file,
                source_path=source_file,
            )

            existing_art = None
            if doi:
                existing_art = article_ctrl.get_by_doi(doi)
            if not existing_art:
                existing_art = article_ctrl.get_by_title_year(title, year)

            if existing_art:
                paper = existing_art
            else:
                paper = article_ctrl.create_article(
                    title=title,
                    year=year,
                    type=art["type"],
                    doi=doi,
                    journal_conference=art.get("journal_conference"),
                    volume=art.get("volume"),
                    pages=art.get("pages"),
                )
                tracking_recorder.record_change(
                    source_record_id=getattr(source_record, "id", None),
                    canonical_entity_type="article",
                    canonical_entity_id=paper.id,
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

            tracking_recorder.record_entity_match(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type="article",
                canonical_entity_id=paper.id,
                match_strategy="doi_exact" if doi else "title_year",
                match_confidence=1.0 if doi else 0.8,
            )
            tracking_recorder.record_attribute_assertions(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type="article",
                canonical_entity_id=paper.id,
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

            # Link primary author
            current_author_ids = [
                getattr(auth, "id") for auth in getattr(paper, "authors", [])
            ]
            if target_researcher.id not in current_author_ids:
                try:
                    _attach_article_author(
                        article_ctrl, researcher_ctrl, paper.id, target_researcher.id
                    )
                except Exception as link_err:
                    logger.warning(
                        f"Failed to link article '{title}' to researcher {target_researcher.id}: {link_err}"
                    )

        except Exception as art_err:
            logger.error(f"Failed to ingest article {art.get('title')}: {art_err}")


def _attach_article_author(
    article_ctrl: ArticleController,
    researcher_ctrl: ResearcherController,
    article_id: int,
    researcher_id: int,
) -> None:
    """Attach article author while tolerating controller/service version mismatches."""
    try:
        article_ctrl.add_author(article_id, researcher_id)
        return
    except AttributeError as exc:
        if " has no attribute 'get'" not in str(exc):
            raise

    article = article_ctrl.get_by_id(article_id)
    researcher = researcher_ctrl.get_by_id(researcher_id)
    if not article or not researcher:
        return

    current_author_ids = [
        getattr(author, "id", None) for author in getattr(article, "authors", [])
    ]
    if researcher_id in current_author_ids:
        return

    article.authors.append(researcher)
    article_ctrl.update(article)


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
                source_record_id="|".join(
                    [
                        str(target_researcher.id),
                        str(edu_data.get("course_name") or ""),
                        str(edu_data.get("degree") or ""),
                        str(edu_data.get("start_year") or ""),
                    ]
                ),
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


def ingest_awards_task(awards, target_researcher, session):
    """Ingests Lattes awards (premios_titulos) into the `awards` table.

    No controller exists for awards, so rows are written via the ORM.
    Deduped by (researcher_id, title, year).
    """
    if session is None:
        logger.warning(
            f"No DB session available; skipping {len(awards)} awards for {target_researcher.name}"
        )
        return
    from research_domain.domain.entities.award import Award

    created = 0
    for a in awards:
        title, year = a["title"], a.get("year")
        exists = (
            session.query(Award)
            .filter_by(researcher_id=target_researcher.id, title=title, year=year)
            .first()
        )
        if exists:
            continue
        session.add(Award(researcher_id=target_researcher.id, title=title, year=year))
        created += 1
    if created:
        session.commit()
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
        return
    from research_domain.domain.entities.language import Language
    from research_domain.domain.entities.proficiency import (
        Proficiency,
        ProficiencyLevel,
    )

    created = 0
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
            continue
        session.add(
            Proficiency(
                researcher_id=target_researcher.id,
                language_id=language.id,
                comprehension=_proficiency_level(lg.get("comprehension")),
                speaking=_proficiency_level(lg.get("speaking")),
                reading=_proficiency_level(lg.get("reading")),
                writing=_proficiency_level(lg.get("writing")),
            )
        )
        created += 1
    if created:
        session.commit()
    logger.info(f"Proficiencies: {created} created for {target_researcher.name}")


def ingest_professional_activities_task(activities, target_researcher, session):
    """Ingests Lattes professional activities (atuacao_profissional).

    Deduped by (researcher_id, institution, start_year, activity_type).
    """
    ctrl = ProfessionalActivityController()
    seen = set()
    if session is not None:
        from research_domain.domain.entities.professional_activity import (
            ProfessionalActivity,
        )

        for e in (
            session.query(ProfessionalActivity)
            .filter_by(researcher_id=target_researcher.id)
            .all()
        ):
            seen.add((e.institution, e.start_year, e.activity_type))

    created = 0
    for act in activities:
        key = (act["institution"], act["start_year"], act["activity_type"])
        if key in seen:
            continue
        try:
            ctrl.create_professional_activity(researcher_id=target_researcher.id, **act)
            seen.add(key)
            created += 1
        except Exception as e:
            logger.warning(f"Failed to ingest professional activity: {e}")
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
                continue

        existing_id = None
        if session is not None:
            from research_domain.domain.entities.research_production import (
                ResearchProduction,
            )

            row = (
                session.query(ResearchProduction)
                .filter_by(title=title, year=year, production_type_id=type_id)
                .first()
            )
            existing_id = row.id if row else None

        try:
            if existing_id is None:
                production = prod_ctrl.create_production(
                    title=title, year=year, production_type_id=type_id
                )
                existing_id = production.id
                created += 1
            prod_ctrl.add_author(existing_id, target_researcher.id)
        except Exception as e:
            logger.warning(f"Failed to ingest technical production '{title}': {e}")
    logger.info(
        f"Technical productions: {created} created for {target_researcher.name}"
    )


@flow(name="Ingest Lattes Projects Flow", **telegram_flow_state_handlers())
def ingest_lattes_projects_flow():
    base_dir = "data/lattes_json"
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(os.getcwd(), base_dir)

    json_files = glob.glob(os.path.join(base_dir, "*.json"))
    logger.info(f"Found {len(json_files)} files in {base_dir}")

    if not json_files:
        return

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

    with tracking_recorder.run_context(
        source_system="lattes_projects", flow_name="lattes_projects"
    ):
        for json_file in json_files:
            ingest_researcher_data(json_file, entity_manager, parser, researcher_index)
            gc.collect()


if __name__ == "__main__":
    ingest_lattes_projects_flow()
