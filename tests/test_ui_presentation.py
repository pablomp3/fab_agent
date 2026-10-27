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
from src.demo_catalog import DEMO_CASES
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


def _run_file(path: Path, note: str) -> RunResult:
    transport = ExperimentalEchoTransport()
    return analyze_csv(
        path,
        note,
        engine_factory=offline_engine_factory(transport),
        mapping_factory=offline_mapping_factory(transport),
        enable_external_search=False,
    )


class OutcomeWordingTests(unittest.TestCase):
    def test_every_outcome_has_human_label_and_tone(self) -> None:
        allowed = {"success", "info", "warning", "error"}
        for outcome in AnalysisOutcome:
            label = presentation.outcome_label(outcome)
            self.assertTrue(label)
            self.assertNotEqual(label, outcome.value)
            self.assertIn(presentation.outcome_tone(outcome), allowed)

    def test_glossary_is_populated_and_valid(self) -> None:
        self.assertTrue(hasattr(presentation, "GLOSSARY"))
        self.assertGreaterEqual(len(presentation.GLOSSARY), 10)
        for term, definition in presentation.GLOSSARY:
            self.assertTrue(term)
            self.assertTrue(definition)


class SummaryTests(unittest.TestCase):
    def test_safe_run_shows_label_not_raw_action(self) -> None:
        result = _run(_PHM_EXPORT, "flowcool")
        summary = presentation.summarize(result)
        self.assertEqual(summary.mode_label, "Known machine (Safe path)")
        self.assertNotEqual(summary.action_label, result.suggested_next_action.value)
        self.assertTrue(summary.analysis_performed)

    def test_experimental_run_is_labelled_unverified(self) -> None:
        result = _run(_UNKNOWN_EXPORT, "unknown tool")
        summary = presentation.summarize(result)
        self.assertIn("guessed columns", summary.mode_label)
        self.assertEqual(summary.action_label, "Review the guessed columns")
        self.assertEqual(summary.outcome_label, "Unknown Machine")


class ResultWordTests(unittest.TestCase):
    def test_the_six_result_words_are_exact(self) -> None:
        self.assertEqual(
            set(presentation.RESULT_WORDS),
            {
                "Fault Confirmed",
                "Regular Behavior",
                "Sensors Disagree",
                "Data Incomplete",
                "Needs Review",
                "Unknown Machine",
            },
        )
        for word in presentation.RESULT_WORDS:
            self.assertTrue(presentation.result_badge(word))
            self.assertIn(
                presentation.result_tone(word),
                {"success", "info", "warning", "error"},
            )

    def test_unexplained_anomaly_is_needs_review_not_regular(self) -> None:
        case = DEMO_CASES["tep_unmodeled"]
        result = _run_file(case.csv_path, case.note)
        self.assertEqual(presentation.result_word(result), "Needs Review")
        card = presentation.answer_card(result)
        self.assertEqual(card.confidence_label, "Needs Review")
        self.assertNotIn("Every checked signal is within", card.headline)
        self.assertIn("no saved check explains it", card.headline)
        self.assertEqual(card.action_label, "Ask an engineer to review")

    def test_differential_rows_use_signals_and_result_words(self) -> None:
        result = _run_file(
            Path(__file__).resolve().parents[1]
            / "samples"
            / "flowcool_supported.csv",
            "flowcool",
        )
        rows = presentation.differential_rows(result.output, result.evidence)
        self.assertTrue(rows)
        self.assertEqual(rows[0].possible_cause, "Coolant loop fault")
        self.assertEqual(rows[0].result, "Fault Confirmed")
        self.assertIn("FLOWCOOLFLOWRATE", rows[0].evidence_for)
        self.assertNotIn("EV_", rows[0].evidence_for)

    def test_flat_run_is_regular_behavior(self) -> None:
        case = DEMO_CASES["synthetic_flowcool_inconclusive"]
        result = _run_file(case.csv_path, case.note)
        self.assertEqual(presentation.result_word(result), "Regular Behavior")
        card = presentation.answer_card(result)
        self.assertIn("Every checked signal stayed below", card.headline)
        self.assertEqual(card.action_label, "Keep monitoring")

    def test_contradiction_is_sensors_disagree_and_instrumentation_cause(self) -> None:
        case = DEMO_CASES["synthetic_rf_veto"]
        result = _run_file(case.csv_path, case.note)
        self.assertEqual(presentation.result_word(result), "Sensors Disagree")
        self.assertEqual(
            result.output.hypotheses[0].root_cause.value, "instrumentation_fault"
        )
        card = presentation.answer_card(result)
        self.assertEqual(card.confidence_label, "Sensors Disagree")
        self.assertEqual(card.action_label, "Check the sensor first")

    def test_alert_threshold_comes_from_the_config(self) -> None:
        case = DEMO_CASES["synthetic_flowcool_supported"]
        result = _run_file(case.csv_path, case.note)
        rows = presentation.evidence_rows(result.evidence)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row.alert_threshold, "3.50z")

    def test_main_ui_copy_has_no_internal_enums(self) -> None:
        forbidden = (
            "VETOED",
            "SUPPORTED",
            "INSUFFICIENT",
            "EXPERIMENTAL",
            "UNVERIFIED",
            "hypothesis_class",
            "predicate",
            "candidate",
            "gate",
            "veto",
        )
        for case in DEMO_CASES.values():
            result = _run_file(case.csv_path, case.note)
            card = presentation.answer_card(result)
            summary = presentation.summarize(result)
            copy = " ".join(
                (
                    card.headline,
                    card.confidence_label,
                    card.confidence_badge,
                    card.confidence_help,
                    card.action_label,
                    card.action_explanation,
                    summary.outcome_label,
                    summary.mode_label,
                    summary.triage,
                    summary.explanation,
                )
            )
            for token in forbidden:
                self.assertNotIn(token, copy, f"{case.key}: {token}")


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
        self.assertEqual(gated.claim, "Coolant loop fault")
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
        self.assertEqual(config_promotion.slugify_config_name("My Tool 2"), "my_tool_2")
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
            config_promotion.save_draft_config(draft, "my_tool", config_dir=temp_dir)
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
                config_promotion.save_draft_config("", "my_tool", config_dir=temp_dir)
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
