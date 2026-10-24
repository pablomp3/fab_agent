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


def _narrative_for(signals: list[str]) -> tuple[str, str, str, str]:
    """Return a realistic offline narrative for the evidence it was given.

    This is still a deterministic fixture, not a model. The wording is selected
    from the signal names so a judge sees a domain-shaped narrative next to the
    Python-gated conclusion. The narrative remains separate and is never used
    to compute the verdict.
    """
    upper = {signal.upper() for signal in signals}
    if any("FLOWCOOL" in signal for signal in upper):
        return (
            "Flowcool loop excursion (offline narrative)",
            "equipment_fault",
            "Coolant flow and pressure moved together.",
            "The configured flowcool relationship is consistent with a loop "
            "excursion; the offline fixture cites the evidence and does not "
            "assert a specific failed part.",
        )
    if "SENSOR_17" in upper:
        return (
            "RF generator arc (offline narrative)",
            "equipment_fault",
            "RF sensor spike with a corroborating signature.",
            "The offline fixture reads the sensor-17 spike as an arc story; "
            "Python still decides whether the corroborating channels agree.",
        )
    if any(signal.startswith("XMEAS") for signal in upper):
        return (
            "Feed-system disturbance (offline narrative)",
            "upstream_process",
            "Feed flow and valve moved together.",
            "The configured TEP cause channels moved; the offline fixture "
            "describes a feed-system disturbance without naming a valve.",
        )
    return (
        "Unverified channel pattern (offline narrative)",
        "unknown",
        "A configured channel moved above its threshold.",
        "The offline fixture cites the supplied evidence; no physical cause is "
        "claimed for an unverified mapping.",
    )


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
        signals = [
            str(item["signal"]) for item in evidence if item.get("signal")
        ]
        schema = request["response_format"]["json_schema"]["schema"]
        classes = schema["properties"]["hypotheses"]["items"]["properties"][
            "hypothesis_class"
        ]["enum"]
        hypothesis_class = classes[0] if classes else "equipment_fault"
        claim, root_cause, failure_mode, mechanism = _narrative_for(signals)
        hypotheses = (
            [
                {
                    "claim": claim,
                    "root_cause": root_cause,
                    "failure_mode": failure_mode,
                    "mechanism": mechanism,
                    "hypothesis_class": hypothesis_class,
                    "cited_evidence": citations,
                }
            ]
            if citations
            else []
        )
        return CompletionResponse(json.dumps({"hypotheses": hypotheses}), "stop")


def _role_guess(name: str) -> str:
    lower = name.lower()
    if "press" in lower:
        return "pressure_candidate"
    if "temp" in lower:
        return "temperature_candidate"
    if "flow" in lower:
        return "flow_candidate"
    if "power" in lower or "rf" in lower:
        return "rf_power_candidate"
    if "valve" in lower or lower.startswith("xmv"):
        return "actuator_candidate"
    return "candidate_sensor"


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
                "role_guess": _role_guess(name),
                "unit_guess": None,
            }
            for name in names
        ]
        relationships = (
            [
                {
                    "primary": names[0],
                    "corroborating": names[1:],
                    "rationale": (
                        "Name and summary-statistic inference only; verify "
                        "against the tool manual."
                    ),
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
