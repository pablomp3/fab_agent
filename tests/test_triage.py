from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.triage import (
    NoMatchingProfile,
    read_csv_headers,
    select_profile,
)

PHM_HEADERS = (
    "time",
    "Tool",
    "stage",
    "Lot",
    "runnum",
    "recipe",
    "recipe_step",
    "IONGAUGEPRESSURE",
    "ETCHBEAMVOLTAGE",
    "ETCHBEAMCURRENT",
    "ETCHSUPPRESSORVOLTAGE",
    "ETCHSUPPRESSORCURRENT",
    "FLOWCOOLFLOWRATE",
    "FLOWCOOLPRESSURE",
)
TEP_HEADERS = ("time", "XMEAS(1)", "XMV(3)", "XMEAS(7)")


class TriageTests(unittest.TestCase):
    def test_read_csv_headers_returns_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "export.csv"
            csv_path.write_text(
                "time,FLOWCOOLFLOWRATE,FLOWCOOLPRESSURE\n1,10,10\n",
                encoding="utf-8",
            )
            headers = read_csv_headers(csv_path)
        self.assertEqual(headers, ("time", "FLOWCOOLFLOWRATE", "FLOWCOOLPRESSURE"))

    def test_phm_headers_select_the_coolant_scenario(self) -> None:
        selection = select_profile(PHM_HEADERS, "flowcool excursion on the ion mill")
        self.assertEqual(selection.config_name, "ion_mill_phm18")
        self.assertEqual(selection.scenario_name, "coolant_loop")
        self.assertEqual(selection.signal_coverage, 1.0)
        self.assertEqual(
            set(selection.matched_signals),
            {"FLOWCOOLFLOWRATE", "FLOWCOOLPRESSURE"},
        )

    def test_unknown_headers_raise_no_matching_profile(self) -> None:
        with self.assertRaises(NoMatchingProfile):
            select_profile(("alpha", "beta", "gamma"), "unknown tool")

    def test_missing_primary_signal_still_selects_the_tool_model(self) -> None:
        # A missing required channel must reach the check and become
        # Data Incomplete; it must not fall through to Auto mode just because
        # the primary-signal subset is no longer complete.
        headers = tuple(
            name for name in PHM_HEADERS if name != "FLOWCOOLFLOWRATE"
        )
        selection = select_profile(headers, "flowcool excursion")
        self.assertEqual(selection.config_name, "ion_mill_phm18")
        self.assertEqual(selection.scenario_name, "coolant_loop")
        self.assertAlmostEqual(selection.signal_coverage, 6 / 7)
        self.assertEqual(selection.matched_signals, ("FLOWCOOLPRESSURE",))

    def test_scenario_less_config_is_not_runnable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "no_scenarios.yaml"
            config_path.write_text(
                "version: 1\n"
                "name: no_scenarios\n"
                "provenance: triage test\n"
                "signals:\n"
                '  - {name: "XMEAS(1)", unit: null, '
                "robust_z_threshold: null, threshold_source: null}\n"
                '  - {name: "XMV(3)", unit: null, '
                "robust_z_threshold: null, threshold_source: null}\n"
                '  - {name: "XMEAS(7)", unit: null, '
                "robust_z_threshold: null, threshold_source: null}\n",
                encoding="utf-8",
            )
            with self.assertRaises(NoMatchingProfile):
                select_profile(TEP_HEADERS, "feed disturbance", search_dir=temp_dir)


if __name__ == "__main__":
    unittest.main()
