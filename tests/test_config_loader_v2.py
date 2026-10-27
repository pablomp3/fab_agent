from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.config_loader import LoadedRelations, load_relations
from src.core.evidence import EvidenceStore
from src.core.sufficiency import derive_predicates
from src.core.types import Evidence, EvidenceKind

_HEADER = """version: 2
tool:
  name: test_tool
  label: Test Tool
baseline:
  mode: lead_in
  rows: 3
signals:
  - {name: a, label: A, unit: null, alert_at: 3.5}
  - {name: b, label: B, unit: null, alert_at: 3.5}
checks:
  - id: check_one
    label: Check one
    kind: equipment_fault
    must_be_unusual:
      - {signal: a}
    must_stay_normal: [b]
    action: INSPECT_COMPONENT
    advice: Inspect the component.
"""


class ConfigLoaderV2Tests(unittest.TestCase):
    def _load(self, text: str) -> LoadedRelations:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return load_relations(path)

    def test_loads_a_check_and_declared_signals(self) -> None:
        relations = self._load(_HEADER)
        scenario = relations.scenarios["check_one"]
        self.assertEqual(relations.name, "test_tool")
        self.assertEqual(relations.signal_labels["a"], "A")
        self.assertEqual([item.name for item in scenario.signals], ["a", "b"])
        declared = scenario.declared_signals or ()
        self.assertEqual([item.name for item in declared], ["a", "b"])
        assert scenario.baseline is not None
        self.assertEqual(scenario.baseline.mode, "lead_in")
        self.assertEqual(scenario.baseline.rows, 3)
        self.assertEqual(scenario.candidate.cited_signals, ("a", "b"))
        self.assertEqual(
            scenario.predicate_config.forbidden_anomaly_signals, frozenset({"b"})
        )
        self.assertEqual(
            scenario.predicate_config.corroboration_signals, frozenset()
        )
        self.assertIn("equipment_fault", scenario.rules)
        self.assertIn("has_instrumentation_contradiction", {
            item.value for item in scenario.rules["equipment_fault"].veto_if_any
        })

    def test_must_stay_normal_is_contradicted_only_when_it_moves(self) -> None:
        relations = self._load(_HEADER)
        scenario = relations.scenarios["check_one"]

        def _predicates(b_kind: EvidenceKind):
            store = EvidenceStore(
                (
                    Evidence(
                        evidence_id="EV_A",
                        kind=EvidenceKind.SENSOR_ANOMALY,
                        signal="a",
                        statistic="robust_z_max",
                        value=5.0,
                        unit=None,
                        window=(1, 3),
                        provenance="fixture",
                        computed_by="fixture",
                        summary="fixture",
                        window_basis="row:fixture",
                    ),
                    Evidence(
                        evidence_id="EV_B",
                        kind=b_kind,
                        signal="b",
                        statistic="robust_z_max",
                        value=0.1 if b_kind is EvidenceKind.SENSOR_NOMINAL else 5.0,
                        unit=None,
                        window=(1, 3),
                        provenance="fixture",
                        computed_by="fixture",
                        summary="fixture",
                        window_basis="row:fixture",
                    ),
                )
            )
            return derive_predicates(store, scenario.predicate_config)

        self.assertFalse(
            _predicates(EvidenceKind.SENSOR_NOMINAL).has_instrumentation_contradiction
        )
        self.assertTrue(
            _predicates(EvidenceKind.SENSOR_ANOMALY).has_instrumentation_contradiction
        )

    def test_rejects_an_unknown_key(self) -> None:
        bad = _HEADER.replace("    advice:", "    typo: 1\n    advice:")
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            self._load(bad)

    def test_rejects_a_duplicate_check_id(self) -> None:
        checks = _HEADER.split("checks:\n", 1)[1]
        with self.assertRaisesRegex(ValueError, "repeats id"):
            self._load(_HEADER.replace("checks:\n", "checks:\n" + checks))

    def test_rejects_the_reserved_new_check_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved"):
            self._load(_HEADER.replace("id: check_one", "id: new"))

    def test_rejects_baseline_exclusivity_violations(self) -> None:
        bad = _HEADER.replace("  rows: 3", "  rows: 3\n  file: nominal.csv")
        with self.assertRaisesRegex(ValueError, "cannot set file"):
            self._load(bad)

    def test_nominal_file_must_contain_every_declared_signal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nominal.csv").write_text("a\n1.0\n", encoding="utf-8")
            text = _HEADER.replace(
                "  mode: lead_in\n  rows: 3",
                "  mode: nominal_file\n  file: nominal.csv",
            )
            path = root / "config.yaml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing declared signal"):
                load_relations(path)


if __name__ == "__main__":
    unittest.main()
