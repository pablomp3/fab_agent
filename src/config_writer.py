from __future__ import annotations

import yaml

from src.agents.mapping_request import ValidatedMapping

DEFAULT_EXPERIMENTAL_THRESHOLD = 3.5
EXPERIMENTAL_THRESHOLD_SOURCE = "experimental_default_robust_mad_multiplier=3.5"
EXPERIMENTAL_HYPOTHESIS_CLASS = "experimental_unverified"
DEFAULT_PROVENANCE = (
    "Experimental unverified mapping draft; an inference from column names and "
    "summary statistics, not a validated schema or field calibration."
)


def _signal_entry(name: str) -> dict[str, object]:
    return {
        "name": name,
        "unit": None,
        "robust_z_threshold": DEFAULT_EXPERIMENTAL_THRESHOLD,
        "threshold_source": EXPERIMENTAL_THRESHOLD_SOURCE,
    }


def draft_relations_yaml(
    mapping: ValidatedMapping,
    *,
    name: str = "experimental_draft",
    provenance: str = DEFAULT_PROVENANCE,
) -> str:
    """Emit a reviewable YAML draft that turns the next run into the safe path.

    The draft is written only after Python validated every column. It is a
    starting point for an engineer, not a calibrated configuration: units stay
    ``null`` and the threshold is an explicit unverified default.
    """
    signal_names = [item.column for item in mapping.signals]
    signal_entries = [_signal_entry(item) for item in signal_names]
    primaries = [item.primary for item in mapping.relationships]
    if not primaries:
        primaries = list(signal_names)
    corroborating = sorted(
        {
            column
            for item in mapping.relationships
            for column in item.corroborating
            if column not in primaries
        }
    )
    scenario = {
        "signals": signal_entries,
        "predicates": {
            "primary_signals": primaries,
            "corroboration_signals": corroborating,
        },
        "rules": {
            EXPERIMENTAL_HYPOTHESIS_CLASS: {
                "require_all": ["has_primary_signal_anomaly"],
                "forbid_any": ["has_missing_required_evidence"],
            }
        },
        "candidate": {
            "claim": "Experimental unverified mapping draft",
            "hypothesis_class": EXPERIMENTAL_HYPOTHESIS_CLASS,
            "cited_signals": signal_names,
            "root_cause": "unknown",
            "failure_mode": "Not claimed; the mapping is unverified.",
            "mechanism": "Not claimed; the mapping is unverified.",
        },
        "supported_action": "ESCALATE_TO_ENGINEER",
    }
    document = {
        "version": 1,
        "name": name,
        "provenance": provenance,
        "signals": signal_entries,
        "scenarios": {"experimental_scope": scenario},
    }
    return str(yaml.safe_dump(document, sort_keys=False))
