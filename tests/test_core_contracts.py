from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from src.core.constraints import ConstraintRule, evaluate_rule
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import EvidenceStore, PayloadTooLarge, build_llm_payload
from src.core.pipeline import Candidate, assess_candidate
from src.core.safety_gate import apply_safety_gate
from src.core.statistics import classify_signal, robust_mad_zscores
from src.core.sufficiency import PredicateConfig, derive_predicates
from src.core.types import (
    Evidence,
    EvidenceKind,
    Predicate,
    PredicateSet,
    SignalSpec,
    SuggestedAction,
    Verdict,
)


class CoreContractTests(unittest.TestCase):
    def test_constant_channel_has_zero_robust_scores(self) -> None:
        self.assertEqual(robust_mad_zscores((2.0, 2.0, 2.0)), (0.0, 0.0, 0.0))

    def test_missing_and_uncalibrated_channels_are_explicit(self) -> None:
        missing = classify_signal("sensor_x", None, None, None, "input.csv")
        uncalibrated = classify_signal("sensor_x", (1.0, 1.0), None, None, "input.csv")
        self.assertIs(missing.kind, EvidenceKind.MISSING_CHANNEL)
        self.assertIs(uncalibrated.kind, EvidenceKind.NOT_EVALUATED)

    def test_duckdb_scan_emits_one_record_per_declared_signal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "telemetry.csv"
            csv_path.write_text("sensor_x,sensor_y\n1,4\n1,4\n1,4\n", encoding="utf-8")
            signals = (
                SignalSpec("sensor_x"),
                SignalSpec("sensor_missing"),
            )
            evidence = extract_evidence(csv_path, signals)
        self.assertEqual(len(evidence), len(signals))
        self.assertIs(evidence[0].kind, EvidenceKind.NOT_EVALUATED)
        self.assertEqual(evidence[0].value, 0.0)
        self.assertIs(evidence[1].kind, EvidenceKind.MISSING_CHANNEL)

    def test_duckdb_summary_fits_payload_budget(self) -> None:
        csv_path = Path("benchmarks/synthetic_twin/cases/B4a/telemetry.csv")
        columns = tuple(csv_path.read_text(encoding="utf-8").splitlines()[0].split(","))
        evidence = extract_evidence(
            csv_path, tuple(SignalSpec(name) for name in columns[1:])
        )
        payload = build_llm_payload(EvidenceStore(evidence))
        self.assertLessEqual(len(payload.encode("utf-8")), 2048)

    def test_resolve_all_reports_unknown_citations(self) -> None:
        evidence = Evidence(
            evidence_id="EV_fixture",
            kind=EvidenceKind.SENSOR_ANOMALY,
            signal="sensor_x",
            statistic="robust_z_max",
            value=None,
            unit=None,
            window=None,
            provenance="input.csv rows 1-3",
            computed_by="test",
            summary="Anomaly status supplied by caller.",
        )
        resolved, unresolved = EvidenceStore((evidence,)).resolve_all(
            ("EV_fixture", "EV_missing")
        )
        self.assertEqual(tuple(item.evidence_id for item in resolved), ("EV_fixture",))
        self.assertEqual(unresolved, ("EV_missing",))

    def test_payload_fails_instead_of_truncating(self) -> None:
        evidence = Evidence(
            evidence_id="EV_large",
            kind=EvidenceKind.NOT_EVALUATED,
            signal="sensor_x",
            statistic=None,
            value=None,
            unit=None,
            window=None,
            provenance="input.csv",
            computed_by="test",
            summary="x" * 4096,
        )
        with self.assertRaises(PayloadTooLarge):
            build_llm_payload(EvidenceStore((evidence,)))

    def test_hard_veto_overrides_missing_requirements(self) -> None:
        predicates = PredicateSet(has_instrumentation_contradiction=True)
        rule = ConstraintRule(
            require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY}),
            veto_if_any=frozenset({Predicate.HAS_INSTRUMENTATION_CONTRADICTION}),
        )
        result = evaluate_rule(rule, predicates)
        self.assertIs(result.verdict, Verdict.VETOED)

    def test_python_derives_instrumentation_veto_from_resolved_evidence(self) -> None:
        store = EvidenceStore(
            (
                Evidence(
                    evidence_id="EV_primary",
                    kind=EvidenceKind.SENSOR_ANOMALY,
                    signal="primary_sensor",
                    statistic="robust_z_max",
                    value=None,
                    unit=None,
                    window=(1, 2),
                    provenance="fixture rows 1-2",
                    computed_by="test",
                    summary="Primary signal status supplied by fixture.",
                    window_basis="row:fixture",
                ),
                Evidence(
                    evidence_id="EV_corrob",
                    kind=EvidenceKind.SENSOR_NOMINAL,
                    signal="independent_sensor",
                    statistic="robust_z_max",
                    value=None,
                    unit=None,
                    window=(1, 2),
                    provenance="fixture rows 1-2",
                    computed_by="test",
                    summary="Independent signal status supplied by fixture.",
                    window_basis="row:fixture",
                ),
            )
        )
        config = PredicateConfig(
            primary_signals=frozenset({"primary_sensor"}),
            corroboration_signals=frozenset({"independent_sensor"}),
        )
        predicates = derive_predicates(store, config)
        self.assertTrue(predicates.has_instrumentation_contradiction)
        rule = ConstraintRule(
            require_all=frozenset({Predicate.HAS_CROSS_TOOL_TEMPORAL_PRECEDENCE}),
            veto_if_any=frozenset({Predicate.HAS_INSTRUMENTATION_CONTRADICTION}),
        )
        self.assertIs(evaluate_rule(rule, predicates).verdict, Verdict.VETOED)

    def test_candidate_gate_resolves_citations_and_forces_abstention(self) -> None:
        evidence = Evidence(
            evidence_id="EV_fixture",
            kind=EvidenceKind.SENSOR_ANOMALY,
            signal="sensor_x",
            statistic="robust_z_max",
            value=None,
            unit=None,
            window=None,
            provenance="input.csv",
            computed_by="test",
            summary="Caller supplied an anomaly record.",
        )
        rule = ConstraintRule(
            require_all=frozenset({Predicate.HAS_PRIMARY_SIGNAL_ANOMALY})
        )
        candidate = Candidate("A claim", "configured_class", ("EV_fixture",))
        rules = {"configured_class": rule}
        supported = assess_candidate(
            candidate,
            EvidenceStore((evidence,)),
            PredicateConfig(primary_signals=frozenset({"sensor_x"})),
            rules,
            SuggestedAction.INSPECT_COMPONENT,
        )
        self.assertIs(supported.constraints.verdict, Verdict.SUPPORTED)
        self.assertIs(
            supported.suggested_next_action, SuggestedAction.INSPECT_COMPONENT
        )

        unresolved = assess_candidate(
            Candidate("A claim", "configured_class", ("EV_missing",)),
            EvidenceStore((evidence,)),
            PredicateConfig(primary_signals=frozenset({"sensor_x"})),
            rules,
            SuggestedAction.INSPECT_COMPONENT,
        )
        self.assertIs(unresolved.constraints.verdict, Verdict.INSUFFICIENT)
        self.assertIs(
            unresolved.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
        )

    def test_output_schema_rejects_free_form_action_and_extra_fields(self) -> None:
        from pydantic import ValidationError

        from src.schemas.models import RCAOutputModel

        with self.assertRaises(ValidationError):
            RCAOutputModel.model_validate(
                {"suggested_next_action": "UPDATE_RECIPE", "confidence": "HIGH"}
            )
        with self.assertRaises(ValidationError):
            RCAOutputModel.model_validate(
                {
                    "suggested_next_action": "ESCALATE_TO_ENGINEER",
                    "confidence": "LOW",
                    "recipe_change": "adjust a setting",
                }
            )

    def test_unsafe_action_cannot_be_represented(self) -> None:
        with self.assertRaises((TypeError, ValueError)):
            apply_safety_gate(
                Verdict.SUPPORTED, cast(SuggestedAction, "UPDATE_RECIPE")
            )

    def test_core_has_no_benchmark_identifiers(self) -> None:
        core = Path("src/core")
        forbidden = ("B1", "B2", "B3", "B4", "IDV", "PHM18", "TEP", "SECOM")
        offenders = [
            path
            for path in core.glob("*.py")
            if any(token in path.read_text(encoding="utf-8") for token in forbidden)
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
