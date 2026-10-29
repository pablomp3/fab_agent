"""Deterministic differential assessment across every saved check.

This module is deliberately free of model calls. It converts each configured
check into the same Python-owned outcome shape, then picks a headline using a
fixed severity order. The caller wires the result to the bounded model calls.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from src.agents.differential_request import ValidatedCause
from src.config_types import CandidateConfig, ScenarioConfig
from src.core.evidence import EvidenceStore
from src.core.pipeline import Candidate, CandidateAssessment, assess_candidate
from src.core.types import Evidence, EvidenceKind, SuggestedAction, Verdict
from src.policy import COVERAGE_UNEXPLAINED_LARGE_Z
from src.schemas.models import (
    DifferentialEntryModel,
    HypothesisModel,
    ModelNarrative,
    RootCauseCategory,
)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """One configured check after Python re-scored its configured candidate."""

    check_id: str
    scenario: ScenarioConfig
    citations: tuple[str, ...]
    missing_signals: tuple[str, ...]
    assessment: CandidateAssessment
    status: Verdict
    evidence_for: tuple[str, ...]
    evidence_against: tuple[str, ...]
    support_count: int
    has_anomaly: bool
    narrative: ModelNarrative | None
    challenge_failed: bool = False
    reason: str | None = None


def _candidate_citations(
    candidate: CandidateConfig, evidence: tuple[Evidence, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    by_signal: dict[str, list[str]] = {}
    for item in evidence:
        if item.signal is not None:
            by_signal.setdefault(item.signal, []).append(item.evidence_id)
    cited: list[str] = []
    missing: list[str] = []
    for signal in candidate.cited_signals:
        evidence_ids = by_signal.get(signal)
        if not evidence_ids:
            missing.append(signal)
            continue
        for evidence_id in evidence_ids:
            if evidence_id not in cited:
                cited.append(evidence_id)
    return tuple(cited), tuple(missing)


def _missing_configured(
    candidate: CandidateConfig, evidence: tuple[Evidence, ...]
) -> tuple[str, ...]:
    """Signals with no measured value, including explicit missing-channel rows."""
    measured = {
        item.signal
        for item in evidence
        if item.signal is not None
        and item.kind in {EvidenceKind.SENSOR_ANOMALY, EvidenceKind.SENSOR_NOMINAL}
    }
    return tuple(signal for signal in candidate.cited_signals if signal not in measured)


def _append_unique(target: list[str], values: tuple[str, ...]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _evidence_split(
    outcome_scenario: ScenarioConfig,
    evidence: tuple[Evidence, ...],
    missing_signals: tuple[str, ...],
    coverage_large: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    primary = outcome_scenario.predicate_config.primary_signals
    corroboration = outcome_scenario.predicate_config.corroboration_signals
    forbidden = outcome_scenario.predicate_config.forbidden_anomaly_signals
    by_signal: dict[str, list[Evidence]] = {}
    for item in evidence:
        if item.signal is not None:
            by_signal.setdefault(item.signal, []).append(item)

    evidence_for: list[str] = []
    evidence_against: list[str] = []
    for signal in sorted(primary):
        for item in by_signal.get(signal, []):
            if item.kind is EvidenceKind.SENSOR_ANOMALY:
                _append_unique(evidence_for, (item.evidence_id,))
            elif item.kind in {
                EvidenceKind.SENSOR_NOMINAL,
                EvidenceKind.MISSING_CHANNEL,
            }:
                _append_unique(evidence_against, (item.evidence_id,))
    for signal in sorted(corroboration):
        for item in by_signal.get(signal, []):
            if item.kind is EvidenceKind.SENSOR_ANOMALY:
                _append_unique(evidence_for, (item.evidence_id,))
            elif item.kind in {
                EvidenceKind.SENSOR_NOMINAL,
                EvidenceKind.MISSING_CHANNEL,
            }:
                _append_unique(evidence_against, (item.evidence_id,))
    for signal in sorted(forbidden):
        for item in by_signal.get(signal, []):
            if item.kind is EvidenceKind.SENSOR_NOMINAL:
                _append_unique(evidence_for, (item.evidence_id,))
            elif item.kind in {
                EvidenceKind.SENSOR_ANOMALY,
                EvidenceKind.MISSING_CHANNEL,
            }:
                _append_unique(evidence_against, (item.evidence_id,))
    # Unexplained coverage anomalies belong in "What else moved"; they are not
    # evidence against this specific check. Adding them here made unrelated
    # channels look like contradictions.
    for signal in missing_signals:
        for item in by_signal.get(signal, []):
            if item.kind is EvidenceKind.MISSING_CHANNEL:
                _append_unique(evidence_against, (item.evidence_id,))
    return tuple(evidence_for), tuple(evidence_against)


def _reason_for(
    scenario: ScenarioConfig,
    status: Verdict,
    missing_signals: tuple[str, ...],
    coverage_large: tuple[str, ...],
) -> str:
    if status is Verdict.VETOED:
        if scenario.predicate_config.forbidden_anomaly_signals:
            return "A must-stay-normal signal also moved."
        return "The signals that should agree did not move together."
    if missing_signals:
        return "Required signal(s) missing: " + ", ".join(missing_signals) + "."
    if coverage_large:
        return (
            "Large unexplained anomaly outside the check: "
            + ", ".join(coverage_large)
            + "."
        )
    if status is Verdict.SUPPORTED:
        return "All required primary signals moved and no contradiction was found."
    return "The required signals did not all move."


def configured_scope(scenarios: Mapping[str, ScenarioConfig]) -> frozenset[str]:
    """Union every saved check's declared scope for shared coverage."""
    signals: set[str] = set()
    for scenario in scenarios.values():
        predicate_config = scenario.predicate_config
        signals |= set(predicate_config.primary_signals)
        signals |= set(predicate_config.corroboration_signals)
        signals |= set(predicate_config.forbidden_anomaly_signals)
        for pair in predicate_config.actuator_pairs:
            signals |= set(pair)
        for pair in predicate_config.temporal_precedence_pairs:
            signals |= set(pair)
    return frozenset(signals)


def assess_check(
    check_id: str,
    scenario: ScenarioConfig,
    evidence: tuple[Evidence, ...],
    store: EvidenceStore,
    narrative: ModelNarrative | None,
    *,
    coverage_scope: frozenset[str] | None = None,
) -> CheckOutcome:
    candidate = scenario.candidate
    citations, _ = _candidate_citations(candidate, evidence)
    missing_signals = _missing_configured(candidate, evidence)
    assessment = assess_candidate(
        Candidate(
            claim=candidate.claim,
            hypothesis_class=candidate.hypothesis_class,
            cited_evidence=citations,
        ),
        store,
        scenario.predicate_config,
        scenario.rules,
        scenario.supported_action,
        large_z=COVERAGE_UNEXPLAINED_LARGE_Z,
        coverage_scope=coverage_scope,
    )
    status = assessment.constraints.verdict
    if missing_signals and status is not Verdict.VETOED:
        status = Verdict.INSUFFICIENT
    coverage_large = (
        assessment.coverage.unexplained_large
        if status is Verdict.SUPPORTED
        else ()
    )
    if coverage_large:
        status = Verdict.INSUFFICIENT

    primary = scenario.predicate_config.primary_signals
    support_count = len(
        {
            item.signal
            for item in assessment.resolved_evidence
            if item.signal in primary and item.kind is EvidenceKind.SENSOR_ANOMALY
        }
    )
    cited = set(candidate.cited_signals)
    has_anomaly = any(
        item.signal in cited and item.kind is EvidenceKind.SENSOR_ANOMALY
        for item in evidence
    ) or bool(coverage_large)
    evidence_for, evidence_against = _evidence_split(
        scenario, evidence, missing_signals, coverage_large
    )
    return CheckOutcome(
        check_id=check_id,
        scenario=scenario,
        citations=citations,
        missing_signals=missing_signals,
        assessment=assessment,
        status=status,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        support_count=support_count,
        has_anomaly=has_anomaly,
        narrative=narrative,
        reason=_reason_for(scenario, status, missing_signals, coverage_large),
    )


def with_challenge_failure(outcome: CheckOutcome) -> CheckOutcome:
    return replace(
        outcome,
        status=Verdict.INSUFFICIENT,
        challenge_failed=True,
        reason="The AI challenge did not support this check.",
    )


def _preferred(
    outcomes: tuple[CheckOutcome, ...], preferred_check: str | None
) -> CheckOutcome | None:
    if preferred_check is not None:
        for item in outcomes:
            if item.check_id == preferred_check:
                return item
    return outcomes[0] if outcomes else None


def choose_headline(
    outcomes: tuple[CheckOutcome, ...], preferred_check: str | None
) -> CheckOutcome | None:
    """Pick the headline by fixed severity: confirm, contradict, missing, review."""
    if not outcomes:
        return None
    preferred = _preferred(outcomes, preferred_check)
    index = {item.check_id: position for position, item in enumerate(outcomes)}

    def best(
        candidates: list[CheckOutcome], score: Callable[[CheckOutcome], int]
    ) -> CheckOutcome:
        return max(
            candidates,
            key=lambda item: (
                score(item),
                item is preferred,
                -index[item.check_id],
            ),
        )

    supported = [item for item in outcomes if item.status is Verdict.SUPPORTED]
    if supported:
        return best(supported, lambda item: item.support_count)
    vetoed = [item for item in outcomes if item.status is Verdict.VETOED]
    if vetoed:
        return best(vetoed, lambda item: len(item.assessment.constraints.vetoed))
    missing = [item for item in outcomes if item.missing_signals]
    if missing:
        return best(missing, lambda item: len(item.missing_signals))
    anomalous = [item for item in outcomes if item.has_anomaly]
    if anomalous:
        return best(anomalous, lambda item: len(item.evidence_for))
    return preferred


def action_for(outcome: CheckOutcome) -> SuggestedAction:
    if outcome.status is Verdict.SUPPORTED:
        return outcome.scenario.supported_action
    if outcome.status is Verdict.VETOED:
        return SuggestedAction.REVIEW_CONTRADICTION
    if outcome.missing_signals:
        return SuggestedAction.COLLECT_MORE_DATA
    if outcome.has_anomaly or outcome.challenge_failed:
        return SuggestedAction.ESCALATE_TO_ENGINEER
    return SuggestedAction.CONTINUE_MONITORING


def build_hypothesis(outcome: CheckOutcome) -> HypothesisModel:
    candidate = outcome.scenario.candidate
    root_cause = (
        RootCauseCategory.INSTRUMENTATION_FAULT
        if outcome.status is Verdict.VETOED
        else candidate.root_cause
    )
    return HypothesisModel(
        claim=candidate.claim,
        root_cause=root_cause,
        failure_mode=candidate.failure_mode,
        mechanism=candidate.mechanism,
        hypothesis_class=candidate.hypothesis_class,
        cited_evidence=list(outcome.citations),
        status=outcome.status,
        veto_reason=(
            ", ".join(
                item.value for item in outcome.assessment.constraints.vetoed
            )
            if outcome.assessment.constraints.vetoed
            else None
        ),
        model_narrative=outcome.narrative,
    )


def build_differential_entry(outcome: CheckOutcome) -> DifferentialEntryModel:
    candidate = outcome.scenario.candidate
    root_cause = (
        RootCauseCategory.INSTRUMENTATION_FAULT
        if outcome.status is Verdict.VETOED
        else candidate.root_cause
    )
    return DifferentialEntryModel(
        check=outcome.check_id,
        title=candidate.claim,
        root_cause=root_cause,
        status=outcome.status,
        evidence_for=list(outcome.evidence_for),
        evidence_against=list(outcome.evidence_against),
        missing_signals=list(outcome.missing_signals),
        action=action_for(outcome),
        reason=outcome.reason,
        has_anomaly=outcome.has_anomaly,
        challenge_failed=outcome.challenge_failed,
    )


def build_unconfigured_entry(cause: ValidatedCause) -> DifferentialEntryModel:
    anomalies = tuple(
        item.evidence_id
        for item in cause.resolved_evidence
        if item.kind is EvidenceKind.SENSOR_ANOMALY
    )
    evidence_for = anomalies or tuple(
        item.evidence_id for item in cause.resolved_evidence
    )
    model_why = cause.why.strip()
    reason = (
        f"{model_why} (Unverified model proposal: no saved check exists, so this "
        "cannot change the result.)"
        if model_why
        else "No saved check exists; this proposed cause cannot change the result."
    )
    return DifferentialEntryModel(
        check="new",
        title=cause.title,
        root_cause=RootCauseCategory.UNKNOWN,
        status=Verdict.INSUFFICIENT,
        evidence_for=list(evidence_for),
        action=SuggestedAction.ESCALATE_TO_ENGINEER,
        reason=reason,
        proposed_by_model=True,
        has_anomaly=bool(anomalies),
    )
