from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.analyze import analyze_csv
from src.core.progress import (
    STAGE_GATE,
    STAGE_MAPPING,
    STAGE_MODEL,
    STAGE_READ,
    STAGE_TAVILY,
    ProgressCallback,
    ProgressState,
)
from src.demo_catalog import DEMO_CASES
from src.demo_data import generate_demo_csv


def _run(
    csv_bytes: bytes,
    config_path: str | None,
    progress: ProgressCallback | None = None,
):
    transport = ExperimentalEchoTransport()
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "generated.csv"
        path.write_bytes(csv_bytes)
        if config_path is None:
            return analyze_csv(
                path,
                "generated demo",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
                progress=progress,
            )
        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir()
        (config_dir / "tool.yaml").write_bytes(Path(config_path).read_bytes())
        return analyze_csv(
            path,
            "generated demo",
            search_dir=config_dir,
            engine_factory=offline_engine_factory(transport),
            mapping_factory=offline_mapping_factory(transport),
            progress=progress,
        )


class DemoDataTests(unittest.TestCase):
    def test_seed_is_reproducible(self) -> None:
        first = generate_demo_csv("flowcool", seed=3, behavior="supported")
        second = generate_demo_csv("flowcool", seed=3, behavior="supported")
        self.assertEqual(first.csv_bytes, second.csv_bytes)
        self.assertIn(b"FLOWCOOLFLOWRATE", first.csv_bytes)

    def test_invalid_behavior_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            generate_demo_csv("flowcool", behavior="contradiction")

    def test_supported_generator_reaches_the_safe_path(self) -> None:
        generated = generate_demo_csv("flowcool", seed=3, behavior="supported")
        result = _run(
            generated.csv_bytes,
            str(generated.template.config_path),
        )
        self.assertEqual(result.mode, "safe")
        self.assertEqual(result.outcome.value, "ANALYSIS_SUPPORTED")

    def test_contradiction_generator_is_vetoed(self) -> None:
        generated = generate_demo_csv(
            "synthetic_rf", seed=3, behavior="contradiction"
        )
        result = _run(
            generated.csv_bytes,
            str(generated.template.config_path),
        )
        self.assertEqual(result.outcome.value, "ANALYSIS_CONTRADICTED")

    def test_unknown_generator_reaches_experimental(self) -> None:
        generated = generate_demo_csv("unknown_tool", seed=3, behavior="supported")
        result = _run(generated.csv_bytes, None)
        self.assertEqual(result.mode, "experimental")
        self.assertEqual(result.outcome.value, "EXPERIMENTAL_UNVERIFIED_MAPPING")

    def test_safe_progress_reports_each_stage(self) -> None:
        events: list[tuple[str, ProgressState]] = []
        generated = generate_demo_csv("flowcool", seed=3, behavior="supported")
        result = _run(
            generated.csv_bytes,
            str(generated.template.config_path),
            progress=lambda step, state: events.append((step, state)),
        )
        self.assertEqual(result.outcome.value, "ANALYSIS_SUPPORTED")
        self.assertIn((STAGE_READ, "done"), events)
        self.assertIn((STAGE_MODEL, "done"), events)
        self.assertIn((STAGE_GATE, "done"), events)
        self.assertIn((STAGE_TAVILY, "skipped"), events)
        self.assertNotIn((STAGE_MAPPING, "done"), events)

    def test_experimental_progress_reports_mapping_and_narrative(self) -> None:
        events: list[tuple[str, ProgressState]] = []
        generated = generate_demo_csv("unknown_tool", seed=3, behavior="supported")
        result = _run(
            generated.csv_bytes,
            None,
            progress=lambda step, state: events.append((step, state)),
        )
        self.assertEqual(result.outcome.value, "EXPERIMENTAL_UNVERIFIED_MAPPING")
        self.assertIn((STAGE_MAPPING, "done"), events)
        self.assertIn((STAGE_MODEL, "done"), events)
        self.assertIn((STAGE_GATE, "done"), events)

    def test_progress_callback_failure_cannot_break_the_run(self) -> None:
        def broken(step: str, state: ProgressState) -> None:
            raise RuntimeError(f"progress failed at {step}: {state}")

        generated = generate_demo_csv("flowcool", seed=3, behavior="supported")
        result = _run(
            generated.csv_bytes,
            str(generated.template.config_path),
            progress=broken,
        )
        self.assertEqual(result.outcome.value, "ANALYSIS_SUPPORTED")


class DemoCatalogTests(unittest.TestCase):
    def test_every_demo_has_a_readable_csv_and_optional_config(self) -> None:
        self.assertGreaterEqual(len(DEMO_CASES), 6)
        for case in DEMO_CASES.values():
            self.assertTrue(case.csv_path.is_file(), case.csv_path)
            if case.config_path is not None:
                self.assertTrue(case.config_path.is_file(), case.config_path)

    def test_every_demo_is_labelled_as_a_dataset(self) -> None:
        for case in DEMO_CASES.values():
            self.assertIn("dataset", case.label.lower())
            self.assertTrue(case.expected)
            self.assertTrue(case.column_notes)


if __name__ == "__main__":
    unittest.main()
