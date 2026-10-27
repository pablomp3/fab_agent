from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RealDataCase:
    case_id: str
    csv_path: Path
    nominal_baseline_path: Path
    expected_verdict: str
    expected_actions: tuple[str, ...]
    subsystem: str | None


@dataclass(frozen=True, slots=True)
class RealDataSuite:
    name: str
    config_path: Path
    cases: tuple[RealDataCase, ...]


def tep_suite(root: Path) -> RealDataSuite:
    processed = root / "benchmarks" / "datasets" / "tep" / "processed"
    # Only IDV 1, 2, and 6 visibly disturb the configured feed-system cause
    # signals (XMEAS(1) and XMV(3)). The other evaluable IDVs do not match the
    # configured relationship and should abstain.
    supported = (1, 2, 6)
    insufficient = (4, 5, 7, 14, 15, 3, 9)
    cases: list[RealDataCase] = []
    for idv in supported + insufficient:
        cases.append(
            RealDataCase(
                case_id=f"IDV{idv}",
                csv_path=processed / f"IDV{idv}.csv",
                nominal_baseline_path=processed / f"IDV{idv}_nominal.csv",
                expected_verdict=("SUPPORTED" if idv in supported else "INSUFFICIENT"),
                expected_actions=("ESCALATE_TO_ENGINEER",),
                subsystem="feed_system",
            )
        )
    return RealDataSuite(
        name="TEP Reactor",
        config_path=root / "config" / "sensor_relations" / "tep_reactor.yaml",
        cases=tuple(cases),
    )


def phm_suite(root: Path) -> RealDataSuite:
    processed = root / "benchmarks" / "datasets" / "phm2018" / "processed"
    nominal = root / "benchmarks" / "datasets" / "phm2018" / "sample"
    return RealDataSuite(
        name="PHM 2018 Ion Mill",
        config_path=root / "config" / "sensor_relations" / "ion_mill_phm18.yaml",
        cases=(
            RealDataCase(
                case_id="M02_DC_01",
                csv_path=processed / "01_M02_DC_score.csv",
                nominal_baseline_path=nominal / "M02_DC_01_nominal_sample.csv",
                expected_verdict="INSUFFICIENT",
                expected_actions=("ESCALATE_TO_ENGINEER",),
                subsystem="flowcool",
            ),
        ),
    )
