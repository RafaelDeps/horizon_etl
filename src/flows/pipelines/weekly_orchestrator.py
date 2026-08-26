"""Process-isolated weekly pipeline orchestrator.

Each phase runs in its OWN `python app.py <cmd>` subprocess. This exists
because a single-process weekly run segfaulted: the CNPq/Lattes phases churn
native browser code (Playwright/Selenium), and heap corruption there crashed
a later native SQLite call in the Lattes ingest — taking the whole run (and
the export/anonymize steps) down with it.

Isolation gives each phase clean native + SQLite state, so one phase crashing
(segfault, timeout, exception) no longer aborts the others. The exports still
run and publish whatever the sources produced, while a failure in any
*critical* phase (sources missing, export, or LGPD anonymization) still makes
the overall run exit non-zero so CI and Telegram surface it — instead of the
old fail-open behavior that reported success on partial data.

Every phase that WRITES to the database is driven through `app.py`, never
`python -m ...`, because the LGPD `before_flush` anonymization hook is
installed at app.py import time; a phase that bypassed it would write raw
PII to the database.

The docentes/OpenAlex analytics phases are the one exception: they are
read-only with respect to the database (they only read Lattes CV JSON,
canonical export JSON and the OpenAlex API, and write JSON reports), so they
run as `python -m src.scripts.<x>` modules. Not touching the DB, they have
no PII-write path and don't need the app.py hook. They run AFTER
`export_canonical` (a couple need `researchers_canonical.json` /
`openalex_citacoes.json` produced upstream) and are all non-critical, so a
missing optional manual input (bolsistas, projetos, corpo docente) degrades
gracefully without failing the weekly run.
"""

import subprocess
import sys
from typing import Optional

from loguru import logger

# (name, argv tail, timeout seconds, critical, mode)
#   mode "app"    -> `python app.py <argv...>`      (DB-writing phases; LGPD hook active)
#   mode "module" -> `python -m <module>`           (read-only docentes/OpenAlex reports)
# Order is load-bearing: SigPesq -> CNPq -> Lattes -> enrich_projects -> exports -> docentes -> LGPD.
# enrich_projects runs after both project sources so PJ document files can match
# initiatives by SigPesq code or Lattes title; it must precede export_canonical.
# The docentes block runs after export_canonical (needs researchers_canonical.json /
# openalex_citacoes.json produced upstream) and is ordered internally so each report's
# inputs exist: fetch_openalex -> rank -> {maturity, venues, impacto, ppp}.
_PHASES = [
    ("sigpesq", ["sigpesq"], 3600, True, "app"),
    ("cnpq", ["cnpq_sync"], 5400, False, "app"),
    ("lattes_download", ["lattes_download"], 5400, False, "app"),
    ("lattes_projects", ["ingest_lattes_projects"], 3600, False, "app"),
    ("lattes_advisorships", ["lattes_advisorships"], 1800, False, "app"),
    ("enrich_projects", ["enrich_projects"], 900, False, "app"),
    ("export_canonical", ["export_canonical"], 1800, True, "app"),
    ("knowledge_areas_mart", ["ka_mart"], 900, False, "app"),
    ("initiatives_analytics_mart", ["analytics_mart"], 900, False, "app"),
    ("people_relationship_graph", ["people_graph"], 1800, False, "app"),
    # --- docentes / OpenAlex analytics (read-only wrt DB; run as modules) ---
    (
        "openalex_citations",
        ["src.scripts.fetch_openalex_citations"],
        3600,
        False,
        "module",
    ),
    (
        "rank_docentes_impact",
        ["src.scripts.rank_docentes_impact"],
        600,
        False,
        "module",
    ),
    ("analyze_maturity", ["src.scripts.analyze_maturity"], 900, False, "module"),
    ("analyze_venues", ["src.scripts.analyze_venues"], 1800, False, "module"),
    (
        "impacto_dashboard",
        ["src.scripts.generate_impacto_dashboard"],
        900,
        False,
        "module",
    ),
    (
        "ppp_edital_report",
        ["src.scripts.generate_ppp_edital_report"],
        900,
        False,
        "module",
    ),
    ("anonymize_backfill", ["anonymize_backfill"], 1800, True, "app"),
]


# Optional phase, NOT part of the normal weekly run.
#
# It produces the PJ_*.json corpus that `enrich_projects` consumes, by downloading
# every project PDF and pushing it through an LLM. That is slow and costs money per
# document, while project plans barely change — so the weekly stays a pure consumer
# and this normally runs on demand (`make extract-project-files`).
#
# `make weekly-mistral` turns it on to REHEARSE how the weekly will look if the
# extraction is ever promoted into it: same process isolation, same position
# (immediately before enrich_projects, so fresh documents feed it), its own
# timeout, and its own line in the summary. Generous timeout because hundreds of
# PDFs plus OCR are involved; non-critical for the same reason enrich_projects is —
# a portal or API problem must not sink the whole run.
_PROJECT_FILES_PHASE = (
    "extract_project_files",
    ["extract_project_files"],
    7200,
    False,
    "app",
)


def _phases(include_project_files: bool = False):
    """The weekly phase list, optionally with the document extraction phase."""
    if not include_project_files:
        return list(_PHASES)
    ordered = []
    for phase in _PHASES:
        if phase[0] == "enrich_projects":
            ordered.append(_PROJECT_FILES_PHASE)
        ordered.append(phase)
    return ordered


def _describe_rc(rc: Optional[int]) -> str:
    if rc is None:
        return "timeout"
    if rc < 0:
        return f"killed by signal {-rc}"
    if rc > 128:
        return f"killed by signal {rc - 128}"  # shell convention (139 = SIGSEGV)
    return f"exit {rc}"


def _run_phase(name, argv_tail, timeout, campus, output_dir, mode="app"):
    if mode == "module":
        # Read-only report modules — run directly, no app.py LGPD hook needed.
        argv = [sys.executable, "-m", *argv_tail]
    else:
        argv = [sys.executable, "app.py", *argv_tail]
        # Pass positional args only where app.py expects them.
        if argv_tail[0] == "cnpq_sync" and campus:
            argv.append(campus)
        elif argv_tail[0] == "export_canonical":
            argv.append(output_dir)
    logger.info("▶ phase '{}': {}", name, " ".join(argv[1:]))
    try:
        proc = subprocess.run(argv, timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        logger.error("phase '{}' timed out after {}s", name, timeout)
        rc = None
    ok = rc == 0
    log = logger.info if ok else logger.error
    log("phase '{}' finished: {}", name, _describe_rc(rc))
    return {
        "name": name,
        "ok": ok,
        "rc": rc,
        "critical": bool(argv_tail and _critical(name)),
    }


def _critical(name):
    for n, _a, _t, crit, _m in (*_PHASES, _PROJECT_FILES_PHASE):
        if n == name:
            return crit
    return False


def _notify(results, crit_failed):
    from src.notifications.telegram import send_telegram_message

    head = "❌ Weekly ETL FALHOU" if crit_failed else "✅ Weekly ETL concluído"
    lines = [head, ""]
    for r in results:
        mark = "✓" if r["ok"] else "✗"
        lines.append(f"{mark} {r['name']} — {_describe_rc(r['rc'])}")
    if crit_failed:
        lines.append("")
        lines.append(
            "Fases críticas que falharam: " + ", ".join(r["name"] for r in crit_failed)
        )
    send_telegram_message("\n".join(lines))


def run_weekly(
    campus_name: Optional[str] = None,
    output_dir: str = "data/exports",
    include_project_files: bool = False,
) -> int:
    """Run every weekly phase in its own subprocess. Returns a process exit code.

    ``include_project_files`` adds the SigPesq document extraction phase before
    ``enrich_projects`` — the rehearsal mode behind ``make weekly-mistral``.
    """
    campus = (campus_name or "").strip()
    results = []
    for name, argv_tail, timeout, _crit, mode in _phases(include_project_files):
        results.append(_run_phase(name, argv_tail, timeout, campus, output_dir, mode))

    failed = [r for r in results if not r["ok"]]
    crit_failed = [r for r in failed if r["critical"]]

    logger.info("=== Weekly pipeline summary ===")
    for r in results:
        logger.info(
            "  {} {} ({})", "✓" if r["ok"] else "✗", r["name"], _describe_rc(r["rc"])
        )

    try:
        _notify(results, crit_failed)
    except Exception as exc:  # notification must never change the run outcome
        logger.warning("Telegram summary failed: {}", exc)

    if crit_failed:
        logger.error(
            "Weekly pipeline FAILED — critical phases: {}",
            ", ".join(r["name"] for r in crit_failed),
        )
        return 1
    if failed:
        logger.warning(
            "Weekly pipeline completed with non-critical failures: {}",
            ", ".join(r["name"] for r in failed),
        )
    return 0


if __name__ == "__main__":
    _campus = sys.argv[1] if len(sys.argv) > 1 else None
    _out = sys.argv[2] if len(sys.argv) > 2 else "data/exports"
    sys.exit(run_weekly(campus_name=_campus, output_dir=_out))
