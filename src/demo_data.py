"""Deterministic synthetic CSV generator for the dashboard.

The generator is deliberately small and explicit: it writes the same kind of
seeded baseline-plus-drift data used by the synthetic twin, but it is not a
benchmark generator and it never produces a ground-truth label. The dashboard
uses it so a judge can create a fresh tool export and watch the same
DuckDB -> Nemotron -> Python gate path run on it.

Every template is paired with a bundled sensor-relations config, except the
``unknown_tool`` template, which intentionally has no config and therefore
exercises the experimental fallback. Values are synthetic and are never
presented as field calibration.
"""

from __future__ import annotations

import csv
import io
import random
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "sensor_relations"


@dataclass(frozen=True, slots=True)
class GeneratorTemplate:
    key: str
    label: str
    description: str
    note: str
    config_path: Path | None
    columns: tuple[str, ...]
    centers: tuple[float, ...]
    sigmas: tuple[float, ...]
    primary_indices: tuple[int, ...]
    behaviors: tuple[str, ...]
    column_notes: tuple[tuple[str, str], ...] = ()


_TEMPLATES: tuple[GeneratorTemplate, ...] = (
    GeneratorTemplate(
        key="flowcool",
        label="PHM-style dataset — flowcool loop",
        description=(
            "Two configured coolant channels. A supported run moves both; an "
            "inconclusive run leaves them nominal."
        ),
        note="Flowcool loop excursion during the RF step.",
        config_path=CONFIG_DIR / "synthetic_flowcool.yaml",
        columns=("FLOWCOOLFLOWRATE", "FLOWCOOLPRESSURE"),
        centers=(10.0, 10.0),
        sigmas=(0.05, 0.05),
        primary_indices=(0, 1),
        behaviors=("supported", "inconclusive"),
        column_notes=(
            ("time", "Row index in the generated export."),
            (
                "FLOWCOOLFLOWRATE",
                "Coolant flow rate; a configured primary channel.",
            ),
            (
                "FLOWCOOLPRESSURE",
                "Coolant pressure; the second configured primary channel.",
            ),
        ),
    ),
    GeneratorTemplate(
        key="synthetic_rf",
        label="Synthetic RF dataset",
        description=(
            "The four synthetic-twin channels. A contradiction run moves "
            "sensor_17 while every corroborating channel stays nominal, so the "
            "Python veto wins over the model narrative."
        ),
        note=(
            "RF reflectometer excursion on Chamber B; corroborating channels "
            "look quiet."
        ),
        config_path=CONFIG_DIR / "synthetic_rf.yaml",
        columns=("sensor_17", "impedance", "thermal", "pressure"),
        centers=(10.0, 10.0, 10.0, 10.0),
        sigmas=(0.5, 0.5, 0.5, 0.5),
        primary_indices=(0,),
        behaviors=("supported", "inconclusive", "contradiction"),
        column_notes=(
            ("time", "Row index in the generated export."),
            ("sensor_17", "RF reflectometer; the configured primary channel."),
            ("impedance", "Electrical corroboration; quiet in a contradiction run."),
            ("thermal", "Thermal corroboration; quiet in a contradiction run."),
            ("pressure", "Pressure corroboration; quiet in a contradiction run."),
        ),
    ),
    GeneratorTemplate(
        key="tep_feed",
        label="TEP-style dataset — feed system",
        description=(
            "Three configured feed-system channels. A supported run moves the "
            "feed flow and reactor pressure together; an inconclusive run leaves "
            "the pattern nominal."
        ),
        note=(
            "Reactor feed disturbance suspected; A feed flow and reactor pressure "
            "look off."
        ),
        config_path=CONFIG_DIR / "tep_reactor.yaml",
        columns=("XMEAS(1)", "XMV(3)", "XMEAS(7)"),
        centers=(0.5, 32.0, 2705.0),
        sigmas=(0.01, 0.2, 1.0),
        primary_indices=(0, 2),
        behaviors=("supported", "inconclusive"),
        column_notes=(
            ("time", "Row index in the generated export."),
            ("XMEAS(1)", "A feed flow; a configured pattern channel."),
            ("XMV(3)", "A feed valve position; recorded but not part of the check."),
            ("XMEAS(7)", "Reactor pressure; the second configured pattern channel."),
        ),
    ),
    GeneratorTemplate(
        key="unknown_tool",
        label="Unknown tool dataset — no matching config",
        description=(
            "A new export with no configured schema. The safe path has no "
            "match, so the experimental mapping runs and stays unverified."
        ),
        note="New tool export; no configured schema yet.",
        config_path=None,
        columns=("chamber_temp", "chamber_pressure", "rf_power"),
        centers=(20.0, 5.0, 100.0),
        sigmas=(0.1, 0.02, 0.5),
        primary_indices=(0, 1, 2),
        behaviors=("supported", "inconclusive"),
        column_notes=(
            ("time", "Row index in the generated export."),
            ("chamber_temp", "Chamber temperature; no configured meaning yet."),
            ("chamber_pressure", "Chamber pressure; no configured meaning yet."),
            ("rf_power", "RF power; no configured meaning yet."),
        ),
    ),
)

GENERATOR_TEMPLATES: dict[str, GeneratorTemplate] = {
    item.key: item for item in _TEMPLATES
}


@dataclass(frozen=True, slots=True)
class GeneratedDataset:
    csv_bytes: bytes
    filename: str
    template: GeneratorTemplate
    behavior: str
    rows: int
    seed: int


def _shift_for(behavior: str, template: GeneratorTemplate, index: int) -> float:
    if behavior == "supported":
        return 12.0 * template.sigmas[index]
    if behavior == "contradiction":
        if index in template.primary_indices:
            return 12.0 * template.sigmas[index]
        return 0.0
    return 0.0


def generate_demo_csv(
    template_key: str,
    *,
    rows: int = 240,
    seed: int = 7,
    behavior: str = "supported",
) -> GeneratedDataset:
    """Return a deterministic CSV and its matching template metadata.

    ``behavior`` is one of the template's declared behaviors. The function
    validates it rather than silently mapping an unknown request to a
    supported-looking run.
    """
    try:
        template = GENERATOR_TEMPLATES[template_key]
    except KeyError as exc:
        raise ValueError(f"unknown generator template: {template_key}") from exc
    if behavior not in template.behaviors:
        raise ValueError(
            f"{behavior!r} is not available for {template.label}; "
            f"choose one of {template.behaviors}"
        )
    if rows < 12:
        raise ValueError("rows must be at least 12")
    rng = random.Random(seed)
    fault_start = int(rows * 0.6)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("time",) + template.columns)
    for index in range(rows):
        in_fault = index >= fault_start
        values: list[float] = []
        for signal_index, (center, sigma) in enumerate(
            zip(template.centers, template.sigmas, strict=True)
        ):
            baseline = center + rng.uniform(-1.0, 1.0) * sigma
            if in_fault:
                baseline += _shift_for(behavior, template, signal_index)
            if (
                behavior == "contradiction"
                and in_fault
                and signal_index not in template.primary_indices
            ):
                # Keep corroborating channels visibly quiet. Clamping is a
                # deliberate synthetic control, not a calibration claim.
                offset = max(-0.5 * sigma, min(0.5 * sigma, baseline - center))
                baseline = center + offset
            values.append(baseline)
        writer.writerow((index + 1, *values))
    filename = f"generated_{template.key}_{behavior}_{seed}.csv"
    return GeneratedDataset(
        csv_bytes=buffer.getvalue().encode("utf-8"),
        filename=filename,
        template=template,
        behavior=behavior,
        rows=rows,
        seed=seed,
    )


__all__ = [
    "GENERATOR_TEMPLATES",
    "GeneratedDataset",
    "GeneratorTemplate",
    "generate_demo_csv",
]
