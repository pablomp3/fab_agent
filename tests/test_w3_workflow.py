from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.evaluator.synthetic_abstention_runner import run_w3
from benchmarks.synthetic_twin.generate_twin import generate_all
from src.config_loader import LoadedRelations, ScenarioConfig, load_relations
from src.core.constraints import ConstraintRule
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import EvidenceStore
from src.core.pipeline import Candidate, assess_candidate
from src.core.sufficiency import PredicateConfig
from src.core.types import EvidenceKind, Predicate, SignalSpec, SuggestedAction, Verdict

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_CONFIG = (
    ROOT / "benchmarks" / "evaluator" / "fixtures" / "v1" / "synthetic_twin.yaml"
)

_MINIMAL_CONFIG = """
version: 1
name: template
provenance: test fixture
signals:
  - {{name: a, unit: null, robust_z_threshold: null}}
  - {{name: b, unit: null, robust_z_threshold: null}}
scenarios:
  scope:
    signals:
      - {{name: a, unit: null, robust_z_threshold: null}}
      - {{name: b, unit: null, robust_z_threshold: null}}
    predicates:
      primary_signals: [a]
    rules:
      cls:
        require_all: [has_primary_signal_anomaly]
    candidate:
      claim: a claim
      hypothesis_class: cls
      cited_signals: [a]
{extra}
"""


class W3WorkflowTests(unittest.TestCase):
    def test_yaml_loads_core_dataclasses_and_keeps_threshold_provenance(self) -> None:
        loaded = load_relations(SYNTHETIC_CONFIG)
        self.assertIsInstance(loaded, LoadedRelations)
        case = loaded.scenarios["B4a"]
        self.assertIsInstance(case, ScenarioConfig)
        self.assertIsInstance(case.predicate_config, PredicateConfig)
        self.assertIsInstance(case.rules["equipment_fault"], ConstraintRule)
        sensor = next(item for item in case.signals if item.name == "sensor_17")
        self.assertIsInstance(sensor, SignalSpec)
        self.assertEqual(sensor.robust_z_threshold, 3.5)
        self.assertEqual(
            sensor.threshold_source, "simulation_parameter:synthetic_twin_v1"
        )
        self.assertEqual(
            case.rules["equipment_fault"].veto_if_any,
            frozenset({Predicate.HAS_INSTRUMENTATION_CONTRADICTION}),
        )

    def test_partial_b4a_evidence_cannot_support_a_candidate(self) -> None:
        scenario = load_relations(SYNTHETIC_CONFIG).scenarios["B4a"]
        all_evidence = extract_evidence(
            ROOT / "benchmarks/synthetic_twin/cases/B4a/telemetry.csv", scenario.signals
        )
        partial_evidence = all_evidence[:3]
        primary = next(item for item in partial_evidence if item.signal == "sensor_17")
        candidate = Candidate(
            claim="synthetic candidate",
            hypothesis_class="equipment_fault",
            cited_evidence=(primary.evidence_id,),
        )

        partial = assess_candidate(
            candidate,
            EvidenceStore(partial_evidence),
            scenario.predicate_config,
            scenario.rules,
        )
        complete = assess_candidate(
            candidate,
            EvidenceStore(all_evidence),
            scenario.predicate_config,
            scenario.rules,
        )

        self.assertIs(partial.constraints.verdict, Verdict.INSUFFICIENT)
        self.assertIs(complete.constraints.verdict, Verdict.VETOED)

    def test_auxiliary_domain_configs_only_define_documented_relations(self) -> None:
        ion = load_relations(ROOT / "config/sensor_relations/ion_mill_phm18.yaml")
        self.assertEqual(
            set(ion.signal_labels),
            {
                "FLOWCOOLFLOWRATE",
                "FLOWCOOLPRESSURE",
                "IONGAUGEPRESSURE",
                "ETCHBEAMVOLTAGE",
                "ETCHBEAMCURRENT",
                "ETCHSUPPRESSORVOLTAGE",
                "ETCHSUPPRESSORCURRENT",
            },
        )
        ion_scenario = ion.scenarios["coolant_loop"]
        self.assertEqual(
            {spec.name for spec in ion_scenario.signals},
            {"FLOWCOOLFLOWRATE", "FLOWCOOLPRESSURE"},
        )
        self.assertEqual(len(ion_scenario.declared_signals or ()), 7)
        assert ion_scenario.baseline is not None
        self.assertEqual(ion_scenario.baseline.mode, "nominal_file")
        tep = load_relations(ROOT / "config/sensor_relations/tep_reactor.yaml")
        self.assertEqual(
            {spec.name for spec in tep.signals},
            {"XMEAS(1)", "XMV(3)", "XMEAS(7)"},
        )
        tep_scenario = tep.scenarios["feed_disturbance"]
        self.assertEqual(
            tep_scenario.predicate_config.primary_signals,
            {"XMEAS(1)", "XMEAS(7)"},
        )

    def test_yaml_loader_rejects_unknown_configuration_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "invalid.yaml"
            config.write_text(
                "version: 1\nname: invalid\nprovenance: test\nsurprise: true\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown keys"):
                load_relations(config)

    def test_generator_is_reproducible_and_keeps_private_truth_separate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            first_root = Path(temp_dir) / "first"
            second_root = Path(temp_dir) / "second"
            generate_all(first_root)
            generate_all(second_root)
            for case_id in ("B4a", "B4b", "B4c", "B4d"):
                relative = (
                    Path("benchmarks/synthetic_twin/cases") / case_id / "telemetry.csv"
                )
                first_csv = first_root / relative
                self.assertEqual(
                    first_csv.read_bytes(),
                    (second_root / relative).read_bytes(),
                )
                with (first_root / relative).open(
                    encoding="utf-8", newline=""
                ) as csv_file:
                    rows = list(csv.DictReader(csv_file))
                self.assertEqual(len(rows), 120)
                if case_id == "B4a":
                    manifest_path = first_csv.parent / "manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(manifest["seed"], 42)
                    self.assertEqual(
                        manifest["outputs"]["telemetry.csv"],
                        f"sha256:{hashlib.sha256(first_csv.read_bytes()).hexdigest()}",
                    )
                    self.assertNotIn("expected_verdict", manifest)
            b4d_header = (
                (first_root / "benchmarks/synthetic_twin/cases/B4d/telemetry.csv")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertNotIn("roughing_line_pressure", b4d_header)
            truth = (
                first_root / "benchmarks/evaluator/ground_truths/B4a_ground_truth.json"
            )
            self.assertTrue(truth.is_file())
            self.assertIn(
                "expected_verdict", json.loads(truth.read_text(encoding="utf-8"))
            )

    def test_scenario_declares_its_supported_action(self) -> None:
        loaded = load_relations(SYNTHETIC_CONFIG)
        self.assertIs(
            loaded.scenarios["B4a"].supported_action,
            SuggestedAction.INSPECT_COMPONENT,
        )

    def test_scenario_defaults_to_escalation_when_undeclared(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "default.yaml"
            config.write_text(_MINIMAL_CONFIG.format(extra=""), encoding="utf-8")
            loaded = load_relations(config)
        self.assertIs(
            loaded.scenarios["scope"].supported_action,
            SuggestedAction.ESCALATE_TO_ENGINEER,
        )

    def test_scenario_supported_action_round_trips(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "supported.yaml"
            config.write_text(
                _MINIMAL_CONFIG.format(extra="    supported_action: INSPECT_COMPONENT"),
                encoding="utf-8",
            )
            loaded = load_relations(config)
        self.assertIs(
            loaded.scenarios["scope"].supported_action,
            SuggestedAction.INSPECT_COMPONENT,
        )

    def test_scenario_supported_action_rejects_unsafe_or_data_actions(self) -> None:
        for value in ("UPDATE_RECIPE", "HOLD_LOT", "PROVIDE_MORE_DATA", "NOPE"):
            with self.subTest(value=value):
                with TemporaryDirectory() as temp_dir:
                    config = Path(temp_dir) / "invalid.yaml"
                    config.write_text(
                        _MINIMAL_CONFIG.format(extra=f"    supported_action: {value}"),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, "action"):
                        load_relations(config)

    def test_w3_passes_all_cases_without_model_calls(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = run_w3(Path(temp_dir))
            self.assertTrue(report.passed)
            self.assertEqual(report.llm_calls, 0)
            cases = {case.case_id: case for case in report.cases}
            self.assertEqual(set(cases), {"B4a", "B4b", "B4c", "B4d"})
            self.assertIs(cases["B4a"].verdict, Verdict.VETOED)
            for case_id in ("B4b", "B4c", "B4d"):
                self.assertIs(cases[case_id].verdict, Verdict.INSUFFICIENT)
            self.assertIs(
                cases["B4a"].predicates.has_instrumentation_contradiction, True
            )
            self.assertIs(cases["B4b"].predicates.has_primary_signal_anomaly, False)
            self.assertIs(
                cases["B4c"].predicates.has_cross_tool_temporal_precedence, False
            )
            self.assertIs(cases["B4d"].predicates.has_missing_required_evidence, True)
            for case in cases.values():
                evidence_ids = {item.evidence_id for item in case.evidence}
                self.assertTrue(set(case.candidate.cited_evidence) <= evidence_ids)
            self.assertEqual(len(cases["B4a"].candidate.cited_evidence), 1)
            self.assertEqual(len(cases["B4d"].candidate.cited_evidence), 2)
            by_signal = {
                case.case_id: {item.signal: item for item in case.evidence}
                for case in cases.values()
            }
            for case in cases.values():
                for item in case.evidence:
                    self.assertIn(
                        "source=simulation_parameter:synthetic_twin_v1",
                        item.provenance,
                    )
            self.assertIs(
                by_signal["B4a"]["sensor_17"].kind, EvidenceKind.SENSOR_ANOMALY
            )
            for signal in ("impedance", "thermal", "pressure"):
                item = by_signal["B4a"][signal]
                self.assertIs(item.kind, EvidenceKind.SENSOR_NOMINAL)
                self.assertLess(item.value or 0.0, 1.0)
            self.assertIs(
                by_signal["B4b"]["thermal_sensor"].kind,
                EvidenceKind.NOT_EVALUATED,
            )
            self.assertIs(
                by_signal["B4c"]["met_cd_bias"].kind, EvidenceKind.SENSOR_ANOMALY
            )
            self.assertAlmostEqual(by_signal["B4c"]["met_cd_bias"].value or 0.0, 4.2)
            for signal in ("etch_rf_power", "chamber_pressure"):
                item = by_signal["B4c"][signal]
                self.assertIs(item.kind, EvidenceKind.SENSOR_NOMINAL)
                self.assertLess(item.value or 0.0, 1.2)
            self.assertIs(
                by_signal["B4d"]["roughing_line_pressure"].kind,
                EvidenceKind.MISSING_CHANNEL,
            )
            result = (
                Path(temp_dir)
                / "benchmarks/evaluator/results/w3_adversarial_check.json"
            )
            self.assertTrue(result.is_file())
            self.assertEqual(
                json.loads(result.read_text(encoding="utf-8"))["llm_calls"], 0
            )


if __name__ == "__main__":
    unittest.main()
