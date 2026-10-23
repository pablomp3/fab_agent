from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.analyze import RunResult, analyze_csv
from src.config_loader import load_relations
from src.core.types import AnalysisOutcome, Evidence, EvidenceKind
from src.ui import config_promotion, presentation

_PHM_EXPORT = (
    "time,FLOWCOOLFLOWRATE,FLOWCOOLPRESSURE\n"
    "1,10.0,10.0\n2,11.0,11.0\n3,10.0,10.0\n"
    "4,11.0,11.0\n5,10.0,10.0\n6,1000.0,11.0\n"
)
_UNKNOWN_EXPORT = (
    "a,b,c\n10.0,10.0,10.0\n11.0,11.0,11.0\n10.0,10.0,10.0\n"
    "11.0,11.0,11.0\n10.0,10.0,10.0\n1000.0,11.0,11.0\n"
)


def _run(text: str, note: str) -> RunResult:
    transport = ExperimentalEchoTransport()
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "export.csv"
        path.write_text(text, encoding="utf-8")
        return analyze_csv(
            path,
            note,
            engine_factory=offline_engine_factory(transport),
            mapping_factory=offline_mapping_factory(transport),
        )


class OutcomeWordingTests(unittest.TestCase):
    def test_every_outcome_has_human_label_and_tone(self) -> None:
        allowed = {"success", "info", "warning", "error"}
        for outcome in AnalysisOutcome:
            label = presentation.outcome_label(outcome)
            self.assertTrue(label)
            self.assertNotEqual(label, outcome.value)
            self.assertIn(presentation.outcome_tone(outcome), allowed)


class SummaryTests(unittest.TestCase):
    def test_safe_run_shows_label_not_raw_action(self) -> None:
        result = _run(_PHM_EXPORT, "flowcool")
        summary = presentation.summarize(result)
        self.assertEqual(summary.mode_label, "Deterministic safe path")
        self.assertNotEqual(summary.action_label, result.suggested_next_action.value)
        self.assertTrue(summary.analysis_performed)

    def test_experimental_run_is_labelled_unverified(self) -> None:
        result = _run(_UNKNOWN_EXPORT, "unknown tool")
        summary = presentation.summarize(result)
        self.assertIn("Experimental", summary.mode_label)
        self.assertEqual(summary.action_label, "Review the draft mapping")
        self.assertEqual(summary.outcome_label, "Unverified mapping (experimental)")


class TableTests(unittest.TestCase):
    def test_evidence_rows_keep_absent_values_explicit(self) -> None:
        evidence = Evidence(
            evidence_id="EV_x",
            kind=EvidenceKind.MISSING_CHANNEL,
            signal=None,
            statistic=None,
            value=None,
            unit=None,
            window=None,
            provenance="unverified_mapping",
            computed_by="experimental_mapping@v1",
            summary="channel absent",
        )
        row = presentation.evidence_rows((evidence,))[0]
        self.assertEqual(row.unit, presentation.MISSING)
        self.assertEqual(row.value, presentation.MISSING)
        self.assertEqual(row.signal, presentation.MISSING)

    def test_hypothesis_rows_carry_python_status(self) -> None:
        result = _run(_PHM_EXPORT, "flowcool")
        rows = presentation.hypothesis_rows(result.output)
        self.assertEqual(len(rows), len(result.output.hypotheses))
        for row in rows:
            self.assertIn(row.status, {"SUPPORTED", "INSUFFICIENT", "VETOED"})

    def test_mapping_rows_surface_guess_without_propagating_unit(self) -> None:
        result = _run(_UNKNOWN_EXPORT, "unknown tool")
        self.assertIsNotNone(result.mapping)
        assert result.mapping is not None
        signals = presentation.mapping_signal_rows(result.mapping)
        self.assertTrue(signals)
        relationships = presentation.mapping_relationship_rows(result.mapping)
        self.assertEqual(len(relationships), len(result.mapping.relationships))
        for evidence in result.evidence:
            self.assertIsNone(evidence.unit)

    def test_model_narrative_is_separate_from_the_gated_claim(self) -> None:
        result = _run(_PHM_EXPORT, "flowcool")
        rows = presentation.model_narrative_rows(result.output)
        self.assertTrue(rows)
        gated = result.output.hypotheses[0]
        self.assertEqual(gated.claim, "flowcool subsystem fault")
        self.assertIsNotNone(gated.model_narrative)
        assert gated.model_narrative is not None
        self.assertEqual(gated.model_narrative.claim, rows[0].claim)
        self.assertNotEqual(rows[0].claim, gated.claim)

    def test_markdown_table_escapes_cell_text(self) -> None:
        table = presentation.markdown_table([{"a": "x|y", "b": "l1\nl2"}])
        self.assertIn("x\\|y", table)
        self.assertIn("l1 l2", table)
        self.assertEqual(presentation.markdown_table([]), "")


class AppSmokeTests(unittest.TestCase):
    def test_app_module_is_importable(self) -> None:
        from src.ui import app

        self.assertTrue(callable(app.main))


class DraftConfigTests(unittest.TestCase):
    def _draft(self) -> str:
        result = _run(_UNKNOWN_EXPORT, "unknown tool")
        self.assertIsNotNone(result.draft_yaml)
        assert result.draft_yaml is not None
        return result.draft_yaml

    def test_slugify_rejects_unsafe_names(self) -> None:
        self.assertEqual(
            config_promotion.slugify_config_name("My Tool 2"), "my_tool_2"
        )
        with self.assertRaises(config_promotion.DraftConfigError):
            config_promotion.slugify_config_name("1bad")
        with self.assertRaises(config_promotion.DraftConfigError):
            config_promotion.slugify_config_name("   ")

    def test_valid_draft_saves_and_reloads(self) -> None:
        draft = self._draft()
        with TemporaryDirectory() as temp_dir:
            saved = config_promotion.save_draft_config(
                draft, "my_tool", config_dir=temp_dir
            )
            self.assertEqual(saved.name, "my_tool.yaml")
            self.assertTrue(saved.is_file())
            loaded = load_relations(saved)
            self.assertEqual(loaded.name, "experimental_draft")

    def test_overwrite_requires_explicit_flag(self) -> None:
        draft = self._draft()
        with TemporaryDirectory() as temp_dir:
            config_promotion.save_draft_config(
                draft, "my_tool", config_dir=temp_dir
            )
            with self.assertRaises(config_promotion.DraftConfigError):
                config_promotion.save_draft_config(
                    draft, "my_tool", config_dir=temp_dir
                )
            again = config_promotion.save_draft_config(
                draft, "my_tool", config_dir=temp_dir, overwrite=True
            )
            self.assertTrue(again.is_file())

    def test_invalid_draft_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(config_promotion.DraftConfigError):
                config_promotion.save_draft_config(
                    "", "my_tool", config_dir=temp_dir
                )
            bad_schema = (
                "version: 2\nname: x\nprovenance: y\nsignals: []\nscenarios: {}\n"
            )
            with self.assertRaises(config_promotion.DraftConfigError):
                config_promotion.save_draft_config(
                    bad_schema, "my_tool", config_dir=temp_dir
                )
            with self.assertRaises(config_promotion.DraftConfigError):
                config_promotion.save_draft_config(
                    "not: [valid", "my_tool", config_dir=temp_dir
                )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
