from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.evaluator.naive_llm_benchmark import (
    ParsedAnswer,
    build_prompt,
    ingest_response,
    load_cases,
    parse_response,
    run_benchmark,
    score_case,
    select_cases,
    write_runbooks,
)
from src.ui import presentation


class _FakeTransport:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _answer(
    *,
    cause: str = "equipment_fault",
    action: str = "INSPECT_COMPONENT",
    abstain: bool = False,
    findings: tuple[tuple[str, str], ...] = (),
) -> ParsedAnswer:
    from benchmarks.evaluator.naive_llm_benchmark import Finding

    return ParsedAnswer(
        findings=tuple(
            Finding(signal=signal, status=status) for signal, status in findings
        ),
        cause=cause,
        action=action,
        abstain=abstain,
        why="fixture",
    )


class CaseTests(unittest.TestCase):
    def test_cases_are_unique_complete_and_balanced(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), 8)
        self.assertEqual(len({case.id for case in cases}), 8)
        for case in cases:
            self.assertTrue(case.input_path.is_file(), case.id)
            self.assertIn(
                case.expected.cause,
                {
                    "equipment_fault",
                    "instrumentation_fault",
                    "upstream_process",
                    "process_drift",
                    "material_issue",
                    "none",
                    "unknown",
                },
            )
            self.assertTrue(case.expected.result)
            self.assertTrue(case.title)
        self.assertEqual(
            sum(1 for case in cases if case.expected.false_alarm_case), 1
        )
        self.assertEqual(
            sum(1 for case in cases if case.expected.should_abstain), 2
        )

    def test_select_cases_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            select_cases(load_cases(), ("not_a_case",))

    def test_select_cases_accepts_numbers_and_ids(self) -> None:
        selected = select_cases(load_cases(), ("1", "phm_nominal"))
        self.assertEqual(
            [case.id for case in selected],
            ["phm_coolant_coverage", "phm_nominal"],
        )


class PromptTests(unittest.TestCase):
    def test_prompt_has_no_case_dataset_or_answer_leak(self) -> None:
        forbidden = (
            "PHM",
            "TEP",
            "M02",
            "IDV",
            "Sensor Conflict",
            "Regular Healthy Run",
            "ground truth",
            "expected action",
            "engineer alarm",
        )
        for case in load_cases():
            for track in ("evidence", "raw"):
                prompt = build_prompt(
                    case,
                    track,
                    evidence_json='{"evidence":[]}',
                    raw_csv="time,signal\n1,10\n",
                )
                self.assertNotIn(case.id, prompt, f"{case.id}:{track}")
                self.assertNotIn(case.title, prompt, f"{case.id}:{track}")
                for token in forbidden:
                    self.assertNotIn(token, prompt, f"{case.id}:{track}:{token}")

    def test_prompt_contains_the_action_menu_but_not_a_choice(self) -> None:
        case = select_cases(load_cases(), ("phm_nominal",))[0]
        prompt = build_prompt(case, "evidence", evidence_json='{"evidence":[]}')
        for action in (
            "INSPECT_COMPONENT",
            "CONTINUE_MONITORING",
            "HOLD_LOT",
            "ADJUST_RECIPE",
        ):
            self.assertIn(action, prompt)
        self.assertNotIn("choose CONTINUE_MONITORING", prompt)


class ParsingTests(unittest.TestCase):
    def test_parse_handles_prose_and_code_fences(self) -> None:
        text = (
            "I inspected the channels.\n"
            "```json\n"
            '{"findings":[{"signal":"a","status":"anomaly"}],'
            '"cause":"equipment_fault","action":"inspect_component",'
            '"abstain":false,"why":"a moved"}\n'
            "```\n"
        )
        answer = parse_response(text)
        self.assertEqual(answer.action, "INSPECT_COMPONENT")
        self.assertEqual(answer.cause, "equipment_fault")
        self.assertEqual(answer.findings[0].status, "unusual")

    def test_parse_canonicalizes_legacy_aliases(self) -> None:
        answer = parse_response(
            '{"cause":"regular_behavior","action":"HALT_TOOL_HOLD_LOT",'
            '"abstain":false,"findings":[],"why":"x"}'
        )
        self.assertEqual(answer.cause, "none")
        self.assertEqual(answer.action, "HOLD_LOT")

    def test_missing_answer_is_a_recorded_failure(self) -> None:
        case = select_cases(load_cases(), ("phm_nominal",))[0]
        score = score_case(case, None, parse_error="unparsable")
        self.assertTrue(score["unsafe"])
        self.assertIs(score["correct_cause"], False)
        self.assertEqual(score["parse_error"], "unparsable")


class ScoringTests(unittest.TestCase):
    def test_safe_action_on_nominal_case(self) -> None:
        case = select_cases(load_cases(), ("phm_nominal",))[0]
        safe = score_case(
            case,
            _answer(cause="none", action="CONTINUE_MONITORING"),
        )
        self.assertFalse(safe["unsafe"])
        self.assertTrue(safe["correct_cause"])
        self.assertFalse(safe["false_alarm"])

        alarm = score_case(case, _answer(cause="equipment_fault"))
        self.assertTrue(alarm["unsafe"])
        self.assertTrue(alarm["false_alarm"])

    def test_confirmed_fault_rejects_recipe_and_hold(self) -> None:
        case = select_cases(load_cases(), ("synthetic_positive_b4e",))[0]
        inspect = score_case(case, _answer())
        self.assertFalse(inspect["unsafe"])
        self.assertTrue(inspect["correct_cause"])
        for action in ("HOLD_LOT", "ADJUST_RECIPE"):
            score = score_case(case, _answer(action=action))
            self.assertTrue(score["unsafe"], action)

    def test_abstention_is_scored_on_the_unmodeled_case(self) -> None:
        case = select_cases(load_cases(), ("tep_unmodeled",))[0]
        abstain = score_case(
            case,
            _answer(
                cause="unknown",
                action="ESCALATE_TO_ENGINEER",
                abstain=True,
            ),
        )
        self.assertTrue(abstain["appropriate_abstention"])
        confident = score_case(case, _answer(cause="upstream_process"))
        self.assertFalse(confident["correct_cause"])
        self.assertFalse(confident["appropriate_abstention"])

    def test_evidence_accuracy_uses_expected_sets(self) -> None:
        case = select_cases(load_cases(), ("synthetic_conflict_b4a",))[0]
        answer = _answer(
            cause="instrumentation_fault",
            action="INSPECT_SENSOR_CALIBRATION",
            findings=(
                ("sensor_17", "unusual"),
                ("impedance", "normal"),
                ("thermal", "normal"),
                ("pressure", "normal"),
            ),
        )
        score = score_case(case, answer)
        self.assertEqual(score["evidence_accuracy"], 1.0)


class ArtifactTests(unittest.TestCase):
    def test_run_writes_prompt_case_manifest_and_summary(self) -> None:
        case = select_cases(load_cases(), ("phm_nominal",))[0]
        response = json.dumps(
            {
                "findings": [
                    {"signal": "FLOWCOOLFLOWRATE", "status": "normal"},
                    {"signal": "FLOWCOOLPRESSURE", "status": "normal"},
                ],
                "cause": "none",
                "action": "CONTINUE_MONITORING",
                "abstain": False,
                "why": "quiet",
            }
        )
        transport = _FakeTransport(response)
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "results"
            summary = run_benchmark(
                (case,),
                provider="gemini",
                track="evidence",
                model="fixture/model",
                out_dir=out,
                transport=transport,
            )
            self.assertTrue((out / "manifest.json").is_file())
            self.assertTrue((out / "summary.json").is_file())
            self.assertTrue((out / "prompts" / "gemini" / f"{case.id}.txt").is_file())
            self.assertTrue((out / "gemini" / f"{case.id}.json").is_file())
            self.assertTrue((out / "fabagent" / f"{case.id}.json").is_file())
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["prompt_version"], "naive-llm-v1")
            self.assertEqual(len(manifest["runs"]), 1)
            artifact = json.loads((out / "gemini" / f"{case.id}.json").read_text())
            self.assertEqual(artifact["score"]["action"], "CONTINUE_MONITORING")
            self.assertIn("raw_response", artifact)
            self.assertNotIn("raw_response", summary)
            self.assertTrue(presentation.benchmark_summary_rows(summary))

    def test_unparsable_ingest_is_recorded_not_dropped(self) -> None:
        case = select_cases(load_cases(), ("phm_nominal",))[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out = root / "results"
            response = root / "response.txt"
            response.write_text("I cannot answer in JSON.", encoding="utf-8")
            summary = ingest_response(
                (case,),
                provider="openai",
                track="evidence",
                model="manual",
                out_dir=out,
                case_id=case.id,
                response_path=response,
            )
            artifact = json.loads(
                (out / "openai" / f"{case.id}.json").read_text()
            )
            self.assertEqual(artifact["score"]["action"], "UNPARSABLE")
            self.assertTrue(artifact["score"]["unsafe"])
            self.assertEqual(summary["case_count"], 1)

    def test_missing_channel_case_reaches_data_incomplete(self) -> None:
        case = select_cases(load_cases(), ("missing_coolant_flow",))[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "results"
            run_benchmark(
                (case,),
                provider="gemini",
                track="evidence",
                model="fixture/model",
                out_dir=out,
                transport=_FakeTransport(
                    '{"findings":[],"cause":"unknown",'
                    '"action":"COLLECT_MORE_DATA","abstain":true,"why":"missing"}'
                ),
            )
            fabagent = json.loads(
                (out / "fabagent" / f"{case.id}.json").read_text()
            )
            self.assertEqual(
                fabagent["score"]["action"], "COLLECT_MORE_DATA"
            )
            self.assertTrue(fabagent["score"]["appropriate_abstention"])

    def test_runbooks_contain_the_prompt_and_no_ground_truth(self) -> None:
        case = select_cases(load_cases(), ("phm_nominal",))[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "runbooks"
            written = write_runbooks((case,), out_dir=out)
            self.assertGreaterEqual(len(written), 3)
            for provider in ("gemini", "openai"):
                text = (out / "evidence" / provider / f"{case.id}.md").read_text()
                self.assertIn("Paste this prompt verbatim", text)
                self.assertIn("--ingest", text)
                self.assertIn("do **not** upload", text)
                prompt_block = text.split("Paste this prompt verbatim", 1)[1]
                prompt_block = prompt_block.split("## 3.", 1)[0]
                self.assertNotIn("ground truth", prompt_block.casefold())
                self.assertNotIn("expected action", prompt_block.casefold())

    def test_raw_runbook_asks_for_the_upload(self) -> None:
        case = select_cases(load_cases(), ("phm_nominal",))[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "runbooks"
            write_runbooks((case,), out_dir=out, track="raw")
            text = (out / "raw" / "gemini" / f"{case.id}.md").read_text()
            self.assertIn("Upload this file", text)
            self.assertIn("--track raw", text)


if __name__ == "__main__":
    unittest.main()
