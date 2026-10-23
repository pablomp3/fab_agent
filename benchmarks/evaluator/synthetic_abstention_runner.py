from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import cast

from benchmarks.evaluator.report import (
    PREDICATE_FIELDS,
    CaseResult,
    W3Report,
    serialize_case,
)
from benchmarks.synthetic_twin.generate_twin import generate_all
from src.config_loader import LoadedRelations, ScenarioConfig, load_relations
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import EvidenceStore
from src.core.pipeline import Candidate, assess_candidate
from src.core.sufficiency import derive_predicates
from src.core.types import Evidence, PredicateSet, SuggestedAction, Verdict

_CASE_IDS = ("B4a", "B4b", "B4c", "B4d")


def _read_object(path: Path) -> dict[str, object]:
    value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"expected a JSON object in {path}")
    return cast(dict[str, object], value)


def _evaluate_case(root: Path, case_id: str, config: ScenarioConfig) -> CaseResult:
    dossier = root / "benchmarks/synthetic_twin/cases" / case_id
    evidence = extract_evidence(dossier / "telemetry.csv", config.signals)
    if not evidence:
        raise ValueError(f"{case_id} produced no evidence")
    for spec, item in zip(config.signals, evidence, strict=True):
        if (
            spec.threshold_source
            and f"source={spec.threshold_source}" not in item.provenance
        ):
            raise ValueError(f"{case_id} evidence omits threshold provenance")
    store = EvidenceStore(evidence)
    evidence_by_signal = {
        item.signal: item for item in evidence if item.signal is not None
    }
    cited_ids: list[str] = []
    for signal in config.candidate.cited_signals:
        item = evidence_by_signal.get(signal)
        if item is None:
            raise ValueError(f"{case_id} citation signal is unavailable: {signal}")
        cited_ids.append(item.evidence_id)
    candidate = Candidate(
        claim=config.candidate.claim,
        hypothesis_class=config.candidate.hypothesis_class,
        cited_evidence=tuple(cited_ids),
    )
    assessment = assess_candidate(
        candidate, store, config.predicate_config, config.rules
    )
    predicates = derive_predicates(store, config.predicate_config)
    truth_path = (
        root / "benchmarks/evaluator/ground_truths" / f"{case_id}_ground_truth.json"
    )
    truth = _read_object(truth_path)
    passed = _matches_truth(
        case_id,
        truth,
        assessment.constraints.verdict,
        assessment.suggested_next_action,
        predicates,
        evidence,
    )
    return CaseResult(
        case_id,
        candidate,
        assessment.constraints.verdict,
        assessment.suggested_next_action,
        predicates,
        assessment.constraints,
        evidence,
        passed,
    )


def _matches_truth(
    case_id: str,
    truth: dict[str, object],
    verdict: Verdict,
    action: SuggestedAction,
    predicates: PredicateSet,
    evidence: tuple[Evidence, ...],
) -> bool:
    if truth.get("case_id") != case_id:
        raise ValueError(f"ground truth case id mismatch for {case_id}")
    expected_verdict = truth.get("expected_verdict")
    allowed = truth.get("allowed_actions")
    expected_predicates = truth.get("expected_predicates")
    if not isinstance(allowed, list) or not isinstance(expected_predicates, dict):
        raise ValueError(f"malformed ground truth for {case_id}")
    if verdict.value != expected_verdict or action.value not in allowed:
        return False
    predicate_map = {name: getattr(predicates, name) for name in PREDICATE_FIELDS}
    for name, expected in expected_predicates.items():
        if name not in predicate_map or not isinstance(expected, bool):
            raise ValueError(f"invalid predicate expectation in {case_id}: {name}")
        if predicate_map[name] is not expected:
            return False
    return _evidence_matches(truth.get("expected_evidence"), evidence)


def _evidence_matches(expected: object, evidence: tuple[Evidence, ...]) -> bool:
    if not isinstance(expected, dict):
        raise ValueError("ground truth expected_evidence must be an object")
    actual = {item.signal: item for item in evidence if item.signal is not None}
    for signal, expectation_obj in expected.items():
        if not isinstance(signal, str) or not isinstance(expectation_obj, dict):
            raise ValueError("malformed expected evidence entry")
        item = actual.get(signal)
        kinds = expectation_obj.get("allowed_kinds")
        if item is None or not isinstance(kinds, list) or item.kind.value not in kinds:
            return False
        maximum = expectation_obj.get("max_robust_z_exclusive")
        if maximum is not None and (
            item.value is None
            or not isinstance(maximum, int | float)
            or isinstance(maximum, bool)
            or item.value >= maximum
        ):
            return False
        target = expectation_obj.get("target_robust_z")
        if target is not None and (
            item.value is None
            or isinstance(target, bool)
            or not isinstance(target, int | float)
            or not math.isclose(item.value, target, rel_tol=0.0, abs_tol=1e-6)
        ):
            return False
        zero_when_evaluated = expectation_obj.get("max_robust_z_when_evaluated")
        if item.kind.value == "SENSOR_NOMINAL" and zero_when_evaluated is not None:
            if item.value != zero_when_evaluated:
                return False
    return True


def run_w3(root: Path, config_path: Path | None = None) -> W3Report:
    """Run B4 abstention checks using only seeded data and deterministic Python."""
    project_root = Path(__file__).resolve().parents[2]
    configuration = (
        config_path or project_root / "config/sensor_relations/synthetic_twin.yaml"
    )
    generated = generate_all(root, configuration)
    if tuple(item.case_id for item in generated) != _CASE_IDS:
        raise ValueError("generator did not produce the complete adversarial suite")
    relations: LoadedRelations = load_relations(configuration)
    if tuple(relations.scenarios) != _CASE_IDS:
        raise ValueError(
            "configuration does not declare exactly B4a through B4d in order"
        )
    cases = tuple(
        _evaluate_case(root, case_id, relations.scenarios[case_id])
        for case_id in _CASE_IDS
    )
    report = W3Report(
        cases=cases, llm_calls=0, passed=all(case.passed for case in cases)
    )
    result_path = root / "benchmarks/evaluator/results/w3_adversarial_check.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "gate": "W3",
        "passed": report.passed,
        "llm_calls": report.llm_calls,
        "configuration": str(configuration),
        "cases": [serialize_case(case) for case in report.cases],
    }
    result_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    report = run_w3(root)
    status = "GREEN" if report.passed and report.llm_calls == 0 else "FAIL"
    print(f"W3: {status} (cases={len(report.cases)}, llm_calls={report.llm_calls})")
    for case in report.cases:
        print(
            f"{case.case_id}: {case.verdict.value} / "
            f"{case.suggested_next_action.value} passed={case.passed}"
        )
    return 0 if status == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
