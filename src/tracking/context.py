from contextvars import ContextVar

current_ingestion_run_id: ContextVar[int | None] = ContextVar(
    "current_ingestion_run_id", default=None
)
current_source_system: ContextVar[str | None] = ContextVar(
    "current_source_system", default=None
)
# The source document being processed (source system, document key), set by
# DocumentSkip while a phase works on it (spec 021); None outside a document.
current_document: ContextVar[tuple[str, str] | None] = ContextVar(
    "current_document", default=None
)
