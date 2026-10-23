from __future__ import annotations

import unittest

from src.core.constraints import ConstraintRule
from src.core.evidence import EvidenceStore
from src.core.pipeline import Candidate, assess_candidate
from src.core.sufficiency import PredicateConfig
from src.core.types import (
    Evidence,
    EvidenceKind,
    Predicate,
    SuggestedAction,
    Verdict,
)


def make_evidence(evidence_id: str, kind: EvidenceKind, signal: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        signal=signal,
        statistic="fixture_status",
        value=None,
        unit=None,
        window=(1, 2),
        provenance="fixture rows 1-2",
        computed_by="test",
        summary="Status supplied by test fixture.",
        window_basis="row:fixture",
    )


class CandidateCitationTests(unittest.TestCase):
    def test_uncited_support_cannot_satisfy_required_predicate(self) -> None:
        store = EvidenceStore(
            (
                make_evidence(
                    "EV_uncited", EvidenceKind.SENSOR_ANOMALY, "primary_sensor"
                ),
                make_evidence(
                    "EV_cited", EvidenceKind.SENSOR_NOMINAL, "unrelated_sensor"
                ),
            )
        )
        result = assess_candidate(
            Candidate("Claim", "fault_class", ("EV_cited",)),
            store,
            PredicateConfig(primary_signals=frozenset({"primary_sensor"})),
            {
                "fault_class": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
                )
            },
        )
        self.assertIs(result.constraints.verdict, Verdict.INSUFFICIENT)
        self.assertIs(
            result.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
        )

    def test_uncited_global_contradiction_still_vetoes_candidate(self) -> None:
        store = EvidenceStore(
            (
                make_evidence(
                    "EV_primary", EvidenceKind.SENSOR_ANOMALY, "primary_sensor"
                ),
                make_evidence(
                    "EV_corrob", EvidenceKind.SENSOR_NOMINAL, "independent_sensor"
                ),
            )
        )
        result = assess_candidate(
            Candidate("Claim", "fault_class", ("EV_primary",)),
            store,
            PredicateConfig(
                primary_signals=frozenset({"primary_sensor"}),
                corroboration_signals=frozenset({"independent_sensor"}),
            ),
            {
                "fault_class": ConstraintRule(
                    require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY}),
                    veto_if_any=frozenset(
                        {Predicate.HAS_INSTRUMENTATION_CONTRADICTION}
                    ),
                )
            },
            SuggestedAction.INSPECT_COMPONENT,
        )
        self.assertIs(result.constraints.verdict, Verdict.VETOED)
        self.assertIs(
            result.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
        )


if __name__ == "__main__":
    unittest.main()
