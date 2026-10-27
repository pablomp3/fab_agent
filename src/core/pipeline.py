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
from src.core.types import (
    Coverage,
    Evidence,
    EvidenceKind,
    Predicate,
    PredicateSet,
    SuggestedAction,
    Verdict,
)


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
    coverage: Coverage


def compute_coverage(
    store: EvidenceStore,
    predicate_config: PredicateConfig,
    *,
    large_z: float | None = None,
    coverage_scope: frozenset[str] | None = None,
) -> Coverage:
    """Split declared channels into explained, unexplained, and large.

    A channel is explained when it belongs to the configured check or scored
    nominal. A channel with an anomaly outside the check is unexplained. The
    caller supplies the product policy limit; core does not hardcode it.
    ``coverage_scope`` lets a caller assess all saved checks together, so a
    channel that another check explains is not treated as unexplained.
    """
    check_signals = (
        coverage_scope
        if coverage_scope is not None
        else (
            predicate_config.primary_signals
            | predicate_config.corroboration_signals
            | predicate_config.forbidden_anomaly_signals
            | frozenset(
                signal
                for pair in predicate_config.actuator_pairs
                for signal in pair
            )
            | frozenset(
                signal
                for pair in predicate_config.temporal_precedence_pairs
                for signal in pair
            )
        )
    )
    anomaly_max: dict[str, float] = {}
    nominal: set[str] = set()
    for item in store:
        if item.signal is None:
            continue
        if item.kind is EvidenceKind.SENSOR_ANOMALY and item.value is not None:
            current = anomaly_max.get(item.signal)
            if current is None or item.value > current:
                anomaly_max[item.signal] = item.value
        elif item.kind is EvidenceKind.SENSOR_NOMINAL:
            nominal.add(item.signal)
    unexplained = set(anomaly_max) - check_signals
    unexplained_large: set[str] = set()
    if large_z is not None:
        unexplained_large = {
            signal
            for signal in unexplained
            if (value := anomaly_max.get(signal)) is not None
            and value >= large_z
        }
    explained = (check_signals & (set(anomaly_max) | nominal)) | nominal
    return Coverage(
        explained=tuple(sorted(explained)),
        unexplained=tuple(sorted(unexplained)),
        unexplained_large=tuple(sorted(unexplained_large)),
    )


def assess_candidate(
    candidate: Candidate,
    store: EvidenceStore,
    predicate_config: PredicateConfig,
    rules: Mapping[str, ConstraintRule],
    supported_action: SuggestedAction = SuggestedAction.ESCALATE_TO_ENGINEER,
    *,
    large_z: float | None = None,
    coverage_scope: frozenset[str] | None = None,
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
        coverage=compute_coverage(
            store,
            predicate_config,
            large_z=large_z,
            coverage_scope=coverage_scope,
        ),
    )


def _assessment_predicates(
    cited: PredicateSet, global_evidence: PredicateSet, rule: ConstraintRule
) -> PredicateSet:
    return PredicateSet(
        has_primary_signal_anomaly=_assessment_flag(
            Predicate.HAS_PRIMARY_SIGNAL_ANOMALY, cited, global_evidence, rule
        ),
        has_all_primary_signals_anomaly=_assessment_flag(
            Predicate.HAS_ALL_PRIMARY_SIGNALS_ANOMALY, cited, global_evidence, rule
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
