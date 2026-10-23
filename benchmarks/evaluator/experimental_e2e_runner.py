from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.config_loader import load_relations
from src.core.types import EvidenceKind
from src.experimental import ExperimentalResult, analyze_experimental
from src.model_config import load_model_route

MODELS_CONFIG_NAME = "config/models.yaml"
DEFAULT_CSV = "benchmarks/datasets/phm2018/sample/M02_DC_01_sample.csv"
OFFLINE_RESULT_NAME = "benchmarks/evaluator/results/experimental_phm_check_offline.json"
LIVE_RESULT_NAME = "benchmarks/evaluator/results/experimental_phm_check.json"
ENGINEER_NOTE = (
    "New export from a tool with no configured schema. We do not know the "
    "channels yet; asked for a low-integration look."
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def run_experimental(
    *,
    offline: bool,
    csv_relative: str = DEFAULT_CSV,
    max_tokens: int = 768,
) -> dict[str, object]:
    root = _project_root()
    model = load_model_route(root / MODELS_CONFIG_NAME, "SYNTHESIS", {}).model
    if offline:
        transport = ExperimentalEchoTransport()
        result: ExperimentalResult = analyze_experimental(
            root / csv_relative,
            ENGINEER_NOTE,
            engine_factory=offline_engine_factory(transport),
            mapping_factory=offline_mapping_factory(transport),
            max_tokens=max_tokens,
        )
        llm_calls = 0
    else:
        result = analyze_experimental(
            root / csv_relative,
            ENGINEER_NOTE,
            max_tokens=max_tokens,
        )
        llm_calls = 2
    anomalies = [
        item for item in result.evidence if item.kind is EvidenceKind.SENSOR_ANOMALY
    ]
    mapping = result.mapping
    return {
        "gate": "B-experimental",
        "case_id": "experimental_low_integration",
        "mode": "offline" if offline else "live",
        "input": csv_relative,
        "model": model,
        "llm_calls": llm_calls,
        "candidate_count": len(result.candidates),
        "outcome": result.outcome.value,
        "detail": result.detail,
        "analysis_performed": result.analysis_performed,
        "model_called": result.model_called,
        "mapping_signal_count": 0 if mapping is None else len(mapping.signals),
        "relationship_count": 0 if mapping is None else len(mapping.relationships),
        "evidence_count": len(result.evidence),
        "anomaly_count": len(anomalies),
        "unverified_tagged": all(
            "unverified_mapping" in item.provenance for item in result.evidence
        ),
        "draft_config_valid": _draft_is_loadable(result.draft_yaml),
        "draft_yaml": result.draft_yaml,
        "suggested_next_action": result.output.suggested_next_action.value,
        "any_supported": any(
            item.status.value == "SUPPORTED" for item in result.output.hypotheses
        ),
        "hypotheses": [
            {
                "hypothesis_class": item.hypothesis_class,
                "status": item.status.value,
                "root_cause": item.root_cause.value,
            }
            for item in result.output.hypotheses
        ],
    }


def main(argv: list[str]) -> int:
    root = _project_root()
    offline = "--live" not in argv
    csv_relative = DEFAULT_CSV
    for index, argument in enumerate(argv):
        if argument == "--csv" and index + 1 < len(argv):
            csv_relative = argv[index + 1]
    report = run_experimental(offline=offline, csv_relative=csv_relative)
    path = root / (OFFLINE_RESULT_NAME if offline else LIVE_RESULT_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Experimental [{report['mode']}] outcome={report['outcome']} "
        f"candidates={report['candidate_count']} "
        f"signals={report['mapping_signal_count']} "
        f"relationships={report['relationship_count']} "
        f"evidence={report['evidence_count']} "
        f"anomalies={report['anomaly_count']} "
        f"draft_ok={report['draft_config_valid']} "
        f"action={report['suggested_next_action']}"
    )
    print(f"artifact={path}")
    if report["outcome"] == "INPUT_UNREADABLE":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
