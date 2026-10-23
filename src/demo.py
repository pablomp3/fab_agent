"""Key-free demo transport and factories.

The dashboard must be usable by a judge without a provider key. This module is
the only place that wires a deterministic local transport into the real engine,
mapping validator, and Python gate. It never runs on the live path and it never
invents an API key.

The transport cites the evidence records it receives and echoes the candidate
columns it receives. All validation and all verdicts still go through the same
production code used for a live call.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from src.agents.mapping_request import MappingEngine, create_mapping_engine
from src.agents.model_transport import CompletionResponse
from src.agents.rca_engine import create_rca_engine
from src.core.constraints import ConstraintRule
from src.core.sufficiency import PredicateConfig
from src.dossier import EngineFactory, HypothesisGenerator
from src.model_config import ModelRoute

MAPPING_SCHEMA_NAME = "fabagent_mapping"
MAX_ECHO_SIGNALS = 12

MODELS_CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


class EchoEvidenceTransport:
    """Offline transport that cites every evidence record in the request.

    It exercises the real RCAEngine validation and gate path without a network
    call, so offline end-to-end runs are deterministic and key-free. Citing the
    complete channel set mirrors a complete candidate proposal; the Python gate
    still decides the verdict.
    """

    def __init__(self) -> None:
        self.calls: int = 0

    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]:
        return (route.model,)

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        self.calls += 1
        request = json.loads(body)
        evidence = json.loads(request["messages"][1]["content"])["evidence"]
        citations = [item["evidence_id"] for item in evidence]
        schema = request["response_format"]["json_schema"]["schema"]
        classes = schema["properties"]["hypotheses"]["items"]["properties"][
            "hypothesis_class"
        ]["enum"]
        hypothesis_class = classes[0] if classes else "equipment_fault"
        hypotheses = (
            [
                {
                    "claim": "Offline echo of the supplied evidence",
                    "root_cause": "equipment_fault",
                    "failure_mode": "offline_fixture",
                    "mechanism": "cites every supplied channel",
                    "hypothesis_class": hypothesis_class,
                    "cited_evidence": citations,
                }
            ]
            if citations
            else []
        )
        return CompletionResponse(json.dumps({"hypotheses": hypotheses}), "stop")


class ExperimentalEchoTransport(EchoEvidenceTransport):
    """Offline transport that also answers the experimental mapping request.

    It echoes the supplied candidate columns (capped) as signals and links the
    first to the rest, exercising Python validation and the scan without a
    network call.
    """

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        request = json.loads(body)
        schema = request.get("response_format", {}).get("json_schema", {})
        if schema.get("name") != MAPPING_SCHEMA_NAME:
            return super().complete(route, api_key, body)
        self.calls += 1
        user = json.loads(request["messages"][1]["content"])
        names = [str(item["column"]) for item in user["candidates"]][
            :MAX_ECHO_SIGNALS
        ]
        signals = [
            {
                "column": name,
                "role_guess": "experimental_candidate",
                "unit_guess": None,
            }
            for name in names
        ]
        relationships = (
            [
                {
                    "primary": names[0],
                    "corroborating": names[1:],
                    "rationale": "offline echo of the candidate columns",
                }
            ]
            if len(names) >= 2
            else []
        )
        response = {"signals": signals, "relationships": relationships}
        return CompletionResponse(json.dumps(response), "stop")


def offline_engine_factory(transport: EchoEvidenceTransport) -> EngineFactory:
    def factory(
        predicates: PredicateConfig,
        rules: Mapping[str, ConstraintRule],
    ) -> HypothesisGenerator:
        return create_rca_engine(
            predicates,
            rules,
            config_path=MODELS_CONFIG,
            environment={"NEBIUS_API_KEY": "offline-fixture-key"},
            transport=transport,
        )

    return factory


def offline_mapping_factory(
    transport: EchoEvidenceTransport,
) -> Callable[[], MappingEngine]:
    def factory() -> MappingEngine:
        return create_mapping_engine(
            MODELS_CONFIG,
            environment={"NEBIUS_API_KEY": "offline-fixture-key"},
            transport=transport,
        )

    return factory
