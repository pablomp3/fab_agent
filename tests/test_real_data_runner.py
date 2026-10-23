from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.evaluator.real_data_fixtures import RealDataCase
from benchmarks.evaluator.real_data_runner import evaluate_case
from src.config_loader import load_relations
from src.core.types import SuggestedAction, Verdict

ROOT = Path(__file__).resolve().parents[1]
TEP_CONFIG = ROOT / "config" / "sensor_relations" / "tep_reactor.yaml"


class RealDataRunnerTests(unittest.TestCase):
    Row = tuple[float, float, float]

    def _write_csv(
        self, path: Path, header: tuple[str, ...], rows: list[Row]
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)

    def test_tep_feed_disturbance_supported_when_cause_anomalous(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            processed = temp_root / "processed"
            processed.mkdir()
            case_csv = processed / "IDV_synthetic.csv"
            nominal_csv = processed / "IDV_synthetic_nominal.csv"
            header = ("XMEAS(1)", "XMV(3)", "XMEAS(7)")
            # Nominal baseline: small variation around steady state.
            nominal_rows = [
                (0.50, 32.1, 2705.0),
                (0.52, 32.3, 2704.0),
                (0.48, 31.9, 2706.0),
                (0.51, 32.0, 2705.5),
                (0.49, 32.2, 2705.2),
                (0.53, 31.8, 2704.8),
            ]
            self._write_csv(nominal_csv, header, nominal_rows)
            # Fault window: cause and symptom deviate strongly.
            fault_rows = [
                (0.5, 32.1, 2705.0),
                (0.0, 10.0, 2600.0),
                (-1.0, -5.0, 2500.0),
                (-2.0, -15.0, 2400.0),
                (-3.0, -25.0, 2300.0),
            ]
            self._write_csv(case_csv, header, nominal_rows + fault_rows)

            case = RealDataCase(
                case_id="IDV_synthetic",
                csv_path=case_csv,
                nominal_baseline_path=nominal_csv,
                expected_verdict="SUPPORTED",
                expected_actions=("ESCALATE_TO_ENGINEER",),
                subsystem="feed_system",
            )
            domain = load_relations(TEP_CONFIG)
            result = evaluate_case(temp_root, case, domain)
            self.assertIs(result.verdict, Verdict.SUPPORTED)
            self.assertIs(
                result.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
            )
            self.assertTrue(result.passed)
            self.assertTrue(result.predicates.has_primary_signal_anomaly)

    def test_tep_feed_disturbance_abstains_when_cause_nominal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            processed = temp_root / "processed"
            processed.mkdir()
            case_csv = processed / "IDV_synthetic.csv"
            nominal_csv = processed / "IDV_synthetic_nominal.csv"
            header = ("XMEAS(1)", "XMV(3)", "XMEAS(7)")
            nominal_rows = [
                (0.50, 32.1, 2705.0),
                (0.52, 32.3, 2704.0),
                (0.48, 31.9, 2706.0),
                (0.51, 32.0, 2705.5),
                (0.49, 32.2, 2705.2),
                (0.53, 31.8, 2704.8),
            ]
            self._write_csv(nominal_csv, header, nominal_rows)
            # Only the symptom deviates; the configured cause signals stay nominal.
            fault_rows = [(0.5, 32.1, 3000.0), (0.5, 32.1, 3500.0), (0.5, 32.1, 4000.0)]
            self._write_csv(case_csv, header, nominal_rows + fault_rows)

            case = RealDataCase(
                case_id="IDV_synthetic_abstain",
                csv_path=case_csv,
                nominal_baseline_path=nominal_csv,
                expected_verdict="INSUFFICIENT",
                expected_actions=("ESCALATE_TO_ENGINEER",),
                subsystem="feed_system",
            )
            domain = load_relations(TEP_CONFIG)
            result = evaluate_case(temp_root, case, domain)
            self.assertIs(result.verdict, Verdict.INSUFFICIENT)
            self.assertIs(
                result.suggested_next_action, SuggestedAction.ESCALATE_TO_ENGINEER
            )
            self.assertTrue(result.passed)
            self.assertFalse(result.predicates.has_primary_signal_anomaly)


if __name__ == "__main__":
    unittest.main()
