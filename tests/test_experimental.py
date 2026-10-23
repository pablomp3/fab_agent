from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmarks.evaluator.echo_transport import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.agents.mapping_request import (
    MAX_MAPPING_SIGNALS,
    MappingEnvelope,
    MappingRelationshipProposal,
    MappingSignalProposal,
    MappingValidationError,
    build_mapping_request,
    validate_mapping,
)
from src.agents.model_transport import CompletionResponse
from src.agents.proposal_request import MAX_REQUEST_BYTES
from src.config_loader import load_relations
from src.core.column_profile import (
    ColumnProfile,
    profile_columns,
    usable_candidates,
)
from src.core.evidence import PayloadTooLarge
from src.core.types import AnalysisOutcome, EvidenceKind, SuggestedAction
from src.experimental import analyze_experimental
from src.model_config import ModelRoute

_EXPERIMENTAL_EXPORT = (
    "a,b,c\n"
    "10.0,10.0,10.0\n"
    "11.0,11.0,11.0\n"
    "10.0,10.0,10.0\n"
    "11.0,11.0,11.0\n"
    "10.0,10.0,10.0\n"
    "1000.0,11.0,11.0\n"
)


def _profile(
    name: str,
    *,
    numeric_count: int = 10,
    minimum: float | None = 0.0,
    maximum: float | None = 1.0,
) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        declared_type="DOUBLE",
        row_count=10,
        numeric_count=numeric_count,
        minimum=minimum,
        median=0.5,
        maximum=maximum,
        mad=0.2,
    )


def _signal(column: str) -> dict[str, object]:
    return {"column": column, "role_guess": "x", "unit_guess": None}


class _BadMappingTransport(ExperimentalEchoTransport):
    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        request = json.loads(body)
        schema = request.get("response_format", {}).get("json_schema", {})
        if schema.get("name") == "fabagent_mapping":
            self.calls += 1
            response = {
                "signals": [
                    {
                        "column": "ghost",
                        "role_guess": "invented",
                        "unit_guess": None,
                    }
                ],
                "relationships": [],
            }
            return CompletionResponse(json.dumps(response), "stop")
        return super().complete(route, api_key, body)


def _write(directory: Path, text: str, name: str = "export.csv") -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


class MappingValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = (
            _profile("a"),
            _profile("b"),
            _profile("c"),
        )

    def _envelope(self, columns: list[str]) -> MappingEnvelope:
        return MappingEnvelope.model_validate(
            {"signals": [_signal(column) for column in columns], "relationships": []}
        )

    def test_valid_mapping_is_accepted(self) -> None:
        envelope = MappingEnvelope(
            signals=[
                MappingSignalProposal(
                    column="a", role_guess="primary", unit_guess=None
                ),
                MappingSignalProposal(
                    column="b", role_guess="support", unit_guess="Pa"
                ),
            ],
            relationships=[
                MappingRelationshipProposal(
                    primary="a", corroborating=["b"], rationale="co-move"
                )
            ],
        )
        mapping = validate_mapping(envelope, self.candidates)
        self.assertEqual([item.column for item in mapping.signals], ["a", "b"])
        self.assertEqual(mapping.relationships[0].corroborating, ("b",))

    def test_unknown_column_is_rejected(self) -> None:
        with self.assertRaises(MappingValidationError):
            validate_mapping(self._envelope(["ghost"]), self.candidates)

    def test_non_numeric_column_is_rejected(self) -> None:
        profiles = (_profile("a", numeric_count=0, minimum=None, maximum=None),)
        with self.assertRaises(MappingValidationError):
            validate_mapping(self._envelope(["a"]), profiles)

    def test_constant_column_is_rejected(self) -> None:
        profiles = (_profile("a", minimum=5.0, maximum=5.0),)
        with self.assertRaises(MappingValidationError):
            validate_mapping(self._envelope(["a"]), profiles)

    def test_duplicate_column_is_rejected(self) -> None:
        with self.assertRaises(MappingValidationError):
            validate_mapping(self._envelope(["a", "a"]), self.candidates)

    def test_relationship_must_reference_validated_signals(self) -> None:
        envelope = MappingEnvelope(
            signals=[
                MappingSignalProposal(column="a", role_guess="x", unit_guess=None)
            ],
            relationships=[
                MappingRelationshipProposal(
                    primary="a", corroborating=["b"], rationale="nope"
                )
            ],
        )
        with self.assertRaises(MappingValidationError):
            validate_mapping(envelope, self.candidates)

    def test_primary_cannot_also_be_corroborating(self) -> None:
        envelope = MappingEnvelope(
            signals=[
                MappingSignalProposal(column="a", role_guess="x", unit_guess=None)
            ],
            relationships=[
                MappingRelationshipProposal(
                    primary="a", corroborating=["a"], rationale="self"
                )
            ],
        )
        with self.assertRaises(MappingValidationError):
            validate_mapping(envelope, self.candidates)


class MappingBudgetTests(unittest.TestCase):
    def test_many_candidates_are_trimmed_within_budget(self) -> None:
        profiles = tuple(
            _profile(f"channel_with_a_long_name_{index:04d}") for index in range(200)
        )
        body = build_mapping_request("fixture/model-v1", profiles)
        self.assertLessEqual(len(body), MAX_REQUEST_BYTES)
        request = json.loads(body)
        names = request["response_format"]["json_schema"]["schema"]["properties"][
            "signals"
        ]["items"]["properties"]["column"]["enum"]
        self.assertGreater(len(names), 0)
        self.assertLessEqual(len(names), len(usable_candidates(profiles)))
        max_items = request["response_format"]["json_schema"]["schema"]["properties"][
            "signals"
        ]["maxItems"]
        self.assertLessEqual(max_items, MAX_MAPPING_SIGNALS)
        self.assertEqual(request["response_format"]["type"], "json_schema")

    def test_single_oversized_candidate_raises(self) -> None:
        profile = _profile("x" * 5000)
        with self.assertRaises(PayloadTooLarge):
            build_mapping_request("fixture/model-v1", (profile,))


class ExperimentalFlowTests(unittest.TestCase):
    def test_offline_end_to_end_marks_unverified_mapping(self) -> None:
        transport = ExperimentalEchoTransport()
        with TemporaryDirectory() as temp_dir:
            csv_path = _write(Path(temp_dir), _EXPERIMENTAL_EXPORT)
            result = analyze_experimental(
                csv_path,
                "unknown new tool export",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
            )

        self.assertIs(result.outcome, AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING)
        self.assertIsNone(result.detail)
        self.assertTrue(result.analysis_performed)
        self.assertTrue(result.model_called)
        self.assertIsNotNone(result.mapping)
        self.assertEqual(transport.calls, 2)
        self.assertEqual(
            result.output.suggested_next_action, SuggestedAction.REVIEW_DRAFT_MAPPING
        )
        self.assertTrue(result.evidence)
        self.assertTrue(
            all(
                item.computed_by == "experimental_mapping@v1"
                and "unverified_mapping" in item.provenance
                for item in result.evidence
            )
        )
        self.assertTrue(
            any(item.kind is EvidenceKind.SENSOR_ANOMALY for item in result.evidence)
        )
        self.assertTrue(
            any(
                item.status.value == "SUPPORTED"
                for item in result.output.hypotheses
            )
        )
        # The model never sets the outcome or an unsafe action.
        self.assertNotIn("HOLD_LOT", result.output.model_dump_json())

    def test_draft_yaml_round_trips_through_the_loader(self) -> None:
        transport = ExperimentalEchoTransport()
        with TemporaryDirectory() as temp_dir:
            csv_path = _write(Path(temp_dir), _EXPERIMENTAL_EXPORT)
            result = analyze_experimental(
                csv_path,
                "unknown export",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
            )
            assert result.draft_yaml is not None
            draft_path = Path(temp_dir) / "draft.yaml"
            draft_path.write_text(result.draft_yaml, encoding="utf-8")
            relations = load_relations(draft_path)

        self.assertIn("experimental_scope", relations.scenarios)
        scenario = relations.scenarios["experimental_scope"]
        self.assertIn("experimental_unverified", scenario.rules)
        self.assertTrue(all(item.unit is None for item in scenario.signals))

    def test_rejected_mapping_fails_closed_without_scan(self) -> None:
        transport = _BadMappingTransport()
        with TemporaryDirectory() as temp_dir:
            csv_path = _write(Path(temp_dir), _EXPERIMENTAL_EXPORT)
            result = analyze_experimental(
                csv_path,
                "unknown export",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
            )

        self.assertIs(result.outcome, AnalysisOutcome.EXPERIMENTAL_MAPPING_REJECTED)
        self.assertIsNotNone(result.detail)
        assert result.detail is not None
        self.assertIn("mapping_rejected", result.detail)
        self.assertIsNone(result.mapping)
        self.assertEqual(result.evidence, ())
        self.assertTrue(result.analysis_performed)
        self.assertTrue(result.model_called)
        self.assertEqual(
            result.output.suggested_next_action, SuggestedAction.FIX_COLUMNS_AND_RETRY
        )

    def test_no_usable_numeric_columns_returns_no_matching_profile(self) -> None:
        transport = ExperimentalEchoTransport()
        with TemporaryDirectory() as temp_dir:
            csv_path = _write(Path(temp_dir), "label\nonly\ntext\n")
            result = analyze_experimental(
                csv_path,
                "text only",
                engine_factory=offline_engine_factory(transport),
                mapping_factory=offline_mapping_factory(transport),
            )

        self.assertIs(result.outcome, AnalysisOutcome.NO_USABLE_NUMERIC_COLUMNS)
        self.assertFalse(result.model_called)
        self.assertEqual(transport.calls, 0)

    def test_missing_input_is_unreadable(self) -> None:
        transport = ExperimentalEchoTransport()
        result = analyze_experimental(
            "/tmp/opencode/experimental-missing.csv",
            "no file",
            engine_factory=offline_engine_factory(transport),
            mapping_factory=offline_mapping_factory(transport),
        )
        self.assertIs(result.outcome, AnalysisOutcome.INPUT_UNREADABLE)
        self.assertFalse(result.model_called)


class ColumnProfileTests(unittest.TestCase):
    def test_numeric_detection_and_constant_flag(self) -> None:
        with TemporaryDirectory() as temp_dir:
            csv_path = _write(
                Path(temp_dir),
                "value,flag,name\n1,5,x\n2,5,y\n3,5,z\n",
            )
            profiles = profile_columns(csv_path)

        by_name = {item.name: item for item in profiles}
        self.assertTrue(by_name["value"].numeric)
        self.assertFalse(by_name["value"].constant)
        self.assertTrue(by_name["flag"].constant)
        self.assertFalse(by_name["name"].numeric)
        self.assertEqual(
            [item.name for item in usable_candidates(profiles)], ["value"]
        )


if __name__ == "__main__":
    unittest.main()
