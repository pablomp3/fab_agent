from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.agents.model_transport import (
    FailureCategory,
    ModelIntegrationError,
    ModelTransport,
    OpenAICompatibleTransport,
)
from src.agents.proposal_request import (
    DEFAULT_MAX_TOKENS,
    MAX_MAX_TOKENS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
)
from src.core.column_profile import ColumnProfile, usable_candidates
from src.core.evidence import PayloadTooLarge
from src.model_config import ModelRoute, load_api_key, load_model_route

MAX_MAPPING_SIGNALS = 12
MAX_MAPPING_RELATIONSHIPS = 5
MAX_MAPPING_BYTES = 2048
# The mapping response carries up to twelve signals plus relationship
# rationales. The 256-token proposal default is too tight for that shape and
# produced finish_reason=length on live Nemotron calls.
DEFAULT_MAPPING_MAX_TOKENS = 768
MAPPING_SYSTEM_PROMPT = (
    "Semiconductor data-mapping assistant. You are given CSV column names, "
    "inferred types, and bounded summary statistics only; no telemetry values. "
    "Propose candidate numeric signals worth scanning and candidate physical "
    "relationships between them. Units are unknown unless the column name makes "
    "one obvious; otherwise use null. This is an unverified mapping suggestion, "
    "not a diagnosis, and it does not author a saved fault check. Return JSON "
    "per the schema; no extra fields."
)


class MappingSignalProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    column: str = Field(min_length=1)
    role_guess: str = Field(min_length=1)
    unit_guess: str | None = None


class MappingRelationshipProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    primary: str = Field(min_length=1)
    corroborating: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class MappingEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    signals: list[MappingSignalProposal] = Field(min_length=1)
    relationships: list[MappingRelationshipProposal] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ValidatedSignal:
    column: str
    role_guess: str
    unit_guess: str | None


@dataclass(frozen=True, slots=True)
class ValidatedRelationship:
    primary: str
    corroborating: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class ValidatedMapping:
    signals: tuple[ValidatedSignal, ...]
    relationships: tuple[ValidatedRelationship, ...]


class MappingValidationError(ValueError):
    """Raised when a proposed mapping is not usable against the real columns."""


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _candidate_items(candidates: tuple[ColumnProfile, ...]) -> list[dict[str, object]]:
    return [
        {
            "column": item.name,
            "type": item.declared_type,
            "rows": item.row_count,
            "null_fraction": round(item.null_fraction, 3),
            "min": _rounded(item.minimum),
            "median": _rounded(item.median),
            "max": _rounded(item.maximum),
            "mad": _rounded(item.mad),
        }
        for item in candidates
    ]


def mapping_candidate_bytes(candidates: tuple[ColumnProfile, ...]) -> int:
    """Size of the candidate-summary payload (the bounded part of the request)."""
    payload = json.dumps(
        {"candidates": _candidate_items(candidates)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(payload.encode("utf-8"))


def _within_budget(
    candidates: tuple[ColumnProfile, ...],
) -> tuple[ColumnProfile, ...]:
    """Deterministically trim candidate columns until the summary fits."""
    selected = list(usable_candidates(candidates))
    if not selected:
        raise ValueError("no usable numeric columns to map")
    while (
        len(selected) > 1
        and mapping_candidate_bytes(tuple(selected)) > MAX_MAPPING_BYTES
    ):
        selected.pop()
    if mapping_candidate_bytes(tuple(selected)) > MAX_MAPPING_BYTES:
        raise PayloadTooLarge(
            "mapping candidate summary exceeds its byte budget",
            actual_bytes=mapping_candidate_bytes(tuple(selected)),
            limit_bytes=MAX_MAPPING_BYTES,
        )
    return tuple(selected)


def build_mapping_request(
    model: str,
    candidates: tuple[ColumnProfile, ...],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> bytes:
    if isinstance(max_tokens, bool) or not 1 <= max_tokens <= MAX_MAX_TOKENS:
        raise ValueError(f"max_tokens must be between 1 and {MAX_MAX_TOKENS}")
    selected = _within_budget(candidates)
    names = [item.name for item in selected]
    items = _candidate_items(selected)
    schema = {
        "type": "object",
        "properties": {
            "signals": {
                "type": "array",
                "minItems": 1,
                "maxItems": min(MAX_MAPPING_SIGNALS, len(names)),
                "items": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string", "enum": names},
                        "role_guess": {"type": "string"},
                        "unit_guess": {"type": ["string", "null"]},
                    },
                    "required": ["column", "role_guess", "unit_guess"],
                    "additionalProperties": False,
                },
            },
            "relationships": {
                "type": "array",
                "maxItems": MAX_MAPPING_RELATIONSHIPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "primary": {"type": "string", "enum": names},
                        "corroborating": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "enum": names},
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["primary", "corroborating", "rationale"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["signals", "relationships"],
        "additionalProperties": False,
    }
    user_payload = json.dumps(
        {"candidates": items}, ensure_ascii=False, separators=(",", ":")
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": MAPPING_SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "fabagent_mapping",
                    "strict": True,
                    "schema": schema,
                },
            },
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0,
            "max_tokens": max_tokens,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise PayloadTooLarge(
            f"mapping request is {len(body)} bytes; limit is {MAX_REQUEST_BYTES}",
            actual_bytes=len(body),
            limit_bytes=MAX_REQUEST_BYTES,
        )
    return body


def validate_mapping(
    envelope: MappingEnvelope,
    candidates: tuple[ColumnProfile, ...],
) -> ValidatedMapping:
    """Python-owned validation: every proposed signal must be real and usable."""
    by_name = {item.name: item for item in candidates}
    if len(envelope.signals) > MAX_MAPPING_SIGNALS:
        raise MappingValidationError("proposed too many signals")
    signals: list[ValidatedSignal] = []
    seen: set[str] = set()
    for proposal in envelope.signals:
        profile = by_name.get(proposal.column)
        if profile is None:
            raise MappingValidationError(f"unknown column {proposal.column!r}")
        if not profile.numeric:
            raise MappingValidationError(f"column {proposal.column!r} is not numeric")
        if profile.constant:
            raise MappingValidationError(f"column {proposal.column!r} is constant")
        if proposal.column in seen:
            raise MappingValidationError(f"duplicate column {proposal.column!r}")
        seen.add(proposal.column)
        signals.append(
            ValidatedSignal(
                column=proposal.column,
                role_guess=proposal.role_guess,
                unit_guess=proposal.unit_guess,
            )
        )
    if not signals:
        raise MappingValidationError("no usable signals were proposed")
    if len(envelope.relationships) > MAX_MAPPING_RELATIONSHIPS:
        raise MappingValidationError("proposed too many relationships")
    relationships: list[ValidatedRelationship] = []
    for proposal in envelope.relationships:
        if proposal.primary not in seen:
            raise MappingValidationError(
                f"relationship primary {proposal.primary!r} is not a validated signal"
            )
        corroborating = tuple(proposal.corroborating)
        if len(set(corroborating)) != len(corroborating):
            raise MappingValidationError("relationship repeats a corroborating column")
        if proposal.primary in corroborating:
            raise MappingValidationError(
                "relationship primary also appears as corroborating"
            )
        for column in corroborating:
            if column not in seen:
                raise MappingValidationError(
                    f"relationship cites unvalidated column {column!r}"
                )
        relationships.append(
            ValidatedRelationship(
                primary=proposal.primary,
                corroborating=corroborating,
                rationale=proposal.rationale,
            )
        )
    return ValidatedMapping(tuple(signals), tuple(relationships))


class MappingEngine:
    """One bounded, strict-schema call that proposes an unverified mapping."""

    def __init__(
        self,
        route: ModelRoute,
        api_key: str,
        transport: ModelTransport | None = None,
    ) -> None:
        if not api_key:
            raise ModelIntegrationError(
                f"{route.role}.api_key_env is empty", FailureCategory.TRANSPORT
            )
        self._route = route
        self._api_key = api_key
        self._transport = (
            OpenAICompatibleTransport() if transport is None else transport
        )
        try:
            model_ids = self._transport.list_models(route, api_key)
        except ModelIntegrationError as exc:
            raise ModelIntegrationError(
                f"{route.role} preflight failed", exc.category
            ) from exc
        if route.model not in model_ids:
            raise ModelIntegrationError(
                f"{route.role}.model is not available from the configured provider",
                FailureCategory.TRANSPORT,
            )

    def propose_mapping(
        self,
        candidates: tuple[ColumnProfile, ...],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> MappingEnvelope:
        body = build_mapping_request(self._route.model, candidates, max_tokens)
        completion = self._transport.complete(self._route, self._api_key, body)
        if completion.finish_reason != "stop":
            raise ModelIntegrationError(
                f"{self._route.role} finish reason was not stop",
                FailureCategory.FINISH_REASON,
            )
        if len(completion.content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ModelIntegrationError(
                f"{self._route.role} response exceeded its size limit",
                FailureCategory.SIZE,
            )
        try:
            return MappingEnvelope.model_validate_json(completion.content, strict=True)
        except ValidationError as exc:
            raise ModelIntegrationError(
                f"{self._route.role} mapping response failed validation",
                FailureCategory.SCHEMA_VALIDATION,
            ) from exc
        except ValueError as exc:
            raise ModelIntegrationError(
                f"{self._route.role} mapping response was not valid JSON",
                FailureCategory.SCHEMA_VALIDATION,
            ) from exc


def create_mapping_engine(
    config_path: str | Path = "config/models.yaml",
    environment: dict[str, str] | None = None,
    transport: ModelTransport | None = None,
    role: str = "MAPPING",
) -> MappingEngine:
    """Load the configured model route, key, and provider preflight."""
    route = load_model_route(config_path, role, environment)
    api_key = load_api_key(route, environment)
    return MappingEngine(route, api_key, transport)
