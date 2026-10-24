from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.agents.mapping_request import DEFAULT_MAPPING_MAX_TOKENS
from src.agents.proposal_request import DEFAULT_MAX_TOKENS
from src.config_loader import load_relations
from src.core.types import EvidenceKind
from src.dossier import DossierResult, analyze_dossier
from src.experimental import ExperimentalResult, analyze_experimental
from src.schemas.models import RCAOutputModel

OFFLINE_RESULT_NAME = "benchmarks/evaluator/results/e2e_suite_offline.json"
LIVE_RESULT_NAME = "benchmarks/evaluator/results/e2e_suite_live.json"

PHM_NOTE = (
    "Ion mill alarm during an RF run; the flowcool loop looks abnormal. "
    "Please isolate the cooling subsystem."
)
TEP_FEED_NOTE = (
    "Reactor feed disturbance suspected; A feed flow and valve look off. "
    "Check the feed system."
)
TEP_ABSTAIN_NOTE = (
    "Reactor excursion with a D feed temperature step; the feed flow itself "
    "looks steady."
)
B4A_NOTE = (
    "Sensor spike on the RF generator with the other channels still nominal; "
    "possible instrumentation contradiction."
)


@dataclass(frozen=True, slots=True)
class SuiteCase:
    case_id: str
    csv_relative: str
    source: str
    note: str
    expected_safe_outcome: str | None
    expected_experimental_outcome: str
    expectation_note: str


def default_cases() -> tuple[SuiteCase, ...]:
    """Three or more consistent end-to-end cases across real and synthetic data.

    Each case is run through **both** paths: the configured safe path
    (``analyze_dossier``) and the no-config experimental path
    (``analyze_experimental``). Add a case by appending a ``SuiteCase``.
    Expectations are advisory: a mismatch is recorded, not raised, so the
    artifact stays useful when the live model behaves differently.
    """
    return (
        SuiteCase(
            case_id="phm2018_flowcool",
            csv_relative=(
                "benchmarks/datasets/phm2018/sample/M02_DC_01_sample.csv"
            ),
            source="real_public_benchmark",
            note=PHM_NOTE,
            # The committed 1,000-row sample is centered on the fault, so the
            # robust baseline shifts with the excursion and no channel exceeds
            # 3.5 in that window; the safe path abstains. The full-file W5 run
            # (`w5_real_data_check.json`) is SUPPORTED. This is a deliberate
            # windowing note, not a regression.
            expected_safe_outcome="ANALYSIS_INCONCLUSIVE",
            expected_experimental_outcome="EXPERIMENTAL_UNVERIFIED_MAPPING",
            expectation_note=(
                "fault-centered sample window; full-file W5 run is SUPPORTED"
            ),
        ),
        SuiteCase(
            case_id="tep_idv6_feed",
            csv_relative="benchmarks/datasets/tep/sample/IDV6_sample.csv",
            source="real_public_benchmark",
            note=TEP_FEED_NOTE,
            # The product TEP scenario declares the feed-system cause channels.
            # IDV 6 moves them, so the safe path supports the configured
            # candidate; the experimental path still maps the channels.
            expected_safe_outcome="ANALYSIS_SUPPORTED",
            expected_experimental_outcome="EXPERIMENTAL_UNVERIFIED_MAPPING",
            expectation_note="feed-system cause channels move; safe path supports",
        ),
        SuiteCase(
            case_id="tep_idv3_abstain",
            csv_relative="benchmarks/datasets/tep/sample/IDV3_sample.csv",
            source="real_public_benchmark",
            note=TEP_ABSTAIN_NOTE,
            # The same scenario is present, but the configured cause channels
            # stay nominal for this disturbance, so the safe path abstains.
            expected_safe_outcome="ANALYSIS_INCONCLUSIVE",
            expected_experimental_outcome="EXPERIMENTAL_UNVERIFIED_MAPPING",
            expectation_note="non-modeled disturbance; safe path abstains",
        ),
        SuiteCase(
            case_id="synthetic_twin_b4a",
            csv_relative="benchmarks/synthetic_twin/cases/B4a/telemetry.csv",
            source="synthetic_twin",
            note=B4A_NOTE,
            # The safe path triages to synthetic_twin_v1/B4a and vetoes the
            # adversarial instrumentation contradiction. This is a synthetic
            # control, never field validation (anti-goal D4).
            expected_safe_outcome="ANALYSIS_CONTRADICTED",
            expected_experimental_outcome="EXPERIMENTAL_UNVERIFIED_MAPPING",
            expectation_note=(
                "synthetic adversarial case; VETOED is the injected expectation"
            ),
        ),
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _hypotheses(output: RCAOutputModel) -> list[dict[str, object]]:
    return [
        {
            "hypothesis_class": item.hypothesis_class,
            "status": item.status.value,
            "root_cause": item.root_cause.value,
            "veto_reason": item.veto_reason,
        }
        for item in output.hypotheses
    ]


def _safe_summary(result: DossierResult, expected: str | None) -> dict[str, object]:
    outcome = result.outcome.value
    return {
        "outcome": outcome,
        "detail": result.detail,
        "analysis_performed": result.analysis_performed,
        "model_called": result.model_called,
        "selected_config": (
            None if result.selection is None else result.selection.config_name
        ),
        "selected_scenario": (
            None if result.selection is None else result.selection.scenario_name
        ),
        "evidence_count": len(result.evidence),
        "suggested_next_action": result.output.suggested_next_action.value,
        "any_supported": any(
            item.status.value == "SUPPORTED" for item in result.output.hypotheses
        ),
        "any_vetoed": any(
            item.status.value == "VETOED" for item in result.output.hypotheses
        ),
        "hypotheses": _hypotheses(result.output),
        "expected_outcome": expected,
        "matched_expectation": None if expected is None else outcome == expected,
    }


def _draft_is_loadable(draft_yaml: str | None) -> bool:
    if draft_yaml is None:
        return False
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "draft.yaml"
        path.write_text(draft_yaml, encoding="utf-8")
        try:
            load_relations(path)
        except ValueError:
            return False
    return True


def _experimental_summary(
    result: ExperimentalResult, expected: str
) -> dict[str, object]:
    mapping = result.mapping
    anomalies = [
        item for item in result.evidence if item.kind is EvidenceKind.SENSOR_ANOMALY
    ]
    return {
        "outcome": result.outcome.value,
        "detail": result.detail,
        "analysis_performed": result.analysis_performed,
        "model_called": result.model_called,
        "candidate_count": len(result.candidates),
        "mapping_signal_count": 0 if mapping is None else len(mapping.signals),
        "relationship_count": 0 if mapping is None else len(mapping.relationships),
        "evidence_count": len(result.evidence),
        "anomaly_count": len(anomalies),
        "unverified_tagged": bool(result.evidence)
        and all("unverified_mapping" in item.provenance for item in result.evidence),
        "draft_config_valid": _draft_is_loadable(result.draft_yaml),
        "suggested_next_action": result.output.suggested_next_action.value,
        "any_supported": any(
            item.status.value == "SUPPORTED" for item in result.output.hypotheses
        ),
        "hypotheses": _hypotheses(result.output),
        "expected_outcome": expected,
        "matched_expectation": result.outcome.value == expected,
    }


def run_case(case: SuiteCase, *, offline: bool, max_tokens: int) -> dict[str, object]:
    root = _project_root()
    csv_path = root / case.csv_relative
    if offline:
        transport = ExperimentalEchoTransport()
        safe: DossierResult = analyze_dossier(
            csv_path,
            case.note,
            max_tokens=max_tokens,
            engine_factory=offline_engine_factory(transport),
        )
        experimental: ExperimentalResult = analyze_experimental(
            csv_path,
            case.note,
            engine_factory=offline_engine_factory(transport),
            mapping_factory=offline_mapping_factory(transport),
            max_tokens=DEFAULT_MAPPING_MAX_TOKENS,
        )
    else:
        safe = analyze_dossier(csv_path, case.note, max_tokens=max_tokens)
        experimental = analyze_experimental(
            csv_path, case.note, max_tokens=DEFAULT_MAPPING_MAX_TOKENS
        )
    return {
        "case_id": case.case_id,
        "source": case.source,
        "csv": case.csv_relative,
        "expectation_note": case.expectation_note,
        "safe_path": _safe_summary(safe, case.expected_safe_outcome),
        "experimental_path": _experimental_summary(
            experimental, case.expected_experimental_outcome
        ),
    }


def run_suite(
    *,
    offline: bool,
    case_ids: tuple[str, ...] | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, object]:
    cases = default_cases()
    if case_ids is not None:
        wanted = set(case_ids)
        cases = tuple(case for case in cases if case.case_id in wanted)
    results = [run_case(case, offline=offline, max_tokens=max_tokens) for case in cases]
    safe_matches = [
        item["safe_path"]["matched_expectation"]
        for item in results
        if item["safe_path"]["matched_expectation"] is not None
    ]
    experimental_matches = [
        item["experimental_path"]["matched_expectation"] for item in results
    ]
    return {
        "gate": "E2E-suite",
        "mode": "offline" if offline else "live",
        "llm_calls": 0 if offline else 3 * len(results),
        "case_count": len(results),
        "cases": results,
        "safe_expectations_checked": len(safe_matches),
        "safe_expectations_matched": sum(1 for item in safe_matches if item),
        "experimental_expectations_matched": sum(
            1 for item in experimental_matches if item
        ),
        "all_expectations_matched": all(safe_matches)
        and all(experimental_matches),
    }


def main(argv: list[str]) -> int:
    root = _project_root()
    offline = "--live" not in argv
    case_ids: list[str] = []
    for index, argument in enumerate(argv):
        if argument == "--case" and index + 1 < len(argv):
            case_ids.append(argv[index + 1])
    report = run_suite(
        offline=offline,
        case_ids=tuple(case_ids) if case_ids else None,
    )
    path = root / (OFFLINE_RESULT_NAME if offline else LIVE_RESULT_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"E2E suite [{report['mode']}] cases={report['case_count']}")
    for item in report["cases"]:
        safe = item["safe_path"]
        exp = item["experimental_path"]
        print(
            f"  {item['case_id']}: "
            f"safe={safe['outcome']}({safe['selected_config']}/"
            f"{safe['selected_scenario']}) "
            f"exp={exp['outcome']} signals={exp['mapping_signal_count']} "
            f"anomalies={exp['anomaly_count']} "
            f"draft_ok={exp['draft_config_valid']}"
        )
    print(
        f"expectations: safe {report['safe_expectations_matched']}/"
        f"{report['safe_expectations_checked']}, experimental "
        f"{report['experimental_expectations_matched']}/{report['case_count']}"
    )
    print(f"artifact={path}")
    return 0 if report["all_expectations_matched"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
