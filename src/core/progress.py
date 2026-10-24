"""Small, optional progress signal for the dashboard.

The analysis pipeline is synchronous. The dashboard uses this callback to show
which deterministic or model stage is running, without changing any verdict or
leaking model text. A progress callback is observational only: a failure in the
callback must never stop an analysis.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

ProgressState = Literal["running", "done", "skipped", "failed"]
ProgressCallback = Callable[[str, ProgressState], None]

STAGE_READ = "read"
STAGE_TRIAGE = "triage"
STAGE_MAPPING = "mapping"
STAGE_DUCKDB = "duckdb"
STAGE_PYTHON = "python"
STAGE_MODEL = "model"
STAGE_GATE = "gate"
STAGE_TAVILY = "tavily"

STAGE_ORDER: tuple[str, ...] = (
    STAGE_READ,
    STAGE_TRIAGE,
    STAGE_MAPPING,
    STAGE_DUCKDB,
    STAGE_PYTHON,
    STAGE_MODEL,
    STAGE_GATE,
    STAGE_TAVILY,
)


def report(
    progress: ProgressCallback | None,
    step: str,
    state: ProgressState,
) -> None:
    """Notify the caller if a callback is present; never break the run."""
    if progress is None:
        return
    try:
        progress(step, state)
    except Exception:
        # Progress is a UI convenience. It must not be able to fail a run.
        return


__all__ = [
    "STAGE_DUCKDB",
    "STAGE_GATE",
    "STAGE_MAPPING",
    "STAGE_MODEL",
    "STAGE_ORDER",
    "STAGE_PYTHON",
    "STAGE_READ",
    "STAGE_TAVILY",
    "STAGE_TRIAGE",
    "ProgressCallback",
    "ProgressState",
    "report",
]
