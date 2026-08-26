import glob
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from eo_lib import Initiative, InitiativeController
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz, process
from sqlalchemy import text

from src.core.logic.initiative_identity import normalize_text
from src.db.migrations import run_migrations
from src.tracking.recorder import tracking_recorder

RESEARCH_PROJECT_TYPE = "Research Project"
# rapidfuzz ratio is on a 0-100 scale.
FUZZY_THRESHOLD = 90.0
NEW_FROM_DOCUMENT = "new_from_document"
STRATEGY_PRIORITY = {"sigpesq_project_code": 0, "title_exact": 1, "title_fuzzy": 2}


# --------------------------------------------------------------------------- #
# Enrichment payload schema (validated on build; stored as JSON in enrichment_json)
# --------------------------------------------------------------------------- #
class Objetivos(BaseModel):
    model_config = ConfigDict(extra="allow")
    geral: Optional[str] = None
    especificos: List[str] = Field(default_factory=list)


class CronogramaItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    atividade: Optional[str] = None
    inicio: Optional[str] = None
    fim: Optional[str] = None


class EnrichmentPayload(BaseModel):
    """Typed, validated shape of ``initiatives.enrichment_json``."""

    model_config = ConfigDict(extra="forbid")
    source: str
    project_code: Optional[str] = None
    match_strategy: str
    needs_review: bool
    objetivos: Objetivos = Field(default_factory=Objetivos)
    cronograma: List[CronogramaItem] = Field(default_factory=list)
    linha_pesquisa: Optional[str] = None
    palavras_chave: List[str] = Field(default_factory=list)
    area_conhecimento: Optional[str] = None
    extracted_at: Optional[str] = None
    extraction_model: Optional[str] = None
    source_file: Optional[str] = None


# --------------------------------------------------------------------------- #
# Pure helpers (no DB / no I/O) — unit-tested in tests/test_project_enrichment.py
# --------------------------------------------------------------------------- #
def normalize_project_code(value: Any) -> str:
    """Extracts the numeric SigPesq project code from a value like 'PJ 6020'."""
    if value is None:
        return ""
    match = re.search(r"\d+", str(value))
    return match.group(0) if match else ""


def compose_description(pj: Dict[str, Any]) -> Optional[str]:
    """Prefers the free-text ``descricao``; falls back to the general objective."""
    desc = (pj.get("descricao") or "").strip()
    if desc:
        return desc
    geral = ((pj.get("objetivos") or {}).get("geral") or "").strip()
    return geral or None


def build_enrichment(
    pj: Dict[str, Any], *, code: str, strategy: str, needs_review: bool
) -> Dict[str, Any]:
    """Assembles and VALIDATES the ``enrichment_json`` payload from a PJ document.

    Returns a plain dict (``EnrichmentPayload.model_dump``); raises
    ``pydantic.ValidationError`` on a malformed document so the row is skipped
    (via the caller's savepoint) instead of persisting garbage.
    """
    meta = pj.get("_meta") or {}
    payload = EnrichmentPayload(
        source=ProjectEnrichmentLoader.SOURCE_SYSTEM,
        project_code=code or None,
        match_strategy=strategy,
        needs_review=needs_review,
        objetivos=pj.get("objetivos") or {},
        cronograma=pj.get("cronograma") or [],
        linha_pesquisa=pj.get("linha_pesquisa"),
        palavras_chave=pj.get("palavras_chave") or [],
        area_conhecimento=pj.get("area_conhecimento"),
        extracted_at=meta.get("extraido_em"),
        extraction_model=meta.get("modelo"),
        source_file=meta.get("arquivo"),
    )
    return payload.model_dump()


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parses a 'YYYY-MM-DD' prefix into a ``datetime`` (for the ORM), or None."""
    if not value:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value))
    if not match:
        return None
    return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def parse_sql_datetime(value: Any) -> Optional[str]:
    """Turns a 'YYYY-MM-DD' string into the datetime format the ORM stores."""
    if not value:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value))
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)} 00:00:00.000000"


def derive_status(start: Optional[str], end: Optional[str], *, now: datetime) -> str:
    """Best-effort status for a documented project without a diretoria parecer.

    ``now`` is injected so the result is deterministic and testable.
    """
    if end:
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(end))
        if match:
            end_dt = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
            return "Concluded" if end_dt < now else "Active"
    return "Active" if start else "Unknown"


class Match(NamedTuple):
    initiative_id: int
    strategy: str
    needs_review: bool


def match_pj(
    pj: Dict[str, Any],
    code_index: Dict[str, int],
    name_index: Dict[str, List[int]],
    fuzzy_choices: Dict[int, str],
) -> Optional[Match]:
    """Resolves a PJ document to an existing initiative, most-confident first.

    code (approved SigPesq) > exact normalized title > fuzzy title >= threshold.
    Returns ``None`` when nothing matches.
    """
    code = normalize_project_code(pj.get("codigo"))
    if code and code in code_index:
        return Match(code_index[code], "sigpesq_project_code", False)

    norm_title = normalize_text(pj.get("titulo")) if pj.get("titulo") else ""
    if not norm_title:
        return None

    exact = name_index.get(norm_title)
    if exact:
        # Unique exact match is trusted; an ambiguous one is flagged for review.
        return Match(exact[0], "title_exact", len(exact) > 1)

    if fuzzy_choices:
        best = process.extractOne(
            norm_title,
            fuzzy_choices,
            scorer=fuzz.ratio,
            score_cutoff=FUZZY_THRESHOLD,
        )
        if best is not None:
            return Match(best[2], "title_fuzzy", True)
    return None


class Candidate(NamedTuple):
    path: str
    pj: Dict[str, Any]
    match: Optional[Match]


def resolve_claims(candidates: List[Candidate]) -> Tuple[List[Candidate], int]:
    """De-duplicates matched candidates so each initiative is claimed once by the
    highest-confidence match (code > title_exact > title_fuzzy; ties by filename).

    Returns (winners, collision_count). Unmatched candidates are ignored here.
    """
    matched = [c for c in candidates if c.match is not None]
    ordered = sorted(
        matched,
        key=lambda c: (STRATEGY_PRIORITY[c.match.strategy], c.path),
    )
    claimed: set[int] = set()
    winners: List[Candidate] = []
    collisions = 0
    for c in ordered:
        if c.match.initiative_id in claimed:
            collisions += 1
            continue
        claimed.add(c.match.initiative_id)
        winners.append(c)
    return winners, collisions


def is_ingestable(pj: Dict[str, Any]) -> bool:
    """A PJ document is rich enough to become a new initiative when it has a
    title, a description and either objectives or a schedule."""
    title = (pj.get("titulo") or "").strip()
    descricao = (pj.get("descricao") or "").strip()
    geral = ((pj.get("objetivos") or {}).get("geral") or "").strip()
    cronograma = pj.get("cronograma") or []
    return bool(title and descricao and (geral or cronograma))


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #
class ProjectEnrichmentLoader:
    """
    Enriches Research Project initiatives with content extracted from SigPesq
    project document files (``PJ_*.json``), and optionally ingests rich documents
    that match no existing initiative as new initiatives.

    Matching (per document, most confident first):
      1. ``sigpesq_project_code`` — tracking-table link; these are APPROVED.
      2. ``title_exact``          — normalized title equals a Research Project name.
      3. ``title_fuzzy``          — best title similarity >= 90 (``needs_review``).

    Writes:
      * ``description`` — filled only when empty (unless ``overwrite``).
      * ``enrichment_json`` — objectives / schedule / research line / keywords /
        area + provenance + match strategy / ``needs_review``. Always (re)written.

    All writes for one run happen in a single transaction; a row that fails is
    rolled back to a savepoint and skipped without aborting the others.
    """

    SOURCE_SYSTEM = "sigpesq_project_files"

    def __init__(self, overwrite: bool = False, dry_run: bool = False):
        self.controller = InitiativeController()
        self.overwrite = overwrite
        self.dry_run = dry_run

    @property
    def _session(self):
        return self.controller._service._repository._session

    # -------------------------------------------------------------- schema
    def ensure_schema(self) -> None:
        """Applies pending schema migrations (idempotent). Delegates DDL to the
        migrations module instead of running ad-hoc ``ALTER`` in business logic."""
        run_migrations(self._session)

    # -------------------------------------------------------------- indexes
    def _load_code_index(self) -> Dict[str, int]:
        """``project_code -> initiative_id`` for APPROVED SigPesq projects, using
        the tracking tables as the authoritative code<->initiative link."""
        rows = self._session.execute(
            text(
                """
                SELECT sr.raw_payload_json AS payload,
                       aa.canonical_entity_id AS init_id
                FROM source_records sr
                JOIN attribute_assertions aa
                  ON aa.source_record_id = sr.id
                 AND aa.canonical_entity_type = 'initiative'
                WHERE sr.source_system = 'sigpesq_research_projects'
                  AND sr.source_entity_type = 'initiative'
                """
            )
        ).fetchall()

        index: Dict[str, int] = {}
        for payload, init_id in rows:
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if "aprovado" not in str(data.get("ParecerDiretoria") or "").lower():
                continue
            code = normalize_project_code(data.get("Id"))
            if code and init_id and code not in index:
                index[code] = init_id
        return index

    def _load_research_project_names(
        self,
    ) -> Tuple[Dict[str, List[int]], Dict[int, str]]:
        """Returns (normalized_name -> [initiative_id], {initiative_id -> normalized_name})
        for Research Project initiatives only (advisorships excluded)."""
        rows = self._session.execute(
            text(
                """
                SELECT i.id, i.name
                FROM initiatives i
                JOIN initiative_types t ON i.initiative_type_id = t.id
                WHERE t.name = :type_name
                """
            ),
            {"type_name": RESEARCH_PROJECT_TYPE},
        ).fetchall()

        by_name: Dict[str, List[int]] = {}
        fuzzy_choices: Dict[int, str] = {}
        for init_id, name in rows:
            norm = normalize_text(name)
            if not norm:
                continue
            by_name.setdefault(norm, []).append(init_id)
            fuzzy_choices[init_id] = norm
        return by_name, fuzzy_choices

    def _load_current_descriptions(self) -> Dict[int, str]:
        rows = self._session.execute(
            text("SELECT id, description FROM initiatives")
        ).fetchall()
        return {row[0]: (row[1] or "") for row in rows}

    def _lookup_org_and_type(self) -> Tuple[Optional[int], int]:
        type_row = self._session.execute(
            text("SELECT id FROM initiative_types WHERE name = :n LIMIT 1"),
            {"n": RESEARCH_PROJECT_TYPE},
        ).fetchone()
        type_id = type_row[0] if type_row else 1
        org_row = self._session.execute(
            text(
                """
                SELECT organization_id FROM initiatives
                WHERE organization_id IS NOT NULL
                GROUP BY organization_id ORDER BY COUNT(*) DESC LIMIT 1
                """
            )
        ).fetchone()
        return (org_row[0] if org_row else None), type_id

    # -------------------------------------------------------------- read
    def _read_documents(self, pj_dir: str) -> List[Tuple[str, Dict[str, Any]]]:
        docs: List[Tuple[str, Dict[str, Any]]] = []
        for path in sorted(glob.glob(os.path.join(pj_dir, "PJ_*.json"))):
            try:
                with open(path, encoding="utf-8") as fh:
                    docs.append((path, json.load(fh)))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"Could not read {path}: {exc}")
        return docs

    # -------------------------------------------------------------- public API
    def load(self, pj_dir: str) -> Dict[str, int]:
        """Enrich existing initiatives only."""
        return self.run(pj_dir, ingest_new=False)

    def ingest_unmatched(self, pj_dir: str) -> Dict[str, int]:
        """Enrich existing AND create new initiatives from unmatched rich docs."""
        return self.run(pj_dir, ingest_new=True)

    def run(self, pj_dir: str, *, ingest_new: bool = False) -> Dict[str, int]:
        """Reads the documents once, classifies them once, then enriches matched
        initiatives (deduplicated) and, if requested, ingests unmatched rich ones.

        All writes join the session's ambient transaction (opened by the index
        SELECTs) and are committed once at the end; a failing row is skipped via
        savepoint. On error the session is rolled back and the exception
        propagates. ``dry_run`` writes nothing and commits nothing.
        """
        self.ensure_schema()

        code_index = self._load_code_index()
        name_index, fuzzy_choices = self._load_research_project_names()
        descriptions = self._load_current_descriptions()
        docs = self._read_documents(pj_dir)
        logger.info(
            f"{len(docs)} documents | {len(code_index)} approved-by-code | "
            f"{len(fuzzy_choices)} research-project names"
        )

        candidates = [
            Candidate(path, pj, match_pj(pj, code_index, name_index, fuzzy_choices))
            for path, pj in docs
        ]
        winners, collisions = resolve_claims(candidates)

        stats = {
            "enriched": 0,
            "desc_filled": 0,
            "desc_kept_existing": 0,
            "needs_review": 0,
            "by_code": 0,
            "by_title_exact": 0,
            "by_title_fuzzy": 0,
            "skipped_no_match": sum(1 for c in candidates if c.match is None),
            "skipped_collision": collisions,
            "errors": 0,
        }

        # NO explicit begin() here. The index loads above already ran SELECTs, and
        # a SQLAlchemy Session autobegins on ANY execute() -- a SELECT included --
        # so the session is always mid-transaction by this point and begin() would
        # raise "A transaction is already begun on this Session". The writes join
        # that ambient transaction instead: still one unit of work, and the
        # per-row SAVEPOINTs from _write_row nest inside it as before.
        # Keep it this way: reintroducing begin() breaks the phase outright, and
        # so does moving these writes above the index loads.
        try:
            self._enrich_winners(winners, descriptions, stats)
            if ingest_new:
                unmatched = [c for c in candidates if c.match is None]
                stats.update(self._ingest_new(unmatched, name_index))
            if not self.dry_run:
                self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        logger.info(
            f"Enrichment complete ({'dry-run' if self.dry_run else 'applied'}, "
            f"ingest_new={ingest_new}): {stats}"
        )
        return stats

    # -------------------------------------------------------------- enrich
    def _enrich_winners(
        self,
        winners: List[Candidate],
        descriptions: Dict[int, str],
        stats: Dict[str, int],
    ) -> None:
        for cand in winners:
            init_id = cand.match.initiative_id
            strategy = cand.match.strategy
            code = normalize_project_code(cand.pj.get("codigo"))
            enrichment = build_enrichment(
                cand.pj,
                code=code,
                strategy=strategy,
                needs_review=cand.match.needs_review,
            )
            new_desc = compose_description(cand.pj)
            current = descriptions.get(init_id, "").strip()
            write_desc = bool(new_desc) and (self.overwrite or not current)

            if self.dry_run:
                logger.info(
                    f"[dry-run][{strategy}] init {init_id} "
                    f"desc={'write' if write_desc else 'keep'} "
                    f"review={cand.match.needs_review} (code={code or '-'})"
                )
            else:
                written = self._write_row(
                    lambda: self._apply(
                        init_id, enrichment, new_desc if write_desc else None
                    )
                )
                if not written:
                    stats["errors"] += 1
                    continue
                self._record_tracking(
                    init_id=init_id,
                    code=code,
                    strategy=strategy,
                    enrichment=enrichment,
                    desc_written=new_desc if write_desc else None,
                    path=cand.path,
                    pj=cand.pj,
                )

            stats["enriched"] += 1
            stats[
                f"by_{'code' if strategy == 'sigpesq_project_code' else strategy}"
            ] += 1
            if cand.match.needs_review:
                stats["needs_review"] += 1
            if write_desc and not current:
                stats["desc_filled"] += 1
            elif current and not self.overwrite:
                stats["desc_kept_existing"] += 1

    # -------------------------------------------------------------- ingest
    def _ingest_new(
        self, unmatched: List[Candidate], name_index: Dict[str, List[int]]
    ) -> Dict[str, int]:
        org_id, type_id = self._lookup_org_and_type()
        existing_names = set(name_index.keys())
        seen_titles: set[str] = set()
        stats = {"created": 0, "skipped_poor": 0, "skipped_duplicate": 0}

        for cand in unmatched:
            pj = cand.pj
            if not is_ingestable(pj):
                stats["skipped_poor"] += 1
                continue
            norm = normalize_text(pj.get("titulo"))
            if norm in existing_names or norm in seen_titles:
                stats["skipped_duplicate"] += 1
                continue
            seen_titles.add(norm)

            if self.dry_run:
                stats["created"] += 1
                logger.info(
                    f"[dry-run][new] would create '{(pj.get('titulo') or '')[:60]}'"
                )
                continue

            if self._create_initiative(cand, org_id, type_id):
                existing_names.add(norm)
                stats["created"] += 1

        return stats

    def _create_initiative(
        self, cand: Candidate, org_id: Optional[int], type_id: int
    ) -> bool:
        pj = cand.pj
        code = normalize_project_code(pj.get("codigo"))
        enrichment = build_enrichment(
            pj, code=code, strategy=NEW_FROM_DOCUMENT, needs_review=True
        )
        datas = pj.get("datas") or {}
        description = compose_description(pj)
        name = (pj.get("titulo") or "").strip()
        new_id_box: Dict[str, Optional[int]] = {"id": None}

        def _do():
            # Create through the ORM entity so SQLAlchemy defaults and the
            # session's before_flush hooks (e.g. LGPD anonymization) fire.
            # flush() (not commit) keeps this inside the run() transaction.
            initiative = Initiative(
                name=name,
                status=derive_status(
                    datas.get("inicio"), datas.get("fim"), now=datetime.now()
                ),
                description=description,
                start_date=parse_datetime(datas.get("inicio")),
                end_date=parse_datetime(datas.get("fim")),
                initiative_type_id=type_id,
                organization_id=org_id,
            )
            self._session.add(initiative)
            self._session.flush()
            new_id_box["id"] = initiative.id
            # enrichment_json has no ORM column mapping -> raw UPDATE, same txn.
            self._session.execute(
                text("UPDATE initiatives SET enrichment_json = :j WHERE id = :id"),
                {"j": json.dumps(enrichment, ensure_ascii=False), "id": initiative.id},
            )

        if not self._write_row(_do):
            return False

        self._record_tracking(
            init_id=new_id_box["id"],
            code=code,
            strategy=NEW_FROM_DOCUMENT,
            enrichment=enrichment,
            desc_written=description,
            path=cand.path,
            pj=pj,
        )
        logger.info(f"[new] initiative {new_id_box['id']} created: {name[:60]}")
        return True

    # -------------------------------------------------------------- write helpers
    def _write_row(self, fn) -> bool:
        """Runs a single write inside a SAVEPOINT so one failing row is skipped
        without aborting the surrounding transaction."""
        try:
            with self._session.begin_nested():
                fn()
            return True
        except Exception as exc:
            logger.warning(f"Row write failed, skipping: {exc}")
            return False

    def _apply(
        self, init_id: int, enrichment: Dict[str, Any], description: Optional[str]
    ) -> None:
        payload = json.dumps(enrichment, ensure_ascii=False)
        if description:
            self._session.execute(
                text(
                    "UPDATE initiatives SET description = :d, enrichment_json = :j "
                    "WHERE id = :id"
                ),
                {"d": description, "j": payload, "id": init_id},
            )
        else:
            self._session.execute(
                text("UPDATE initiatives SET enrichment_json = :j WHERE id = :id"),
                {"j": payload, "id": init_id},
            )

    def _record_tracking(
        self,
        *,
        init_id: int,
        code: str,
        strategy: str,
        enrichment: Dict[str, Any],
        desc_written: Optional[str],
        path: str,
        pj: Dict[str, Any],
    ) -> None:
        if not tracking_recorder.has_active_run():
            return
        source_record = tracking_recorder.record_source_record(
            source_entity_type="initiative",
            payload=pj,
            source_record_id=f"PJ {code}" if code else os.path.basename(path),
            source_file=os.path.basename(path),
            source_path=path,
        )
        sr_id = getattr(source_record, "id", None)
        tracking_recorder.record_entity_match(
            source_record_id=sr_id,
            canonical_entity_type="initiative",
            canonical_entity_id=init_id,
            match_strategy=strategy,
            match_confidence=1.0 if strategy != "title_fuzzy" else 0.9,
        )
        selected = {"enrichment": enrichment}
        if desc_written:
            selected["description"] = desc_written
        tracking_recorder.record_attribute_assertions(
            source_record_id=sr_id,
            canonical_entity_type="initiative",
            canonical_entity_id=init_id,
            selected_attributes=selected,
            selection_reason="sigpesq_project_file_enrichment",
        )
        tracking_recorder.record_change(
            source_record_id=sr_id,
            canonical_entity_type="initiative",
            canonical_entity_id=init_id,
            operation="update",
            changed_fields=list(selected.keys()),
            after={"initiative_id": init_id, **selected},
            reason="ProjectEnrichmentLoader applied",
        )
