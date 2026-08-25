from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

from loguru import logger


class StepTimer:
    """Lightweight pipeline step timer with summary reporting."""

    def __init__(self, pipeline_name: str) -> None:
        self.pipeline_name = pipeline_name
        self.steps: list[dict[str, Any]] = []
        self._pipeline_start: float | None = None

    def start(self) -> None:
        self._pipeline_start = time.time()

    @contextmanager
    def track(self, step_name: str) -> Generator[None, None, None]:
        t0 = time.time()
        status = "ok"
        error_msg = None
        try:
            yield
        except Exception as exc:
            status = "error"
            error_msg = str(exc)[:200]
            raise
        finally:
            elapsed = time.time() - t0
            self.steps.append(
                {
                    "step": step_name,
                    "duration_s": round(elapsed, 2),
                    "status": status,
                    "error": error_msg,
                }
            )
            logger.info(f"[{self.pipeline_name}] {step_name} completed in {_fmt(elapsed)}")

    def summary(self) -> str:
        total = sum(s["duration_s"] for s in self.steps)
        width = max(len(s["step"]) for s in self.steps) if self.steps else 0
        lines = [
            "",
            f"===== {self.pipeline_name} — step durations =====",
        ]
        for s in self.steps:
            tag = "" if s["status"] == "ok" else f" [{s['status']}]"
            lines.append(f"  {s['step']:<{width}}  {_fmt(s['duration_s'])}{tag}")
        lines.append(f"  {'TOTAL':<{width}}  {_fmt(total)}")
        lines.append("")
        text = "\n".join(lines)
        logger.info(text)
        return text


def _fmt(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{int(m)}m {s:.1f}s"
    h, m = divmod(m, 60)
    return f"{int(h)}h {int(m)}m {s:.0f}s"
