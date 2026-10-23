from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.core.constraints import ConstraintResult, ConstraintRule
from src.core.evidence import EvidenceStore
from src.core.safety_gate import apply_safety_gate
from src.core.sufficiency import (
    PredicateConfig,
    derive_predicates,
    evaluate_sufficiency,
)
from src.core.types import Evidence, Predicate, PredicateSet, SuggestedAction, Verdict


@dataclass(frozen=True, slots=True)
class Candidate:
    claim: str
    hypothesis_class: str
    cited_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    candidate: Candidate
    resolved_evidence: tuple[Evidence, ...]
    unresolved_evidence: tuple[str, ...]
    constraints: ConstraintResult
    suggested_next_action: SuggestedAction


def assess_candidate(
    candidate: Candidate,
    store: EvidenceStore,
    predicate_config: PredicateConfig,
    rules: Mapping[str, ConstraintRule],
    supported_action: SuggestedAction = SuggestedAction.ESCALATE_TO_ENGINEER,
) -> CandidateAssessment:
    resolved, unresolved = store.resolve_all(candidate.cited_evidence)
    rule = rules.get(candidate.hypothesis_class)
    if not candidate.cited_evidence or unresolved or rule is None:
        result = ConstraintResult(
            verdict=Verdict.INSUFFICIENT,
            satisfied=(),
            unmet=(),
            forbidden=(),
            vetoed=(),
        )
    else:
        cited_predicates = derive_predicates(EvidenceStore(resolved), predicate_config)
        global_predicates = derive_predicates(store, predicate_config)
        predicates = _assessment_predicates(cited_predicates, global_predicates, rule)
        result = evaluate_sufficiency(rule, predicates)
    action = apply_safety_gate(result.verdict, supported_action)
    return CandidateAssessment(
        candidate=candidate,
        resolved_evidence=resolved,
        unresolved_evidence=unresolved,
        constraints=result,
        suggested_next_action=action,
    )


def _assessment_predicates(
    cited: PredicateSet, global_evidence: PredicateSet, rule: ConstraintRule
) -> PredicateSet:
    return PredicateSet(
        has_primary_signal_anomaly=_assessment_flag(
            Predicate.HAS_PRIMARY_SIGNAL_ANOMALY, cited, global_evidence, rule
        ),
        has_correlated_actuator_response=_assessment_flag(
            Predicate.HAS_CORRELATED_ACTUATOR_RESPONSE,
            cited,
            global_evidence,
            rule,
        ),
        has_expected_spatial_signature=_assessment_flag(
            Predicate.HAS_EXPECTED_SPATIAL_SIGNATURE,
            cited,
            global_evidence,
            rule,
        ),
        has_manual_or_prior_case_support=_assessment_flag(
            Predicate.HAS_MANUAL_OR_PRIOR_CASE_SUPPORT,
            cited,
            global_evidence,
            rule,
        ),
        has_instrumentation_contradiction=_assessment_flag(
            Predicate.HAS_INSTRUMENTATION_CONTRADICTION,
            cited,
            global_evidence,
            rule,
        ),
        has_missing_required_evidence=_assessment_flag(
            Predicate.HAS_MISSING_REQUIRED_EVIDENCE,
            cited,
            global_evidence,
            rule,
        ),
        has_cross_tool_temporal_precedence=_assessment_flag(
            Predicate.HAS_CROSS_TOOL_TEMPORAL_PRECEDENCE,
            cited,
            global_evidence,
            rule,
        ),
    )


def _assessment_flag(
    predicate: Predicate,
    cited: PredicateSet,
    global_evidence: PredicateSet,
    rule: ConstraintRule,
) -> bool:
    if predicate is Predicate.HAS_MISSING_REQUIRED_EVIDENCE:
        return cited.enabled(predicate) or global_evidence.enabled(predicate)
    if predicate in rule.forbid_any or predicate in rule.veto_if_any:
        return global_evidence.enabled(predicate)
    return cited.enabled(predicate)
