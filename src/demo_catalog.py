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
    ("time", "Row index"),
    ("Tool", "Machine ID"),
    ("stage", "Process stage"),
    ("Lot", "Wafer lot ID"),
    ("runnum", "Run sequence"),
    ("recipe", "Recipe number"),
    ("recipe_step", "Step number"),
    ("IONGAUGEPRESSURE", "Chamber pressure"),
    ("ETCHBEAMVOLTAGE", "Beam voltage"),
    ("ETCHBEAMCURRENT", "Beam current"),
    ("ETCHSUPPRESSORVOLTAGE", "Suppressor voltage"),
    ("ETCHSUPPRESSORCURRENT", "Suppressor current"),
    ("FLOWCOOLFLOWRATE", "Coolant flow"),
    ("FLOWCOOLPRESSURE", "Coolant pressure"),
    ("ETCHGASCHANNEL1READBACK", "Gas 1 flow"),
    ("ETCHPBNGASREADBACK", "Purge gas flow"),
    ("FIXTURETILTANGLE", "Tilt angle"),
    ("ROTATIONSPEED", "Rotation speed"),
    ("ACTUALROTATIONANGLE", "Rotation angle"),
    ("FIXTURESHUTTERPOSITION", "Shutter state"),
    ("ETCHSOURCEUSAGE", "Source usage"),
    ("ETCHAUXSOURCETIMER", "Auxiliary timer"),
    ("ETCHAUX2SOURCETIMER", "Auxiliary timer 2"),
    ("ACTUALSTEPDURATION", "Step duration"),
)

_SYNTHETIC_FLOWCOOL_COLUMNS = (
    ("time", "Row index"),
    ("FLOWCOOLFLOWRATE", "Coolant flow"),
    ("FLOWCOOLPRESSURE", "Coolant pressure"),
)

_PHM_SIGNALS = (
    ("FLOWCOOLFLOWRATE", "Coolant flow channel"),
    ("FLOWCOOLPRESSURE", "Coolant pressure channel"),
)

_TEP_COLUMNS = (
    ("time", "Row index"),
    ("XMEAS(1)", "Feed flow"),
    ("XMV(3)", "Feed valve"),
    ("XMEAS(7)", "Reactor pressure"),
)

_TEP_SIGNALS = (
    ("XMEAS(1)", "Primary feed flow"),
    ("XMV(3)", "Primary feed valve"),
    ("XMEAS(7)", "Corroborating reactor pressure"),
)

_RF_COLUMNS = (
    ("time", "Row index"),
    ("sensor_17", "RF power"),
    ("impedance", "Chamber impedance"),
    ("thermal", "Chamber temperature"),
    ("pressure", "Chamber pressure"),
)

_RF_SIGNALS = (
    ("sensor_17", "Primary RF power"),
    ("impedance", "Backup impedance"),
    ("thermal", "Backup temperature"),
    ("pressure", "Backup pressure"),
)

_UNKNOWN_COLUMNS = (
    ("time", "Row index"),
    ("chamber_temp", "Chamber temperature"),
    ("chamber_pressure", "Chamber pressure"),
    ("rf_power", "RF power"),
)


_DEMOS: tuple[DemoCase, ...] = (
    DemoCase(
        key="phm_flowcool_supported",
        label="PHM 2018 dataset — Coolant Fault 🟠 [Needs Review]",
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
            "Real public ion-mill etching tool dataset. The later time window "
            "contains a documented coolant-loop fault where both coolant flow "
            "and coolant pressure drop simultaneously. Several other declared "
            "channels also move, so the result is not a bare confirmation."
        ),
        expected=(
            "Result: Needs Review — the coolant check passed, but large anomalies "
            "outside that check remain unexplained. Next step: ask an engineer to "
            "review."
        ),
        source="Public PHM 2018 dataset sample",
        column_notes=_PHM_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="phm_flowcool_inconclusive",
        label="PHM 2018 dataset — Normal Run 🟢 [Regular Behavior]",
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
            "The same public ion-mill tool during healthy production. The "
            "sensors are present and stay within normal limits, so FabAgent "
            "reports Regular Behavior instead of inventing a false alarm."
        ),
        expected=(
            "Result: Regular Behavior — every checked signal stayed below its "
            "alert threshold. Next step: keep monitoring."
        ),
        source="Public PHM 2018 dataset sample",
        column_notes=_PHM_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="tep_feed_supported",
        label="TEP dataset — Feed Disturbance 🔴 [Fault Confirmed]",
        csv_path=(
            ROOT / "benchmarks" / "datasets" / "tep" / "sample" / "IDV6_sample.csv"
        ),
        config_path=ROOT / "config" / "sensor_relations" / "tep_reactor.yaml",
        note=(
            "Reactor feed disturbance suspected; A feed flow and reactor pressure "
            "look off. Check the feed system."
        ),
        description=(
            "Real Tennessee Eastman chemical reactor benchmark. Feed flow and "
            "reactor pressure move abnormally together; the valve position is "
            "recorded but is not part of this check."
        ),
        expected=(
            "Result: Fault Confirmed — both configured pattern channels moved. "
            "Next step: ask an engineer to review."
        ),
        source="Public TEP dataset sample",
        column_notes=_TEP_COLUMNS,
        signal_notes=_TEP_SIGNALS,
    ),
    DemoCase(
        key="tep_unmodeled",
        label="TEP dataset — Unmodeled Disturbance 🟠 [Needs Review]",
        csv_path=(
            ROOT / "benchmarks" / "datasets" / "tep" / "sample" / "IDV3_sample.csv"
        ),
        config_path=ROOT / "config" / "sensor_relations" / "tep_reactor.yaml",
        note=(
            "Reactor excursion with a D feed temperature step; the feed flow "
            "itself looks steady."
        ),
        description=(
            "A different TEP disturbance (temperature step). Reactor pressure "
            "moved outside its normal range, but no saved feed-system check "
            "explains it. FabAgent asks for a human review instead of calling "
            "this run normal."
        ),
        expected=(
            "Result: Needs Review — a signal moved without a saved check "
            "explaining it. Next step: ask an engineer to review."
        ),
        source="Public TEP dataset sample",
        column_notes=_TEP_COLUMNS,
        signal_notes=_TEP_SIGNALS,
    ),
    DemoCase(
        key="synthetic_flowcool_supported",
        label="Synthetic dataset — Coolant Fault 🔴 [Fault Confirmed]",
        csv_path=ROOT / "samples" / "flowcool_supported.csv",
        config_path=ROOT / "config" / "sensor_relations" / "synthetic_flowcool.yaml",
        note="Flowcool loop excursion during the RF step.",
        description=(
            "Compact synthetic testbed with known mathematical ground truth. "
            "Both primary coolant channels exceed the 3.5z threshold."
        ),
        expected=(
            "Result: Fault Confirmed — clean positive control. "
            "Next step: inspect the part."
        ),
        source="Synthetic dataset (seeded ground truth)",
        column_notes=_SYNTHETIC_FLOWCOOL_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="synthetic_flowcool_inconclusive",
        label="Synthetic dataset — Normal Run 🟢 [Regular Behavior]",
        csv_path=ROOT / "samples" / "flowcool_inconclusive.csv",
        config_path=ROOT / "config" / "sensor_relations" / "synthetic_flowcool.yaml",
        note="Flowcool loop looks normal; check whether anything moved.",
        description=(
            "Compact synthetic testbed with all sensors in quiet baseline state. "
            "Demonstrates zero-LLM mathematical abstention."
        ),
        expected=(
            "Result: Regular Behavior — every checked signal stayed below its "
            "alert threshold. Next step: keep monitoring."
        ),
        source="Synthetic dataset (seeded ground truth)",
        column_notes=_SYNTHETIC_FLOWCOOL_COLUMNS,
        signal_notes=_PHM_SIGNALS,
    ),
    DemoCase(
        key="synthetic_rf_veto",
        label="Synthetic dataset — Sensor Conflict 🟡 [Sensors Disagree]",
        csv_path=ROOT / "samples" / "rf_contradiction.csv",
        config_path=ROOT / "config" / "sensor_relations" / "synthetic_rf.yaml",
        note=(
            "RF reflectometer excursion on Chamber B; corroborating channels "
            "look quiet."
        ),
        description=(
            "The primary RF sensor spikes to 12z while redundant electrical, "
            "thermal, and pressure sensors stay flat. A naive LLM falsely halts "
            "the chamber; FabAgent triggers a hard veto for sensor contradiction."
        ),
        expected=(
            "Result: Sensors Disagree — primary sensor spiked but backup stayed "
            "flat. Next step: check the sensor first."
        ),
        source="Synthetic dataset (seeded ground truth)",
        column_notes=_RF_COLUMNS,
        signal_notes=_RF_SIGNALS,
    ),
    DemoCase(
        key="unknown_export",
        label="Unknown tool dataset — No Config ⚪ [Unknown Machine]",
        csv_path=ROOT / "samples" / "unknown_tool.csv",
        config_path=None,
        note="New tool export; no configured schema yet.",
        description=(
            "No bundled schema matches these columns. The experimental mapping "
            "proposes an unverified channel map, marks the evidence, and offers "
            "a draft config for review."
        ),
        expected=(
            "Result: Unknown Machine — review the guessed columns and save a "
            "tool model."
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
