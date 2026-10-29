"""Skip unchanged source documents (spec 021).

A phase wraps each document it processes::

    skip = DocumentSkip(store, "lattes_projects", on_rollback=reload_caches)
    for path in files:
        with skip.document(lattes_id) as doc:
            data = read(path)
            if doc.unchanged(data):
                continue                     # skipped: nothing is written
            doc.begin()                      # one transaction for the document
            process(data)                    # today's code
    skip.finish(listed_keys, complete=True)
    skip.log_summary()

A document that raises, or that ``mark_partial`` flagged, is rolled back whole
and recorded as failed; the phase goes on with the next one (contract
document-processing.md). The decision to skip only uses source data: the
canonical content hash, the rule version and (US1) the references.
"""

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Callable, Dict, Iterable, List, Optional

from loguru import logger
from rapidfuzz import fuzz as rapid_fuzz
from rapidfuzz import process as rapid_process
from thefuzz import utils as fuzz_utils

from src.core.logic.horizon_identity import (
    FUZZY_MATCH_THRESHOLD,
    HORIZON_RULE_VERSION,
    initiative_reference_key,
    person_reference_key,
)
from src.core.logic.initiative_identity import normalize_text
from src.core.logic.person_identity import normalize_participant_name
from src.core.ports.document_state_store import (
    DocumentFailed,
    DocumentOutcome,
    DocumentState,
    IDocumentStateStore,
    Reference,
)
from src.tracking.context import current_document, current_ingestion_run_id
from src.tracking.recorder import stable_hash, tracking_recorder

PROCESSED = "processed"
SKIPPED = "skipped"
FAILED = "failed"
DELETED = "deleted_items"

# The Document object behind ``current_document`` (which only holds its keys).
_active_document: ContextVar[Optional["Document"]] = ContextVar(
    "active_document", default=None
)


class Document:
    """The document being processed; created by ``DocumentSkip.document``."""

    def __init__(self, skip: "DocumentSkip", key: str):
        self._skip = skip
        self.key = key
        self.state: Optional[DocumentState] = skip.states.get(key)
        self.content_hash: Optional[str] = None
        self.references: List[Reference] = []
        self.items: Dict[tuple, bool] = {}
        self.begun = False
        self.skipped = False
        self.partial_reason: Optional[str] = None

    def unchanged(self, content) -> bool:
        """True when the stored state says this exact content was already
        processed under the same rules; the document is then skipped."""
        self.content_hash = stable_hash(content)
        state = self.state
        same = bool(
            state is not None
            and state.content_hash == self.content_hash
            and state.rule_version == self._skip.rule_version
        )
        # A key already processed in this run (the same report row in several
        # files) had its references resolved minutes ago: no need to check them.
        self.skipped = same and (
            self.key in self._skip.processed_this_run
            or self._skip.references_hold(state)
        )
        return self.skipped

    def begin(self) -> None:
        if self.content_hash is None:
            raise RuntimeError("unchanged(content) must run before begin()")
        self._skip.store.begin_document()
        self.begun = True

    def reference(self, kind: str, lookup_key: str, outcome: str, score=None) -> None:
        self.references.append(Reference(kind, lookup_key, outcome, score))

    def carry(self, item_type: str, item_ref, is_subject: bool = False) -> None:
        key = (item_type, str(item_ref))
        self.items[key] = self.items.get(key, False) or is_subject

    def mark_partial(self, detail: str = "") -> None:
        """A section or row of the document failed: it must not be committed,
        or the items of that section would look removed (research R4)."""
        self.partial_reason = detail or "a part of the document failed"

    def outcome(self) -> DocumentOutcome:
        references = sorted(
            set(self.references), key=lambda r: (r.kind, r.lookup_key, r.outcome)
        )
        return DocumentOutcome(
            source_system=self._skip.source_system,
            document_key=self.key,
            content_hash=self.content_hash,
            dependency_fingerprint=stable_hash(
                [[r.kind, r.lookup_key, r.outcome, r.score] for r in references]
            ),
            rule_version=self._skip.rule_version,
            ingestion_run_id=current_ingestion_run_id.get(),
            references=references,
            items=sorted((t, r, subject) for (t, r), subject in self.items.items()),
        )


class DocumentSkip:
    def __init__(
        self,
        store: IDocumentStateStore,
        source_system: str,
        rule_version: int = HORIZON_RULE_VERSION,
        on_rollback: Optional[Callable[[], None]] = None,
    ):
        self.store = store
        self.source_system = source_system
        self.rule_version = rule_version
        self.on_rollback = on_rollback
        self.states: Dict[str, DocumentState] = store.load(source_system)
        # Stable keys of current persons and initiatives (R3 check 1): read once,
        # extended with the rows created after each write, read again after a
        # rollback (rows it knew may be gone).
        self._targets = None
        self._targets_after = (0, 0)
        self._targets_stale = False
        self.processed_this_run: set = set()
        # Every key this run opened a document for: the listing of a report.
        self.seen: set = set()
        self.counts: Counter = Counter()
        self.failures: List[tuple] = []
        self.listing = None
        self.listing_complete: Optional[bool] = None

    @contextmanager
    def document(self, key: str):
        doc = Document(self, str(key))
        self.seen.add(doc.key)
        token = current_document.set((self.source_system, doc.key))
        doc_token = _active_document.set(doc)
        try:
            yield doc
        except DocumentFailed as exc:
            self._fail(doc, exc.reason, exc.detail)
        except Exception as exc:  # the phase goes on with the next document
            logger.exception("Document {} {} failed", self.source_system, doc.key)
            self._fail(doc, "partial", f"{type(exc).__name__}: {exc}")
        else:
            if doc.skipped:
                self.counts[SKIPPED] += 1
                if doc.state is not None and doc.state.last_failure:
                    # Read again and unchanged: an earlier failure (a download
                    # that failed once) no longer applies.
                    self.store.clear_failure(self.source_system, doc.key)
            elif not doc.begun:
                # Read but neither skipped nor processed (the phase decided it
                # has nothing to write): counts as skipped, state unchanged.
                self.counts[SKIPPED] += 1
            elif doc.partial_reason:
                self._fail(doc, "partial", doc.partial_reason)
            else:
                self._commit(doc)
        finally:
            _active_document.reset(doc_token)
            current_document.reset(token)

    def references_hold(self, state: DocumentState) -> bool:
        """Research R3: an unchanged document is skipped only if every name it
        resolved would still resolve the same way. False when a target is
        gone, or a person or initiative created or renamed since the document
        was processed could match one of its lookups (conservative: a similar
        name is enough to process the document again)."""
        refs = self.store.references(self.source_system, state.document_key)
        if not refs:
            return True
        if self._targets is None:
            persons, initiatives, max_p, max_i = self.store.target_keys()
            self._targets = (persons, initiatives)
            self._targets_after = (max_p, max_i)
            self._targets_stale = False
        elif self._targets_stale:
            new_p, new_i, max_p, max_i = self.store.target_keys(*self._targets_after)
            self._targets[0].update(new_p)
            self._targets[1].update(new_i)
            self._targets_after = (max_p, max_i)
            self._targets_stale = False
        persons, initiatives = self._targets
        for ref in refs:
            if ref.outcome.startswith("person:") and ref.outcome not in persons:
                return False
            if ref.outcome.startswith("initiative:") and ref.outcome not in initiatives:
                return False
        delta = self.store.delta(state)
        if delta.persons and _person_lookups_affected(refs, delta.persons):
            return False
        if delta.initiatives and _initiative_lookups_affected(refs, delta.initiatives):
            return False
        return True

    def _commit(self, doc: Document) -> None:
        outcome = doc.outcome()
        try:
            deletions = self.store.commit_processed(outcome) or []
            for deleted in deletions:
                # FR-011b: the tracking rows of a deleted item stay; the
                # deletion itself is logged with the item's last values.
                tracking_recorder.record_change(
                    source_record_id=None,
                    canonical_entity_type=deleted.entity_type,
                    canonical_entity_id=deleted.entity_id,
                    operation="delete",
                    changed_fields=[],
                    before=deleted.before,
                    reason=f"Dropped by {self.source_system} {doc.key}",
                )
        except DocumentFailed as exc:
            self._fail(doc, exc.reason, exc.detail)
            return
        self.store.commit_document()
        self.counts[DELETED] += len(deletions)
        self._targets_stale = True
        self.processed_this_run.add(doc.key)
        self.counts[PROCESSED] += 1
        # A key seen twice in one run (the same row twice in a report) is then
        # compared with what was just written, not with the previous run.
        self.states[doc.key] = DocumentState(
            source_system=self.source_system,
            document_key=doc.key,
            content_hash=outcome.content_hash,
            dependency_fingerprint=outcome.dependency_fingerprint,
            rule_version=outcome.rule_version,
            max_person_id=None,
            max_initiative_id=None,
            item_count=sum(1 for _t, _r, subject in outcome.items if not subject),
            last_ingestion_run_id=outcome.ingestion_run_id,
            processed_at=None,
            last_seen_at="",
            status="active",
        )

    def _fail(self, doc: Document, reason: str, detail: str = "") -> None:
        if doc.begun:
            self._targets = None
            self.store.rollback_document()
            if self.on_rollback is not None:
                self.on_rollback()
        self.store.record_failure(self.source_system, doc.key, reason)
        self.counts[FAILED] += 1
        self.counts[f"failed:{reason}"] += 1
        self.failures.append((doc.key, reason, detail))
        logger.warning(
            "Document {} {} failed ({}){}: stored data and state kept",
            self.source_system,
            doc.key,
            reason,
            f" — {detail}" if detail else "",
        )

    def finish(self, listed_keys: Iterable[str], complete: bool) -> None:
        self.listing = self.store.mark_listing(
            self.source_system, listed_keys, complete
        )
        self.listing_complete = complete

    def summary(self) -> dict:
        reasons = {
            k.split(":", 1)[1]: v
            for k, v in self.counts.items()
            if k.startswith("failed:")
        }
        listing = self.listing
        return {
            "source_system": self.source_system,
            "processed": self.counts[PROCESSED],
            "skipped": self.counts[SKIPPED],
            "failed": self.counts[FAILED],
            "deleted_items": self.counts[DELETED],
            "failed_by_reason": reasons,
            "listing_complete": self.listing_complete,
            "newly_inactive": listing.newly_inactive if listing else 0,
            "reactivated": listing.reactivated if listing else 0,
            "failures": [
                {"document_key": k, "reason": r, "detail": d}
                for k, r, d in self.failures
            ],
        }

    def log_summary(self) -> dict:
        s = self.summary()
        reasons = " ".join(f"{k}={v}" for k, v in sorted(s["failed_by_reason"].items()))
        logger.info(
            "documents {}: processed={} skipped={} failed={}{} inactive={} "
            "reactivated={} deleted_items={}",
            self.source_system,
            s["processed"],
            s["skipped"],
            s["failed"],
            f" ({reasons})" if reasons else "",
            s["newly_inactive"],
            s["reactivated"],
            s["deleted_items"],
        )
        write_phase_report(s)
        return s


# The reference checks normalize the names of every person and initiative
# created after a document, for each skipped document: after a rebuild that is
# thousands of names per document, the same names every time.
@lru_cache(maxsize=None)
def _exact_form(name: str) -> str:
    return normalize_participant_name(name, canonical_particles=False)


@lru_cache(maxsize=None)
def _title_form(name: str) -> str:
    return normalize_text(name)


@lru_cache(maxsize=None)
def _fuzzy_form(name: str) -> str:
    # The same processing PersonMatcher applies before its fuzzy step.
    normalized = normalize_participant_name(name or "", canonical_particles=False)
    return fuzz_utils.full_process(
        fuzz_utils.full_process(normalized), force_ascii=True
    )


def _person_lookups_affected(refs: List[Reference], persons) -> bool:
    lookups = [r for r in refs if r.kind in ("person_name", "researcher_owner")]
    if not lookups:
        return False
    lattes_ids = {url.rstrip("/").rsplit("/", 1)[-1] for _n, url in persons if url}
    exact = choices = None
    for ref in lookups:
        name, _, lattes = ref.lookup_key.partition("|lattes:")
        if lattes and lattes in lattes_ids:
            return True
        if ref.outcome == person_reference_key(name):
            # Resolved to a person of this very name: the exact match comes
            # before any fuzzy step and the earlier person wins a tie, so a
            # person created since cannot change it (check 1 covers its loss).
            continue
        if exact is None:
            exact = {_exact_form(n or "") for n, _ in persons}
            choices = [_fuzzy_form(n or "") for n, _ in persons]
        if name in exact:
            return True
        query = _fuzzy_form(name)
        if query and rapid_process.extractOne(
            query,
            choices,
            scorer=rapid_fuzz.token_sort_ratio,
            processor=None,
            score_cutoff=FUZZY_MATCH_THRESHOLD - 0.5,
        ):
            return True
    return False


def _initiative_lookups_affected(refs: List[Reference], names: List[str]) -> bool:
    titles = None
    for ref in refs:
        if ref.kind != "initiative":
            continue
        _identity, _, title = ref.lookup_key.partition("|title:")
        if ref.outcome == initiative_reference_key(title):
            # Resolved to an initiative of this very title: the earlier one
            # keeps winning (indexes keep the first per title).
            continue
        if not title:
            continue
        if titles is None:
            titles = {_title_form(n) for n in names if n}
        if title in titles:
            return True
    return False


def current() -> Optional[Document]:
    """The document being processed in this context, or None."""
    return _active_document.get()


def document_reference(kind: str, lookup_key: str, outcome: str, score=None) -> None:
    """For resolvers: records a reference on the current document, if any."""
    doc = current()
    if doc is not None:
        doc.reference(kind, lookup_key, outcome, score)


def carry(item_type: str, item_ref, is_subject: bool = False) -> None:
    """For writers: records that the current document carries this item."""
    doc = current()
    if doc is not None and item_ref is not None:
        doc.carry(item_type, item_ref, is_subject)


def mark_partial(detail: str = "") -> None:
    """For code that logs and swallows a failure inside a document."""
    doc = current()
    if doc is not None:
        doc.mark_partial(detail)


STATES_FILE = "source_document_states_canonical.json"
_STATE_FIELDS = (
    "source_system",
    "document_key",
    "status",
    "last_seen_at",
    "processed_at",
)


def write_states_file(rows: List[dict], output_dir: str) -> Optional[str]:
    """Writes ``source_document_states_canonical.json`` (contract
    source-document-states-export.md): keys, statuses and dates only, sorted,
    so two exports of the same state differ only in the dates. Writes nothing
    (and returns None) when there is no state yet."""
    import os
    from datetime import datetime, timezone

    from src.core.logic.atomic_io import atomic_write_json

    if not rows:
        logger.warning("No document states to export; {} not written", STATES_FILE)
        return None
    documents = sorted(
        ({f: row.get(f) for f in _STATE_FIELDS} for row in rows),
        key=lambda r: (r["source_system"], r["document_key"]),
    )
    payload = {
        "rule_version": HORIZON_RULE_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "documents": documents,
    }
    path = os.path.join(output_dir, STATES_FILE)
    atomic_write_json(path, payload, indent=2)
    logger.info("Exported {} document states to {}", len(documents), path)
    return path


REPORT_PATH = "data/reports/source_document_states_report.json"


def write_phase_report(summary: dict, path: str = None) -> None:
    """One entry per phase in ``source_document_states_report.json`` (research
    R12): the counts and the failed documents by key and reason, replaced by
    the phase's next run. Never fails the phase."""
    import json
    import os
    from datetime import datetime, timezone

    from src.core.logic.atomic_io import atomic_write_json

    path = path or REPORT_PATH
    try:
        report = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                report = json.load(f)
        phases = report.setdefault("phases", {})
        entry = dict(summary)
        entry["generated_at"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        phases[summary["source_system"]] = entry
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        atomic_write_json(path, report, indent=2)
    except Exception as exc:
        logger.warning("Document states report not written: {}", exc)


def order_free(content):
    """The content with every list sorted, for documents whose source returns
    lists in no fixed order (the CNPq mirror shuffles some of its tables
    between two downloads of the same page): the content hash then changes
    only when the content does."""
    import json

    if isinstance(content, dict):
        return {k: order_free(v) for k, v in content.items()}
    if isinstance(content, list):
        items = [order_free(v) for v in content]
        return sorted(
            items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False)
        )
    return content
