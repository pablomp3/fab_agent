from __future__ import annotations

from dataclasses import dataclass

from src.core.constraints import ConstraintResult
from src.core.pipeline import Candidate
from src.core.types import Evidence, PredicateSet, SuggestedAction, Verdict

PREDICATE_FIELDS = (
    "has_primary_signal_anomaly",
    "has_correlated_actuator_response",
    "has_expected_spatial_signature",
    "has_manual_or_prior_case_support",
    "has_instrumentation_contradiction",
    "has_missing_required_evidence",
    "has_cross_tool_temporal_precedence",
)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    candidate: Candidate
    verdict: Verdict
    suggested_next_action: SuggestedAction
    predicates: PredicateSet
    constraints: ConstraintResult
    evidence: tuple[Evidence, ...]
    passed: bool


@dataclass(frozen=True, slots=True)
class W3Report:
    cases: tuple[CaseResult, ...]
    llm_calls: int
    passed: bool


def serialize_case(case: CaseResult) -> dict[str, object]:
    predicates = {name: getattr(case.predicates, name) for name in PREDICATE_FIELDS}
    return {
        "case_id": case.case_id,
        "candidate": {
            "claim": case.candidate.claim,
            "hypothesis_class": case.candidate.hypothesis_class,
            "cited_evidence": list(case.candidate.cited_evidence),
        },
        "verdict": case.verdict.value,
        "suggested_next_action": case.suggested_next_action.value,
        "passed": case.passed,
        "predicates": predicates,
        "constraints": {
            "satisfied": [item.value for item in case.constraints.satisfied],
            "unmet": [item.value for item in case.constraints.unmet],
            "forbidden": [item.value for item in case.constraints.forbidden],
            "vetoed": [item.value for item in case.constraints.vetoed],
        },
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "signal": item.signal,
                "kind": item.kind.value,
                "value": item.value,
                "unit": item.unit,
                "provenance": item.provenance,
            }
            for item in case.evidence
        ],
    }
