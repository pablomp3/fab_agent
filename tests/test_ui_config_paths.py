from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from src.ui.app import _resolve_baseline_paths  # pyright: ignore[reportPrivateUsage]

_V2 = """version: 2
tool:
  name: fixture
baseline:
  mode: nominal_file
  file: ../../benchmarks/nominal.csv
signals:
  - {name: a, label: A, unit: null, alert_at: 3.5}
checks: []
"""


class BaselinePathTests(unittest.TestCase):
    def test_relative_nominal_file_resolves_from_the_saved_config(self) -> None:
        source = Path("/repo/config/sensor_relations/tool.yaml")

        resolved = yaml.safe_load(
            _resolve_baseline_paths(_V2, source)
        )

        self.assertEqual(
            resolved["baseline"]["file"], "/repo/benchmarks/nominal.csv"
        )

    def test_absolute_nominal_file_is_unchanged(self) -> None:
        text = _V2.replace("../../benchmarks/nominal.csv", "/data/nominal.csv")

        resolved = yaml.safe_load(
            _resolve_baseline_paths(text, Path("/repo/config/tool.yaml"))
        )

        self.assertEqual(resolved["baseline"]["file"], "/data/nominal.csv")

    def test_lead_in_baseline_is_unchanged(self) -> None:
        text = _V2.replace(
            "nominal_file\n  file: ../../benchmarks/nominal.csv",
            "lead_in\n  rows: 3",
        )

        self.assertEqual(
            _resolve_baseline_paths(text, Path("/repo/config/tool.yaml")), text
        )

    def test_missing_source_path_is_unchanged(self) -> None:
        self.assertEqual(_resolve_baseline_paths(_V2, None), _V2)


if __name__ == "__main__":
    unittest.main()
