from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.model_config import ModelRoute

_MAX_CATALOG_BYTES = 1_000_000
_MAX_COMPLETION_BYTES = 8192


class FailureCategory(StrEnum):
    TRANSPORT = "transport"
    FINISH_REASON = "finish_reason"
    RESPONSE_SHAPE = "response_shape"
    SCHEMA_VALIDATION = "schema_validation"
    SIZE = "size"


@dataclass(frozen=True, slots=True)
class CompletionResponse:
    content: str
    finish_reason: str


class ModelIntegrationError(RuntimeError):
    """Raised for model routing, transport, or response failures."""

    def __init__(self, message: str, category: FailureCategory) -> None:
        super().__init__(message)
        self.category = category


class ModelTransport(Protocol):
    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]: ...

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse: ...


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        return None
    return cast(Mapping[str, object], value)


class OpenAICompatibleTransport:
    def _read_json(
        self, route: ModelRoute, api_key: str, path: str, max_bytes: int
    ) -> object:
        request = Request(
            f"{route.base_url}/{path}",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=route.timeout_seconds) as response:
                content = response.read(max_bytes + 1)
        except (OSError, URLError) as exc:
            raise ModelIntegrationError(
                f"{route.role} request to {path} failed", FailureCategory.TRANSPORT
            ) from exc
        if len(content) > max_bytes:
            raise ModelIntegrationError(
                f"{route.role} response exceeded its size limit", FailureCategory.SIZE
            )
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelIntegrationError(
                f"{route.role} returned invalid JSON", FailureCategory.RESPONSE_SHAPE
            ) from exc

    def list_models(self, route: ModelRoute, api_key: str) -> tuple[str, ...]:
        payload = self._read_json(route, api_key, "models", _MAX_CATALOG_BYTES)
        data = _mapping(payload)
        if data is None or not isinstance(data.get("data"), list):
            raise ModelIntegrationError(
                f"{route.role} model catalog has an invalid shape",
                FailureCategory.RESPONSE_SHAPE,
            )
        model_ids: list[str] = []
        for item_obj in cast(list[object], data["data"]):
            item = _mapping(item_obj)
            if item is not None and isinstance(item.get("id"), str):
                model_ids.append(cast(str, item["id"]))
        return tuple(model_ids)

    def complete(
        self, route: ModelRoute, api_key: str, body: bytes
    ) -> CompletionResponse:
        request = Request(
            f"{route.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=route.timeout_seconds) as response:
                content = response.read(_MAX_COMPLETION_BYTES + 1)
        except (OSError, URLError) as exc:
            raise ModelIntegrationError(
                f"{route.role} completion request failed",
                FailureCategory.TRANSPORT,
            ) from exc
        if len(content) > _MAX_COMPLETION_BYTES:
            raise ModelIntegrationError(
                f"{route.role} response exceeded its size limit", FailureCategory.SIZE
            )
        try:
            payload: object = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelIntegrationError(
                f"{route.role} returned invalid JSON", FailureCategory.RESPONSE_SHAPE
            ) from exc
        data = _mapping(payload)
        if data is None or not isinstance(data.get("choices"), list):
            raise ModelIntegrationError(
                f"{route.role} completion has an invalid shape",
                FailureCategory.RESPONSE_SHAPE,
            )
        choices = cast(list[object], data["choices"])
        choice = _mapping(choices[0]) if choices else None
        if choice is None:
            raise ModelIntegrationError(
                f"{route.role} completion has no message",
                FailureCategory.RESPONSE_SHAPE,
            )
        message = _mapping(choice.get("message"))
        if message is None or not isinstance(message.get("content"), str):
            raise ModelIntegrationError(
                f"{route.role} completion content is not text",
                FailureCategory.RESPONSE_SHAPE,
            )
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str):
            raise ModelIntegrationError(
                f"{route.role} completion has no finish reason",
                FailureCategory.RESPONSE_SHAPE,
            )
        return CompletionResponse(cast(str, message["content"]), finish_reason)
