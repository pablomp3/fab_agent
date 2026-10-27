from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product

from src.core.constraints import ConstraintResult, ConstraintRule, evaluate_rule
from src.core.evidence import EvidenceStore
from src.core.types import Evidence, EvidenceKind, PredicateSet


@dataclass(frozen=True, slots=True)
class SpatialExpectation:
    statistic: str
    minimum: float | None
    maximum: float | None
    source: str

    def __post_init__(self) -> None:
        if not self.statistic or not self.source:
            raise ValueError("spatial expectation requires a statistic and source")
        if self.minimum is None and self.maximum is None:
            raise ValueError("spatial expectation requires at least one bound")
        for bound in (self.minimum, self.maximum):
            if bound is not None and not math.isfinite(bound):
                raise ValueError("spatial expectation bounds must be finite")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("spatial expectation minimum exceeds maximum")


@dataclass(frozen=True, slots=True)
class PredicateConfig:
    primary_signals: frozenset[str] = frozenset()
    actuator_pairs: tuple[tuple[str, str], ...] = ()
    expected_spatial_features: tuple[SpatialExpectation, ...] = ()
    # v1: at least one corroborating channel should move, so all-nominal is a
    # contradiction. v2 ``must_stay_normal`` uses the explicit forbidden set.
    corroboration_signals: frozenset[str] = frozenset()
    forbidden_anomaly_signals: frozenset[str] = frozenset()
    required_evidence_ids: frozenset[str] = frozenset()
    temporal_precedence_pairs: tuple[tuple[str, str], ...] = ()


def derive_predicates(store: EvidenceStore, config: PredicateConfig) -> PredicateSet:
    evidence = tuple(store)
    by_signal: dict[str, list[Evidence]] = {}
    for item in evidence:
        if item.signal is not None:
            by_signal.setdefault(item.signal, []).append(item)
    anomaly_signals = {
        signal
        for signal, items in by_signal.items()
        if any(item.kind is EvidenceKind.SENSOR_ANOMALY for item in items)
    }
    nominal_signals = {
        signal
        for signal, items in by_signal.items()
        if any(item.kind is EvidenceKind.SENSOR_NOMINAL for item in items)
    }
    primary_anomaly = bool(anomaly_signals & config.primary_signals)
    all_primary_anomaly = bool(config.primary_signals) and (
        config.primary_signals <= anomaly_signals
    )
    actuator_response = any(
        primary in anomaly_signals
        and actuator in anomaly_signals
        and _windows_overlap(by_signal[primary], by_signal[actuator])
        for primary, actuator in config.actuator_pairs
        if primary in by_signal and actuator in by_signal
    )
    spatial = _matches_spatial_expectations(evidence, config.expected_spatial_features)
    manual_support = any(
        item.kind in {EvidenceKind.MANUAL_EXCERPT, EvidenceKind.VERIFIED_CASE}
        for item in evidence
    )

    corroboration_contradiction = (
        bool(config.corroboration_signals)
        and config.corroboration_signals <= nominal_signals
    )
    forbidden_contradiction = bool(
        config.forbidden_anomaly_signals & anomaly_signals
    )
    instrumentation_contradiction = primary_anomaly and (
        corroboration_contradiction or forbidden_contradiction
    )
    required_channels = (
        config.primary_signals
        | config.corroboration_signals
        | config.forbidden_anomaly_signals
        | frozenset(signal for pair in config.actuator_pairs for signal in pair)
        | frozenset(
            signal for pair in config.temporal_precedence_pairs for signal in pair
        )
    )
    evaluated_signals = anomaly_signals | nominal_signals
    absent_required = bool(required_channels - evaluated_signals)
    missing_ids = config.required_evidence_ids - {item.evidence_id for item in evidence}
    has_missing = (
        absent_required
        or bool(missing_ids)
        or any(
            item.kind in {EvidenceKind.MISSING_CHANNEL, EvidenceKind.NOT_EVALUATED}
            and item.signal in required_channels
            for item in evidence
        )
    )
    temporal_precedence = any(
        _precedes(by_signal[upstream], by_signal[downstream])
        for upstream, downstream in config.temporal_precedence_pairs
        if upstream in by_signal and downstream in by_signal
    )
    return PredicateSet(
        has_primary_signal_anomaly=primary_anomaly,
        has_all_primary_signals_anomaly=all_primary_anomaly,
        has_correlated_actuator_response=actuator_response,
        has_expected_spatial_signature=spatial,
        has_manual_or_prior_case_support=manual_support,
        has_instrumentation_contradiction=instrumentation_contradiction,
        has_missing_required_evidence=has_missing,
        has_cross_tool_temporal_precedence=temporal_precedence,
    )


def _matches_spatial_expectations(
    evidence: tuple[Evidence, ...],
    expectations: tuple[SpatialExpectation, ...],
) -> bool:
    if not expectations:
        return False
    return all(
        any(
            item.kind is EvidenceKind.SPATIAL_FEATURE
            and item.statistic == expected.statistic
            and item.value is not None
            and (expected.minimum is None or item.value >= expected.minimum)
            and (expected.maximum is None or item.value <= expected.maximum)
            for item in evidence
        )
        for expected in expectations
    )


def _windows_overlap(left: list[Evidence], right: list[Evidence]) -> bool:
    return any(
        a.window is not None
        and b.window is not None
        and a.window_basis is not None
        and a.window_basis == b.window_basis
        and a.window[0] <= b.window[1]
        and b.window[0] <= a.window[1]
        for a, b in product(left, right)
    )


def _precedes(upstream: list[Evidence], downstream: list[Evidence]) -> bool:
    return any(
        left.kind is EvidenceKind.SENSOR_ANOMALY
        and right.kind is EvidenceKind.SENSOR_ANOMALY
        and left.window is not None
        and right.window is not None
        and left.window_basis is not None
        and left.window_basis == right.window_basis
        and left.window[1] <= right.window[0]
        for left, right in product(upstream, downstream)
    )


def evaluate_sufficiency(
    rule: ConstraintRule, predicates: PredicateSet
) -> ConstraintResult:
    """Evaluate configured boolean predicates; callers supply no model verdict."""
    return evaluate_rule(rule, predicates)
