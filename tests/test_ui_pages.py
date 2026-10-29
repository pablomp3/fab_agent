from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.action_guidance import action_explanation
from src.analyze import RunResult, analyze_csv
from src.core.types import SuggestedAction
from src.demo_catalog import DEMO_CASES
from src.ui import config_promotion, presentation


def _run_file(key: str) -> RunResult:
    case = DEMO_CASES[key]
    transport = ExperimentalEchoTransport()
    return analyze_csv(
        case.csv_path,
        case.note,
        engine_factory=offline_engine_factory(transport),
        mapping_factory=offline_mapping_factory(transport),
        enable_external_search=False,
    )


class SignalLabelTests(unittest.TestCase):
    def test_saved_labels_reach_the_run_result(self) -> None:
        result = _run_file("synthetic_flowcool_supported")
        labels = dict(result.signal_labels)
        self.assertEqual(labels["FLOWCOOLFLOWRATE"], "Coolant flow")
        self.assertEqual(labels["FLOWCOOLPRESSURE"], "Coolant pressure")

    def test_confirmed_card_uses_labels_not_raw_columns(self) -> None:
        card = presentation.answer_card(_run_file("synthetic_flowcool_supported"))
        self.assertEqual(card.confidence_label, "Fault Confirmed")
        self.assertIn("Coolant flow", card.headline)
        self.assertNotIn("FLOWCOOLFLOWRATE", card.headline)

    def test_differential_rows_use_labels(self) -> None:
        result = _run_file("synthetic_flowcool_supported")
        rows = presentation.differential_rows(
            result.output,
            result.evidence,
            presentation.signal_labels(result),
        )
        self.assertTrue(rows)
        self.assertIn("Coolant flow", rows[0].evidence_for)
        self.assertNotIn("FLOWCOOLFLOWRATE", rows[0].evidence_for)

    def test_what_else_moved_uses_labels_and_plain_z(self) -> None:
        result = _run_file("phm_flowcool_supported")
        self.assertEqual(presentation.result_word(result), "Needs Review")
        rows = presentation.unexplained_rows(result)
        self.assertTrue(rows)
        names = {row.signal for row in rows}
        self.assertIn("Beam voltage", names)
        self.assertNotIn("ETCHBEAMVOLTAGE", names)
        self.assertTrue(
            all(
                "z" in row.peak_deviation or "very large" in row.peak_deviation
                for row in rows
            )
        )
        self.assertTrue(any("Large" in row.meaning for row in rows))


class AuditTests(unittest.TestCase):
    def test_payload_size_is_bounded_and_reported(self) -> None:
        result = _run_file("phm_flowcool_supported")
        size = presentation.model_payload_bytes(result)
        self.assertGreater(size, 0)
        self.assertLessEqual(size, 2048)
        self.assertIn("2048 limit", presentation.model_payload_text(result))

    def test_model_roles_never_show_a_model_id(self) -> None:
        result = _run_file("synthetic_flowcool_supported")
        text = presentation.model_role_text(result)
        self.assertIn("cause finder", text)
        self.assertIn("challenge check", text)
        self.assertNotIn("/", text)
        self.assertNotIn("nvidia", text.casefold())

    def test_auto_run_reports_the_column_mapper(self) -> None:
        result = _run_file("unknown_export")
        self.assertIn("column mapper", presentation.model_roles(result))

    def test_challenge_audit_keeps_the_raw_record(self) -> None:
        result = _run_file("tep_feed_supported")
        rows = presentation.challenge_audit_rows(result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Status"], "checked")
        self.assertEqual(rows[0]["Expectation met"], "Yes")
        self.assertIn("EV_", rows[0]["Evidence IDs"])

    def test_evidence_rows_keep_raw_status_and_id(self) -> None:
        result = _run_file("synthetic_flowcool_supported")
        rows = presentation.evidence_rows(result.evidence)
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row.evidence_id.startswith("EV_"))
            self.assertIn(
                row.raw_status,
                {
                    "SENSOR_ANOMALY",
                    "SENSOR_NOMINAL",
                    "MISSING_CHANNEL",
                    "NOT_EVALUATED",
                },
            )

    def test_no_challenge_returns_no_audit_rows(self) -> None:
        result = _run_file("phm_flowcool_supported")
        self.assertEqual(presentation.challenge_audit_rows(result), [])

    def test_continue_monitoring_is_not_worded_as_a_fault(self) -> None:
        explanation = action_explanation(SuggestedAction.CONTINUE_MONITORING)
        self.assertNotIn("supports a fault", explanation)


class ConfigEditorTests(unittest.TestCase):
    def test_custom_template_is_v2_commented_and_loads(self) -> None:
        template = config_promotion.CUSTOM_TOOL_MODEL_TEMPLATE
        self.assertTrue(template.startswith("# Tool model"))
        self.assertNotIn("version:", template)
        self.assertIn("# Signals are the only columns", template)
        self.assertIn("# A check is one fault pattern", template)
        config_promotion.validate_draft_yaml(template)

    def test_stale_loader_error_names_the_restart_action(self) -> None:
        def _old_loader(path: Path) -> object:
            raise ValueError(
                "configuration has unknown keys: baseline, checks, tool"
            )

        with patch.object(config_promotion, "load_relations", _old_loader):
            with self.assertRaises(config_promotion.DraftConfigError) as raised:
                config_promotion.validate_draft_yaml(
                    config_promotion.CUSTOM_TOOL_MODEL_TEMPLATE
                )
        self.assertIn("Restart", str(raised.exception))
        self.assertIn("tool model itself is fine", str(raised.exception))


class LoaderSmokeTests(unittest.TestCase):
    def test_loaded_engine_knows_the_v2_schema(self) -> None:
        from src.ui import app

        self.assertTrue(
            app._v2_loader_ready()  # pyright: ignore[reportPrivateUsage]
        )


class BenchmarkSummaryTests(unittest.TestCase):
    def test_valid_summary_rows_are_accepted(self) -> None:
        payload = {
            "systems": [
                {
                    "system": "FabAgent",
                    "unsafe_action_rate": 0.0,
                    "correct_cause_rate": 1.0,
                    "appropriate_abstention": 1.0,
                    "false_alarm_rate": 0.0,
                    "evidence_accuracy": 1.0,
                    "n": 8,
                }
            ]
        }
        rows = presentation.benchmark_summary_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["system"], "FabAgent")

    def test_invalid_summary_is_not_rendered(self) -> None:
        self.assertEqual(presentation.benchmark_summary_rows({}), [])
        self.assertEqual(
            presentation.benchmark_summary_rows({"systems": [{"system": "x"}]}), []
        )
        self.assertEqual(presentation.benchmark_summary_rows("nope"), [])

    def test_compact_score_is_safe_plus_cause_plus_abstention(self) -> None:
        from src.ui import app

        rows = [{"system": "FabAgent (deterministic gate)"}]
        records = [
            {
                "provider": "fabagent",
                "unsafe": False,
                "correct_cause": True,
                "appropriate_abstention": True,
            },
            {
                "provider": "fabagent",
                "unsafe": False,
                "correct_cause": None,
                "appropriate_abstention": None,
            },
            {
                "provider": "fabagent",
                "unsafe": False,
                "correct_cause": True,
                "appropriate_abstention": None,
            },
            {
                "provider": "fabagent",
                "unsafe": False,
                "correct_cause": True,
                "appropriate_abstention": None,
            },
        ]

        display = app._benchmark_display_rows(rows, records)  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(display[0]["Score"], ":green[**8/8 pts**]")


class PageSourceTests(unittest.TestCase):
    def test_performance_page_no_longer_has_the_old_chart(self) -> None:
        from src.ui import app

        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertNotIn("Operational Decisiveness", source)
        self.assertNotIn("100% vs 0%", source)
        self.assertIn("Benchmark in progress", source)

    def test_app_contains_the_three_layer_cards(self) -> None:
        from src.ui import app

        source = Path(app.__file__).read_text(encoding="utf-8")
        for text in (
            "Possible causes",
            "What else moved",
            "Audit",
            "Tool model YAML",
            "What the YAML means (advanced)",
        ):
            self.assertIn(text, source)


class AppTestSmokeTests(unittest.TestCase):
    def test_start_page_renders_the_new_positioning(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "src" / "ui" / "app.py"
        app_test = AppTest.from_file(str(app_path), default_timeout=30).run()
        self.assertEqual([item.value for item in app_test.exception], [])
        self.assertTrue(
            any("manufacturing copilot" in item.value for item in app_test.title)
        )


if __name__ == "__main__":
    unittest.main()
