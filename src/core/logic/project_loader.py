from typing import Any, Dict, Optional

import pandas as pd
from eo_lib import Initiative, InitiativeController, PersonController, TeamController
from loguru import logger
from research_domain import (
    CampusController,
    KnowledgeAreaController,
    ResearchGroupController,
)

# Workaround: Import directly from controllers module since not exported in __init__
from research_domain.controllers.controllers import (
    AdvisorshipController,
    FellowshipController,
)
from research_domain.domain.entities import Advisorship
from sqlalchemy import text

from src.core.logic.entity_manager import EntityManager
from src.core.logic.initiative_handlers import (
    AdvisorshipHandler,
    StandardProjectHandler,
)
from src.core.logic.initiative_identity import (
    get_existing_initiative_identity,
    normalize_text,
)
from src.core.logic.initiative_linker import InitiativeLinker
from src.core.logic.person_matcher import PersonMatcher
from src.core.logic.strategies.sigpesq_excel import SigPesqCampusStrategy
from src.core.logic.team_synchronizer import TeamSynchronizer
from src.tracking.recorder import tracking_recorder


class ProjectLoader:
    """
    Orchestrates the loading of project initiatives from external sources.
    Delegates specific tasks to specialized handlers, managers, and linkers.
    """

    def __init__(self, mapping_strategy, campus_strategy=None):
        self.mapping_strategy = mapping_strategy
        self.campus_strategy = campus_strategy or SigPesqCampusStrategy()

        # Controllers
        self.controller = InitiativeController()
        self.person_controller = PersonController()
        self.team_controller = TeamController()
        self.rg_controller = ResearchGroupController()
        self.adv_controller = AdvisorshipController()
        self.campus_ctrl = CampusController()

        # O mesmo campus se repete em quase toda linha do relatório; sem cache
        # cada linha faria um get_all() de campi.
        self._campus_cache: Dict[str, Optional[int]] = {}

        # Service/Logic Classes
        self.entity_manager = EntityManager(self.controller, self.person_controller)
        self.person_matcher = PersonMatcher(self.person_controller)

        # Initialize Roles and Cache
        roles_cache = self.entity_manager.ensure_roles()

        self.team_synchronizer = TeamSynchronizer(self.team_controller, roles_cache)

        self.linker = InitiativeLinker(
            initiative_controller=self.controller,
            rg_controller=self.rg_controller,
            team_controller=self.team_controller,
            person_matcher=self.person_matcher,
            team_synchronizer=self.team_synchronizer,
            entity_manager=self.entity_manager,
        )

        # Handlers registry
        self.handlers = {
            Initiative: StandardProjectHandler(self.controller),
            Advisorship: AdvisorshipHandler(
                self.controller, self.person_matcher, self.entity_manager
            ),
        }

        # Ensure base environment
        self.initiative_type = self.entity_manager.ensure_initiative_type(
            "Research Project"
        )
        self.org_id = self.entity_manager.ensure_organization()

    def _resolve_execution_campus_id(self, campus_name: Any) -> Optional[int]:
        """Resolve o campus de execução afirmado pela fonte para um id.

        Nunca levanta: um campus irresolúvel não pode derrubar a ingestão da
        linha (FR-004) — a linha entra sem campus e o nome cru continua
        registrado para auditoria.
        """
        if campus_name is None:
            return None

        try:
            if pd.isna(campus_name):
                return None
        except (TypeError, ValueError):
            pass

        stated = str(campus_name).strip()
        if not stated:
            return None

        cache_key = normalize_text(stated)
        if cache_key in self._campus_cache:
            return self._campus_cache[cache_key]

        campus_id = None
        try:
            campus_id = self.campus_strategy.ensure(
                self.campus_ctrl, stated, self.org_id
            )
        except Exception as exc:
            logger.warning(f"Could not resolve execution campus '{stated}': {exc}")

        self._campus_cache[cache_key] = campus_id
        return campus_id

    def _execution_campus_attrs(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        """Atributos de campus a gravar como assertions para esta linha.

        Independe de a linha ter grupo de pesquisa — é justamente o caso em que
        o campus se perdia antes. Só devolve chaves com valor, para não encher
        `attribute_assertions` de nulos vindos das fontes que não informam
        campus (o Lattes manda `campus_name=None`).
        """
        campus_name = project_data.get("campus_name")
        campus_id = self._resolve_execution_campus_id(campus_name)

        attrs: Dict[str, Any] = {}
        if campus_name is not None and str(campus_name).strip():
            attrs["execution_campus_name"] = str(campus_name).strip()
        if campus_id is not None:
            attrs["execution_campus_id"] = campus_id
        return attrs

    def _tracked_attrs(
        self, title: Any, project_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Valores que a linha afirma, gravados como assertions de auditoria.

        Extraído de `_process_row` para que a ligação com o campus de execução
        seja testável sem montar o loader inteiro — era justamente o trecho em
        que o campus se perdia antes.
        """
        return {
            "name": title,
            "status": project_data.get("status"),
            "description": project_data.get("description"),
            "start_date": project_data.get("start_date"),
            "end_date": project_data.get("end_date"),
            "coordinator_name": project_data.get("coordinator_name"),
            "student_names": project_data.get("student_names"),
            "researcher_names": project_data.get("researcher_names"),
            **self._execution_campus_attrs(project_data),
        }

    def process_file(self, file_path: str) -> None:
        """
        Reads an Excel file and orchestrates the UPSERT logic across handlers and linkers.
        """
        logger.info(f"Processing Projects from: {file_path}")

        try:
            df = pd.read_excel(file_path)
            df = df.fillna("")
        except Exception as e:
            logger.error(f"Failed to read Excel file {file_path}: {e}")
            return

        records = df.to_dict("records")
        self.process_records(records, source_file=file_path)

    def process_records(
        self, records: list[Dict[str, Any]], source_file: Optional[str] = None
    ) -> None:
        """
        Maps a list of raw dictionary records and orchestrates the UPSERT logic across handlers and linkers.
        """
        logger.info("Fetching existing initiatives for UPSERT...")
        existing_initiatives = self.controller.get_all()
        existing_by_name = {
            init.name: init
            for init in existing_initiatives
            if getattr(init, "name", None)
        }
        # Índice por nome normalizado. O índice único do banco usa colação
        # BINARY, então "PROJETO X" e "Projeto X" convivem como linhas
        # diferentes — e era assim que o mesmo projeto entrava duas vezes,
        # vindo do SigPesq numa grafia e do Lattes noutra. Este índice é o
        # único ponto que enxerga as duas como a mesma coisa.
        existing_by_norm_name = {}
        for init in existing_initiatives:
            nome = getattr(init, "name", None)
            if nome:
                existing_by_norm_name.setdefault(normalize_text(nome), init)
        existing_by_identity = {}
        for init in existing_initiatives:
            identity = get_existing_initiative_identity(init)
            if identity:
                existing_by_identity[identity] = init

        self.person_matcher.preload_cache()
        initial_persons_count = len(self.person_matcher._persons_cache)

        # `skipped` era um contador só, somando descarte por regra de negócio e
        # perda por defeito — coisas de natureza oposta. Uma fase que reportava
        # "18 skipped" podia ser 18 projetos legitimamente reprovados ou 18
        # registros perdidos por bug, e não havia como distinguir.
        stats = {
            "created": 0,
            "updated": 0,
            "skipped_not_approved": 0,
            "skipped_no_title": 0,
            "failed": 0,
            "teams": 0,
            "skipped_reasons": {},
        }

        for row_dict in records:
            try:
                self._process_row(
                    row_dict,
                    existing_by_name,
                    existing_by_identity,
                    stats,
                    source_file=source_file,
                    existing_by_norm_name=existing_by_norm_name,
                )
            except Exception as e:
                logger.warning(
                    f"PERDIDO por erro: {self._row_label(row_dict)}"
                    + (f" [{source_file}]" if source_file else "")
                    + f" — {type(e).__name__}: {e}"
                )
                stats["failed"] += 1
                self._rollback_session()

        new_persons_count = (
            len(self.person_matcher._persons_cache) - initial_persons_count
        )
        logger.info(
            f"Ingestion complete: {stats['created']} created, {stats['updated']} updated, "
            f"{stats['skipped_not_approved']} not approved, "
            f"{stats['skipped_no_title']} without title, {stats['failed']} FAILED | "
            f"{stats['teams']} teams, {new_persons_count} new persons"
        )
        if stats["skipped_reasons"]:
            detalhe = ", ".join(
                f"{n}x {motivo}"
                for motivo, n in sorted(stats["skipped_reasons"].items())
            )
            logger.info(f"Descartes por parecer: {detalhe}")
        if stats["failed"]:
            # Registro perdido não é descarte por regra: é defeito, e precisa
            # aparecer num nível que alguém leia.
            logger.error(
                f"{stats['failed']} registro(s) PERDIDO(S) por erro em "
                f"{source_file or 'origem desconhecida'} — veja os warnings acima"
            )
        self.last_stats = dict(stats)

    def recalculate_all_parent_statuses(self) -> None:
        """
        Recalculates start_date, end_date, and status for ALL parent research projects
        based on the persisted advisorships in the database.
        This fixes orphans and ensures consistency across all years.
        """
        logger.info(
            "Recalculating dates and status for all parent projects from Database..."
        )

        from datetime import date, datetime

        from sqlalchemy import text

        session = self.controller._service._repository._session

        # Aggregate dates for all parents that have advisorships
        query = text(
            """
            SELECT 
                i.parent_id,
                MIN(i.start_date) as min_start,
                MAX(i.end_date) as max_end
            FROM advisorships a
            JOIN initiatives i ON a.id = i.id
            WHERE i.parent_id IS NOT NULL
            GROUP BY i.parent_id
        """
        )

        results = session.execute(query).fetchall()

        processed_count = 0
        updated_count = 0

        def ensure_datetime(val):
            if not val:
                return None
            if isinstance(val, (datetime, date)):
                return val
            if isinstance(val, str):
                try:
                    # Attempt generic ISO
                    return datetime.fromisoformat(val)
                except ValueError:
                    pass
                try:
                    # Attempt common SQL format
                    return datetime.strptime(val, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    pass
                try:
                    return datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            return None

        for row in results:
            parent_id = row.parent_id
            min_start = ensure_datetime(row.min_start)
            max_end = ensure_datetime(row.max_end)

            if not parent_id:
                continue

            processed_count += 1

            # Determine status
            status = "Unknown"
            new_status = "Active"
            if max_end:
                # Check if max_end is in the past
                # Ensure max_end is comparable (datetime)
                target_date = max_end
                if hasattr(max_end, "date"):  # datetime object
                    target_date = max_end
                elif isinstance(max_end, str):
                    try:
                        target_date = datetime.fromisoformat(max_end)
                    except:
                        pass

                if isinstance(target_date, datetime):
                    if target_date < datetime.now():
                        new_status = "Concluded"
                elif hasattr(target_date, "year"):  # date object
                    if target_date < datetime.now().date():
                        new_status = "Concluded"

            # Fetch parent initiative to check if update is needed
            parent = self.controller.get_by_id(parent_id)
            if not parent:
                continue

            # Check if any change is needed
            # Note: We need to handle potential None/types mismatch for comparison or just update
            # Since this is a bulk fix operation, we can just update if distinct

            needs_update = False

            # Non-destructive update for start_date: only if earlier than current
            if min_start and (not parent.start_date or min_start < parent.start_date):
                parent.start_date = min_start
                needs_update = True

            # Non-destructive update for end_date: only if later than current
            if max_end and (not parent.end_date or max_end > parent.end_date):
                parent.end_date = max_end
                needs_update = True

            # Recalculate status based on the RESULTING end_date (if it was "Unknown" or "Active/Concluded")
            if parent.end_date:
                # Map Concluded/Active based on time
                # We skip updating status if it's something like "Recusado" or "Salvo"
                if parent.status in ["Unknown", "Active", "Concluded", "Aprovado"]:
                    calculated_status = "Active"
                    if parent.end_date < datetime.now():
                        calculated_status = "Concluded"

                    if parent.status != calculated_status:
                        parent.status = calculated_status
                        needs_update = True

            if needs_update:
                self.controller.update(parent)
                updated_count += 1

        logger.info(
            f"Recalculation complete. Processed {processed_count} parents, updated {updated_count}."
        )

    def _process_row(
        self,
        row_dict: Dict[str, Any],
        existing_by_name: Dict[str, Any],
        existing_by_identity: Dict[str, Any],
        stats: Dict[str, int],
        source_file: Optional[str] = None,
        existing_by_norm_name: Optional[Dict[str, Any]] = None,
    ) -> None:
        existing_by_norm_name = (
            existing_by_norm_name if existing_by_norm_name is not None else {}
        )
        # 1. Map to Dict
        project_data = self.mapping_strategy.map_row(row_dict)

        title = project_data.get("title")
        identity_key = project_data.get("identity_key")
        model_class = project_data.get("model_class", Initiative)
        handler = self.handlers.get(model_class, self.handlers[Initiative])

        # A linhagem é gravada ANTES do portão de aprovação, de propósito: uma
        # linha recusada precisa deixar rastro tanto quanto uma aceita. É esse
        # registro que permite auditar depois o que ficou de fora — e é dele
        # que o enriquecimento por documento descobre quais códigos a diretoria
        # recusou, para não recriá-los pela porta dos fundos.
        source_record = tracking_recorder.record_source_record(
            source_entity_type=(
                "advisorship" if model_class is Advisorship else "initiative"
            ),
            payload=row_dict,
            source_record_id=identity_key or title or self._row_label(row_dict),
            source_file=source_file,
            source_path=source_file,
        )

        # 2. Validation
        approved, parecer = self._approval_status(row_dict)
        if not approved:
            logger.info(
                f"Descartado por parecer '{parecer}': {self._row_label(row_dict)}"
                + (f" [{source_file}]" if source_file else "")
            )
            stats["skipped_not_approved"] += 1
            stats.setdefault("skipped_reasons", {})
            stats["skipped_reasons"][parecer] = (
                stats["skipped_reasons"].get(parecer, 0) + 1
            )
            return
        if not title:
            logger.info(f"Descartado por falta de título: {self._row_label(row_dict)}")
            stats["skipped_no_title"] += 1
            return

        # 2.5 Parent Initiative Handling
        parent_id = None
        parent_initiative = None
        parent_title = project_data.get("parent_title")
        if parent_title:
            parent_identity = project_data.get("parent_identity_key")
            parent_initiative = self._resolve_existing_initiative(
                existing_by_name=existing_by_name,
                existing_by_identity=existing_by_identity,
                model_class=Initiative,
                identity_key=parent_identity,
                title=parent_title,
                existing_by_norm_name=existing_by_norm_name,
            )

            if not parent_initiative:
                # Create parent via Standard Handler
                logger.info(f"Creating parent Research Project: {parent_title}")

                # Ensure we have the "Research Project" type for the parent
                res_proj_type = self.entity_manager.ensure_initiative_type(
                    "Research Project"
                )

                # Initial creation without dates - will be fixed by recalculate_all_parent_statuses
                parent_initiative = self.handlers[Initiative].create_or_update(
                    project_data={
                        "title": parent_title,
                        "status": "Unknown",  # Temporary
                    },
                    existing_initiative=None,
                    initiative_type_name="Research Project",
                    initiative_type_id=res_proj_type.id,
                    organization_id=self.org_id,
                )
                self._register_existing_initiative(
                    existing_by_name=existing_by_name,
                    title=parent_title,
                    initiative=parent_initiative,
                    model_class=Initiative,
                )
                parent_identity_resolved = get_existing_initiative_identity(
                    parent_initiative
                )
                if parent_identity_resolved:
                    existing_by_identity[parent_identity_resolved] = parent_initiative

            parent_id = parent_initiative.id

        # 3. UPSERT Initiative
        existing = self._resolve_existing_initiative(
            existing_by_name=existing_by_name,
            existing_by_identity=existing_by_identity,
            model_class=model_class,
            identity_key=identity_key,
            title=title,
            existing_by_norm_name=existing_by_norm_name,
        )

        # Casou com uma linha cujo nome é o mesmo escrito de outra forma:
        # atualiza o resto, mas NÃO renomeia. Renomear é exatamente o que
        # disparava `UNIQUE constraint failed: initiatives.name` — a linha
        # tentava assumir um nome que outra linha já ocupava — e o registro
        # acabava descartado. O nome já persistido prevalece.
        if existing is not None and title:
            nome_persistido = getattr(existing, "name", None)
            if nome_persistido and nome_persistido != title:
                if normalize_text(nome_persistido) == normalize_text(title):
                    logger.debug(
                        f"Mesma iniciativa com grafia diferente; mantendo "
                        f"'{nome_persistido[:60]}' e ignorando '{title[:60]}'"
                    )
                    title = nome_persistido
                    project_data["title"] = nome_persistido

        initiative = handler.create_or_update(
            project_data=project_data,
            existing_initiative=existing,
            initiative_type_name=self.initiative_type.name,
            initiative_type_id=self.initiative_type.id,
            organization_id=self.org_id,
            parent_id=parent_id,
        )

        if not existing:
            stats["created"] += 1
            if initiative:
                self._register_existing_initiative(
                    existing_by_name=existing_by_name,
                    title=title,
                    initiative=initiative,
                    model_class=model_class,
                )
                nome_novo = getattr(initiative, "name", None)
                if nome_novo:
                    existing_by_norm_name.setdefault(
                        normalize_text(nome_novo), initiative
                    )
                resolved_identity = (
                    get_existing_initiative_identity(initiative) or identity_key
                )
                self._register_identity(
                    existing_by_identity, resolved_identity, initiative
                )
        else:
            stats["updated"] += 1
            if initiative:
                self._register_existing_initiative(
                    existing_by_name=existing_by_name,
                    title=title,
                    initiative=initiative,
                    model_class=model_class,
                )
                nome_novo = getattr(initiative, "name", None)
                if nome_novo:
                    existing_by_norm_name.setdefault(
                        normalize_text(nome_novo), initiative
                    )
                resolved_identity = (
                    get_existing_initiative_identity(initiative) or identity_key
                )
                self._register_identity(
                    existing_by_identity, resolved_identity, initiative
                )

        if initiative:
            canonical_entity_type = (
                "advisorship" if model_class is Advisorship else "initiative"
            )
            tracking_recorder.record_entity_match(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type=canonical_entity_type,
                canonical_entity_id=initiative.id,
                match_strategy="identity_key" if identity_key else "title_fallback",
                match_confidence=1.0 if identity_key else 0.7,
            )
            tracked_attrs = self._tracked_attrs(title, project_data)
            tracking_recorder.record_attribute_assertions(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type=canonical_entity_type,
                canonical_entity_id=initiative.id,
                selected_attributes=tracked_attrs,
                selection_reason="loader_selected_values",
            )
            tracking_recorder.record_change(
                source_record_id=getattr(source_record, "id", None),
                canonical_entity_type=canonical_entity_type,
                canonical_entity_id=initiative.id,
                operation="create" if not existing else "update",
                changed_fields=[
                    key
                    for key, value in tracked_attrs.items()
                    if value not in (None, [], "")
                ],
                before=(
                    {"existing_initiative_id": getattr(existing, "id", None)}
                    if existing
                    else None
                ),
                after={"initiative_id": initiative.id, **tracked_attrs},
                reason=f"{self.mapping_strategy.__class__.__name__} applied",
            )

        # 3.5 Link Advisorship members to Parent Project
        if parent_id and parent_initiative:
            self.linker.add_members_to_initiative_team(parent_initiative, project_data)

        # 4. Linkages
        if initiative:
            # Team synchronization
            self.linker.create_initiative_team(initiative, project_data)
            stats["teams"] += 1

            # Research Group linkage
            rg_name = project_data.get("research_group_name")
            if rg_name and isinstance(rg_name, str) and rg_name.strip():
                self.linker.link_research_group(
                    initiative,
                    rg_name,
                    project_data,
                    project_data.get("campus_name"),
                    self.org_id,
                )

            # Knowledge Areas / Keywords
            self.linker.associate_keyword_knowledge_areas(
                initiative, project_data, rg_name
            )

    def _resolve_existing_initiative(
        self,
        *,
        existing_by_name: Dict[str, Any],
        existing_by_identity: Dict[str, Any],
        model_class,
        identity_key: Optional[str],
        title: Optional[str],
        existing_by_norm_name: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        if identity_key:
            candidate = existing_by_identity.get(identity_key)
            if self._candidate_matches_model(candidate, model_class):
                return candidate

        if title:
            candidate = existing_by_name.get(title)
            if self._candidate_matches_model(candidate, model_class):
                return candidate

        exact = self._lookup_existing_by_exact_name(title, model_class)
        if exact is not None:
            return exact

        # Última tentativa: mesma coisa escrita de outro jeito. Só depois de o
        # exato falhar, para que a grafia idêntica sempre tenha precedência.
        #
        # NÃO vale para orientações, e a diferença é de significado. No projeto,
        # o nome identifica o projeto: "PROJETO X" e "Projeto X" são a mesma
        # coisa e devem virar uma linha só. Na orientação, o nome é o título do
        # TRABALHO, e o mesmo trabalho aparece legitimamente em mais de um
        # currículo — o do orientador e o do coorientador —, cada um trazendo
        # participantes diferentes. Fundir pelo título faz a linha sobrevivente
        # ficar só com os participantes de quem escreveu por último: medido, 100
        # orientações fundidas custaram 200 vínculos, um orientador por fusão.
        # A desambiguação das orientações já é feita pelo AdvisorshipHandler,
        # por aluno, ano e código.
        if model_class is Advisorship:
            return None

        if title and existing_by_norm_name:
            candidate = existing_by_norm_name.get(normalize_text(title))
            if self._candidate_matches_model(candidate, model_class):
                return candidate

        return None

    def _candidate_matches_model(self, candidate: Optional[Any], model_class) -> bool:
        if candidate is None:
            return False

        is_advisorship_candidate = self._is_advisorship_candidate(candidate)
        if model_class is Advisorship:
            return is_advisorship_candidate

        return not is_advisorship_candidate

    def _is_advisorship_candidate(self, candidate: Any) -> bool:
        if isinstance(candidate, Advisorship):
            return True

        candidate_id = getattr(candidate, "id", None)
        if not candidate_id:
            return False

        try:
            return self.adv_controller.get_by_id(candidate_id) is not None
        except Exception:
            return False

    def _lookup_existing_by_exact_name(
        self, title: Optional[str], model_class
    ) -> Optional[Any]:
        if not title:
            return None

        session = self.controller._service._repository._session
        row = session.execute(
            text("SELECT id FROM initiatives WHERE name = :name LIMIT 1"),
            {"name": title},
        ).fetchone()
        if not row:
            return None

        candidate_id = row[0]
        if model_class is Advisorship:
            try:
                return self.adv_controller.get_by_id(candidate_id)
            except Exception:
                return None

        try:
            candidate = self.controller.get_by_id(candidate_id)
        except Exception:
            return None

        if self._is_advisorship_candidate(candidate):
            return None
        return candidate

    @staticmethod
    def _register_identity(
        existing_by_identity: Dict[str, Any], identity: Optional[str], initiative: Any
    ) -> None:
        """Indexa a iniciativa pela identidade, recusando sobrescrever outra.

        Duas linhas distintas sob a mesma chave de identidade é sinal de que a
        chave não identifica o que deveria — foi assim que duas bolsas do mesmo
        plano de trabalho colidiram. Sobrescrever em silêncio fazia a segunda
        linha ser resolvida como se fosse a primeira; aqui isso vira ERROR e a
        primeira associação prevalece.
        """
        if not identity or not initiative:
            return

        atual = existing_by_identity.get(identity)
        atual_id = getattr(atual, "id", None)
        novo_id = getattr(initiative, "id", None)
        if atual is not None and atual_id != novo_id:
            logger.error(
                f"Chave de identidade '{identity}' aponta para duas iniciativas "
                f"({atual_id} e {novo_id}); mantendo a primeira. A chave não "
                f"identifica o registro de forma única."
            )
            return
        existing_by_identity[identity] = initiative

    def _register_existing_initiative(
        self,
        *,
        existing_by_name: Dict[str, Any],
        title: Optional[str],
        initiative: Any,
        model_class,
    ) -> None:
        if not title or not initiative:
            return

        current = existing_by_name.get(title)
        if current is None or self._candidate_matches_model(current, model_class):
            existing_by_name[title] = initiative

    @staticmethod
    def _row_label(row_dict: Dict[str, Any]) -> str:
        """Identifica a linha nas mensagens de log.

        A planilha do SigPesq nomeia a coluna ``Titulo``, sem acento. O código
        antigo lia ``'Título'`` e por isso todo descarte saía como 'Unknown' —
        18 projetos omitidos do catálogo sem que se pudesse saber quais. A
        estratégia de mapeamento já aceitava as duas grafias; aqui não aceitava.
        """
        titulo = row_dict.get("Titulo") or row_dict.get("Título") or "sem título"
        codigo = row_dict.get("Id") or row_dict.get("CodPJ") or row_dict.get("CodPT")
        return f"{titulo}" + (f" (Id {codigo})" if codigo else "")

    def _approval_status(self, row_dict: Dict[str, Any]) -> tuple[bool, str]:
        """Devolve (aprovado, parecer bruto).

        Regra: aprovado é o que **começa** com "aprovado" depois de normalizado.
        O teste anterior era ``"aprovado" not in parecer.lower()``, que aceita
        qualquer texto contendo a palavra — inclusive "Não aprovado". Nenhum dos
        valores presentes hoje (Aprovado, Salvo, Aprovação Solicitada, Recusado)
        dispara esse falso positivo, mas o vocabulário do SigPesq não é estável:
        a planilha de grupos usa outro conjunto para a mesma coluna.

        Coluna ausente continua aprovando, e isso é necessário: as planilhas de
        orientações e os projetos do Lattes não têm parecer nenhum.
        """
        if "ParecerDiretoria" not in row_dict:
            return True, ""

        parecer = str(row_dict.get("ParecerDiretoria") or "").strip()
        if not parecer:
            # Célula vazia não é o mesmo que coluna ausente: aqui a fonte tinha
            # onde declarar o parecer e não declarou. Mantemos a ingestão para
            # não mudar volume de dado sem decisão de negócio, mas avisamos.
            logger.warning(
                f"Projeto sem parecer da diretoria, ingerido assim mesmo: "
                f"{self._row_label(row_dict)}"
            )
            return True, ""

        return normalize_text(parecer).startswith("aprovado"), parecer

    def _is_approved(self, row_dict: Dict[str, Any]) -> bool:
        approved, _ = self._approval_status(row_dict)
        return approved

    def _rollback_session(self):
        try:
            self.controller._service._repository._session.rollback()
        except Exception:
            pass
