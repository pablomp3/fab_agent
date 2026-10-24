"""Prepared demo inputs shown in the dashboard.

Each entry pairs a small CSV with the bundled sensor-relations config that
makes the run meaningful. The expected result is a short, human-readable
description for the judge; it is not an assertion used by the gate. The app
still runs the real triage, DuckDB scan, model call, and Python gate.

The public-dataset samples are committed slices of the public PHM 2018 and
Tennessee Eastman Process data. The remaining samples are synthetic and are
labelled as such. None of these files is field validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class DemoCase:
    key: str
    label: str
    csv_path: Path
    config_path: Path | None
    note: str
    description: str
    expected: str
    source: str
    column_notes: tuple[tuple[str, str], ...] = ()
    signal_notes: tuple[tuple[str, str], ...] = ()


_PHM_COLUMNS = (
    ("time", "Row index in this committed public-data slice."),
    (
        "FLOWCOOLFLOWRATE",
        "Coolant flow rate. A sustained drop can indicate a cooling-loop problem.",
    ),
    (
        "FLOWCOOLPRESSURE",
        "Coolant pressure. The configured relationship expects it to move with flow.",
    ),
    ("IONGAUGEPRESSURE", "Ion-gauge pressure; a chamber-condition signal."),
    ("ETCHBEAMVOLTAGE", "Etch beam voltage; an ion-source signal."),
    ("ETCHBEAMCURRENT", "Etch beam current; an ion-source signal."),
)

_PHM_SIGNALS = (
    (
        "FLOWCOOLFLOWRATE",
        "Primary coolant channel. It must be anomalous for the configured candidate.",
    ),
    (
        "FLOWCOOLPRESSURE",
        "Second primary coolant channel. Both coolant channels must move.",
    ),
)

_TEP_COLUMNS = (
    ("time", "Row index in this committed public-data slice."),
    (
        "XMEAS(1)",
        "A feed flow (kscmh). A configured cause channel for the "
        "feed-system candidate.",
    ),
    (
        "XMV(3)",
        "A feed valve position (%). A configured cause channel for the "
        "feed-system candidate.",
    ),
    (
        "XMEAS(7)",
        "Reactor pressure (kPa). A symptom channel used only as corroboration.",
    ),
)

_TEP_SIGNALS = (
    ("XMEAS(1)", "Primary cause channel. It must be anomalous."),
    ("XMV(3)", "Primary cause channel. It must be anomalous."),
    ("XMEAS(7)", "Corroboration only; it cannot substitute for the cause channels."),
)

_RF_COLUMNS = (
    ("time", "Row index in the synthetic export."),
    ("sensor_17", "The configured RF reflectometer signal. It moves in this sample."),
    ("impedance", "A corroborating electrical channel. It stays quiet here."),
    ("thermal", "A corroborating thermal channel. It stays quiet here."),
    ("pressure", "A corroborating pressure channel. It stays quiet here."),
)

_RF_SIGNALS = (
    ("sensor_17", "Primary RF channel. Anomalous in this sample."),
    ("impedance", "Corroborating channel. Quiet in this sample."),
    ("thermal", "Corroborating channel. Quiet in this sample."),
    ("pressure", "Corroborating channel. Quiet in this sample."),
)

_UNKNOWN_COLUMNS = (
    ("time", "Row index in the synthetic export."),
    ("chamber_temp", "Chamber temperature; no configured meaning yet."),
    ("chamber_pressure", "Chamber pressure; no configured meaning yet."),
    ("rf_power", "RF power; no configured meaning yet."),
)


_DEMOS: tuple[DemoCase, ...] = (
    DemoCase(
        key="phm_flowcool_supported",
        label="PHM 2018 dataset — coolant-loop fault",
        csv_path=(
            ROOT
            / "benchmarks"
            / "datasets"
            / "phm2018"
            / "sample"
            / "M02_DC_01_demo_sample.csv"
        ),
        config_path=ROOT / "config" / "sensor_relations" / "ion_mill_phm18.yaml",
        note=(
            "Ion mill alarm during an RF run; the flowcool loop looks abnormal. "
            "Please isolate the cooling subsystem."
        ),
        description=(
            "A public ion-mill dataset. The first rows are normal; the later "
            "window contains the documented coolant-loop fault. Both configured "
            "coolant channels move."
        ),
        expected=(
            "SUPPORTED — the configured coolant-loop candidate passes every "
            "check. Next step: inspect the component."
        ),
        source="Public PHM 2018 dataset sample",
        column_notes=_PHM_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="phm_flowcool_inconclusive",
        label="PHM 2018 dataset — nominal coolant loop",
        csv_path=(
            ROOT
            / "benchmarks"
            / "datasets"
            / "phm2018"
            / "sample"
            / "M02_DC_01_nominal_sample.csv"
        ),
        config_path=ROOT / "config" / "sensor_relations" / "ion_mill_phm18.yaml",
        note="Flowcool loop looks normal; check whether anything moved.",
        description=(
            "The same public ion-mill columns and config, but a nominal window. "
            "The configured channels are present and not anomalous, so the gate "
            "abstains instead of inventing a fault."
        ),
        expected=(
            "INSUFFICIENT — the configured channels are present but normal. "
            "Next step: collect more data."
        ),
        source="Public PHM 2018 dataset sample",
        column_notes=_PHM_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="tep_feed_supported",
        label="TEP dataset — feed-system disturbance",
        csv_path=(
            ROOT / "benchmarks" / "datasets" / "tep" / "sample" / "IDV6_sample.csv"
        ),
        config_path=ROOT / "config" / "sensor_relations" / "tep_reactor.yaml",
        note=(
            "Reactor feed disturbance suspected; A feed flow and valve look off. "
            "Check the feed system."
        ),
        description=(
            "A public Tennessee Eastman Process dataset. The feed flow and feed "
            "valve move together; reactor pressure is corroboration, not a "
            "substitute for the cause channels."
        ),
        expected=(
            "SUPPORTED — the configured feed-system candidate passes every "
            "check. Next step: escalate to an engineer."
        ),
        source="Public TEP dataset sample",
        column_notes=_TEP_COLUMNS,
        signal_notes=_TEP_SIGNALS,
    ),
    DemoCase(
        key="tep_unmodeled",
        label="TEP dataset — unmodeled disturbance",
        csv_path=(
            ROOT / "benchmarks" / "datasets" / "tep" / "sample" / "IDV3_sample.csv"
        ),
        config_path=ROOT / "config" / "sensor_relations" / "tep_reactor.yaml",
        note=(
            "Reactor excursion with a D feed temperature step; the feed flow "
            "itself looks steady."
        ),
        description=(
            "A public Tennessee Eastman Process dataset for a different "
            "disturbance. The reactor is upset, but the configured feed-cause "
            "channels stay normal, so the gate abstains."
        ),
        expected=(
            "INSUFFICIENT — the reactor is upset, but the configured feed-cause "
            "channels stay normal. Next step: collect more data."
        ),
        source="Public TEP dataset sample",
        column_notes=_TEP_COLUMNS,
        signal_notes=_TEP_SIGNALS,
    ),
    DemoCase(
        key="synthetic_flowcool_supported",
        label="Synthetic dataset — coolant-loop fault",
        csv_path=ROOT / "samples" / "flowcool_supported.csv",
        config_path=ROOT / "config" / "sensor_relations" / "ion_mill_phm18.yaml",
        note="Flowcool loop excursion during the RF step.",
        description=(
            "A tiny hand-written synthetic dataset. Both configured coolant "
            "channels move; the model narrative is separate from the gate."
        ),
        expected=(
            "SUPPORTED — the configured coolant-loop candidate passes every "
            "check. Next step: inspect the component."
        ),
        source="Synthetic dataset (not field data)",
        column_notes=_PHM_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="synthetic_flowcool_inconclusive",
        label="Synthetic dataset — nominal coolant loop",
        csv_path=ROOT / "samples" / "flowcool_inconclusive.csv",
        config_path=ROOT / "config" / "sensor_relations" / "ion_mill_phm18.yaml",
        note="Flowcool loop looks normal; check whether anything moved.",
        description=(
            "A tiny hand-written synthetic dataset with the configured channels "
            "present but nominal. The gate asks for more data."
        ),
        expected=(
            "INSUFFICIENT — the configured channels are present but normal. "
            "Next step: collect more data."
        ),
        source="Synthetic dataset (not field data)",
        column_notes=_PHM_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="synthetic_rf_veto",
        label="Synthetic dataset — sensor contradiction",
        csv_path=ROOT / "samples" / "rf_contradiction.csv",
        config_path=ROOT / "config" / "sensor_relations" / "synthetic_twin.yaml",
        note=(
            "RF reflectometer excursion on Chamber B; corroborating channels "
            "look quiet."
        ),
        description=(
            "The RF sensor is anomalous while every configured corroborating "
            "channel is nominal. The Python contradiction rule vetoes the "
            "candidate even if the model tells a story."
        ),
        expected=(
            "VETOED — one sensor moves while every configured corroborating "
            "channel stays quiet. Next step: review the contradiction."
        ),
        source="Synthetic dataset (not field data)",
        column_notes=_RF_COLUMNS,
        signal_notes=_RF_SIGNALS,
    ),
    DemoCase(
        key="unknown_export",
        label="Unknown tool dataset — no matching config",
        csv_path=ROOT / "samples" / "unknown_tool.csv",
        config_path=None,
        note="New tool export; no configured schema yet.",
        description=(
            "No bundled schema matches these columns. The experimental mapping "
            "proposes an unverified channel map, marks the evidence, and offers "
            "a draft config for review."
        ),
        expected=(
            "EXPERIMENTAL — no configured schema matches. Next step: review the "
            "draft mapping; it is unverified."
        ),
        source="Synthetic dataset (not field data)",
        column_notes=_UNKNOWN_COLUMNS,
        signal_notes=(),
    ),
)

DEMO_CASES: dict[str, DemoCase] = {item.key: item for item in _DEMOS}


def demo_case(key: str) -> DemoCase:
    try:
        return DEMO_CASES[key]
    except KeyError as exc:
        raise ValueError(f"unknown demo case: {key}") from exc


__all__ = ["DEMO_CASES", "DemoCase", "demo_case"]
