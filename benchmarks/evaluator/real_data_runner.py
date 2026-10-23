from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

from benchmarks.evaluator.real_data_fixtures import (
    RealDataCase,
    RealDataSuite,
    phm_suite,
    tep_suite,
)
from benchmarks.evaluator.report import CaseResult, serialize_case
from src.config_loader import LoadedRelations, load_relations
from src.config_types import CandidateConfig, ScenarioConfig
from src.core.constraints import ConstraintRule
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import EvidenceStore
from src.core.pipeline import Candidate, assess_candidate
from src.core.sufficiency import PredicateConfig, derive_predicates
from src.core.types import Predicate, SignalSpec
from src.schemas.models import RootCauseCategory

_ROBUST_Z_THRESHOLD = 3.5
_THRESHOLD_SOURCE_PREFIX = f"standard_robust_mad_multiplier={_ROBUST_Z_THRESHOLD}"


def build_scenario(case: RealDataCase, domain: LoadedRelations) -> ScenarioConfig:
    if domain.name == "tep_reactor":
        return _build_tep_scenario(case, domain)
    if domain.name == "ion_mill_phm18":
        return _build_phm_scenario(case, domain)
    raise ValueError(f"unsupported domain: {domain.name}")


def _build_tep_scenario(case: RealDataCase, domain: LoadedRelations) -> ScenarioConfig:
    cause = domain.roles["cause"]
    symptom = domain.roles["symptom"]
    signals = tuple(
        SignalSpec(
            name=spec.name,
            unit=spec.unit,
            robust_z_threshold=_ROBUST_Z_THRESHOLD,
            threshold_source=f"{_THRESHOLD_SOURCE_PREFIX};nominal_baseline:{case.nominal_baseline_path}",
        )
        for spec in domain.signals
    )
    predicates = PredicateConfig(
        primary_signals=frozenset(cause),
        corroboration_signals=frozenset(symptom),
    )
    rules = {
        "feed_disturbance": ConstraintRule(
            require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY}),
            forbid_any=frozenset({Predicate.HAS_MISSING_REQUIRED_EVIDENCE}),
            veto_if_any=frozenset(),
        )
    }
    return ScenarioConfig(
        signals=signals,
        predicate_config=predicates,
        rules=rules,
        candidate=CandidateConfig(
            claim="A feed disturbance",
            hypothesis_class="feed_disturbance",
            cited_signals=cause + symptom,
        ),
    )


def _build_phm_scenario(case: RealDataCase, domain: LoadedRelations) -> ScenarioConfig:
    subsystem = cast(str, case.subsystem)
    subsystem_signals = domain.groups[subsystem]
    signals = tuple(
        SignalSpec(
            name=spec.name,
            unit=spec.unit,
            robust_z_threshold=_ROBUST_Z_THRESHOLD,
            threshold_source=f"{_THRESHOLD_SOURCE_PREFIX};nominal_baseline:{case.nominal_baseline_path}",
        )
        for spec in domain.signals
    )
    predicates = PredicateConfig(
        primary_signals=frozenset(subsystem_signals),
    )
    rules = {
        "equipment_fault": ConstraintRule(
            require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY}),
            forbid_any=frozenset({Predicate.HAS_MISSING_REQUIRED_EVIDENCE}),
            veto_if_any=frozenset(),
        )
    }
    return ScenarioConfig(
        signals=signals,
        predicate_config=predicates,
        rules=rules,
        candidate=CandidateConfig(
            claim=f"{case.subsystem} subsystem fault",
            hypothesis_class="equipment_fault",
            cited_signals=subsystem_signals,
            root_cause=RootCauseCategory.EQUIPMENT_FAULT,
            failure_mode=(
                "Subsystem fault; confirm the specific mode during inspection."
            ),
            mechanism=(
                "Configured subsystem relationship; the physical mechanism is "
                "not asserted."
            ),
        ),
        supported_action=domain.scenarios[subsystem].supported_action,
    )


def evaluate_case(
    root: Path, case: RealDataCase, domain: LoadedRelations
) -> CaseResult:
    scenario = build_scenario(case, domain)
    evidence = extract_evidence(case.csv_path, scenario.signals)
    store = EvidenceStore(evidence)
    evidence_by_signal = {
        item.signal: item for item in evidence if item.signal is not None
    }
    cited_ids: list[str] = []
    for signal in scenario.candidate.cited_signals:
        item = evidence_by_signal.get(signal)
        if item is None:
            raise ValueError(f"{case.case_id} citation signal is unavailable")
        cited_ids.append(item.evidence_id)
    candidate = Candidate(
        claim=scenario.candidate.claim,
        hypothesis_class=scenario.candidate.hypothesis_class,
        cited_evidence=tuple(cited_ids),
    )
    assessment = assess_candidate(
        candidate,
        store,
        scenario.predicate_config,
        scenario.rules,
        scenario.supported_action,
    )
    predicates = derive_predicates(store, scenario.predicate_config)
    passed = (
        assessment.constraints.verdict.value == case.expected_verdict
        and assessment.suggested_next_action.value in case.expected_actions
    )
    return CaseResult(
        case_id=case.case_id,
        candidate=candidate,
        verdict=assessment.constraints.verdict,
        suggested_next_action=assessment.suggested_next_action,
        predicates=predicates,
        constraints=assessment.constraints,
        evidence=evidence,
        passed=passed,
    )


def _run_suite(root: Path, suite: RealDataSuite) -> dict[str, object]:
    domain = load_relations(suite.config_path)
    cases = [evaluate_case(root, case, domain) for case in suite.cases]
    passed = all(case.passed for case in cases)
    return {
        "suite": suite.name,
        "configuration": str(suite.config_path),
        "passed": passed,
        "cases": [serialize_case(case) for case in cases],
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    results_dir = root / "benchmarks" / "evaluator" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    phm_result = _run_suite(root, phm_suite(root))
    tep_result = _run_suite(root, tep_suite(root))

    payload = {
        "gate": "W5",
        "timestamp": "2026-10-03",
        "suites": [phm_result, tep_result],
    }
    result_path = results_dir / "w5_real_data_check.json"
    result_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"W5 artifact written to {result_path}")
    suites = cast(list[dict[str, object]], payload["suites"])
    for suite in suites:
        print(
            f"{suite['suite']}: passed={suite['passed']} "
            f"cases={len(cast(list[object], suite['cases']))}"
        )
        for case in cast(list[dict[str, object]], suite["cases"]):
            print(
                f"  {case['case_id']}: {case['verdict']} / "
                f"{case['suggested_next_action']} passed={case['passed']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
