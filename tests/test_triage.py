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
        self.assertEqual(
            headers, ("time", "FLOWCOOLFLOWRATE", "FLOWCOOLPRESSURE")
        )

    def test_phm_headers_select_the_flowcool_scenario(self) -> None:
        selection = select_profile(
            PHM_HEADERS, "flowcool excursion on the ion mill"
        )
        self.assertEqual(selection.config_name, "ion_mill_phm18")
        self.assertEqual(selection.scenario_name, "flowcool")
        self.assertEqual(selection.signal_coverage, 1.0)
        self.assertEqual(
            set(selection.matched_signals),
            {"FLOWCOOLFLOWRATE", "FLOWCOOLPRESSURE"},
        )

    def test_unknown_headers_raise_no_matching_profile(self) -> None:
        with self.assertRaises(NoMatchingProfile):
            select_profile(("alpha", "beta", "gamma"), "unknown tool")

    def test_scenario_less_config_is_not_runnable(self) -> None:
        with self.assertRaises(NoMatchingProfile):
            select_profile(TEP_HEADERS, "feed disturbance")


if __name__ == "__main__":
    unittest.main()
