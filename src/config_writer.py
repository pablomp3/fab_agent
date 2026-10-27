from __future__ import annotations

import yaml

from src.agents.mapping_request import ValidatedMapping

DEFAULT_EXPERIMENTAL_THRESHOLD = 3.5
EXPERIMENTAL_THRESHOLD_SOURCE = "experimental_default_robust_mad_multiplier=3.5"
EXPERIMENTAL_HYPOTHESIS_CLASS = "experimental_unverified"
DEFAULT_DRAFT_BASELINE_ROWS = 50
DEFAULT_PROVENANCE = (
    "Experimental unverified mapping draft; an inference from column names and "
    "summary statistics, not a validated schema or field calibration."
)


def _signal_entry(name: str) -> dict[str, object]:
    return {
        "name": name,
        "label": name,
        "unit": None,
        "alert_at": DEFAULT_EXPERIMENTAL_THRESHOLD,
    }


def draft_relations_yaml(
    mapping: ValidatedMapping,
    *,
    name: str = "experimental_draft",
    provenance: str = DEFAULT_PROVENANCE,
) -> str:
    """Emit a reviewable v2 draft that explains why the next run abstains.

    The draft is written only after Python validated every column. It contains
    signals and a normal-reference definition, but no checks: without a
    check, the next run is **Unknown Machine**, not a diagnosis. An engineer
    adds the check before the profile can confirm or reject anything.
    """
    signal_names = [item.column for item in mapping.signals]
    signal_entries = [_signal_entry(item) for item in signal_names]
    label = " ".join(part.capitalize() for part in name.replace("_", " ").split())
    document = {
        "version": 2,
        "tool": {
            "name": name,
            "label": label or name,
            "description": provenance,
        },
        "baseline": {
            "mode": "lead_in",
            "rows": DEFAULT_DRAFT_BASELINE_ROWS,
            "file": None,
            "step_column": None,
        },
        "signals": signal_entries,
        "checks": [],
    }
    return str(yaml.safe_dump(document, sort_keys=False))
