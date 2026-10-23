from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import yaml


class ModelConfigurationError(ValueError):
    """Raised when a configured model role is incomplete or invalid."""


@dataclass(frozen=True, slots=True)
class ModelRoute:
    role: str
    model: str
    base_url: str
    api_key_env: str
    timeout_seconds: float


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ModelConfigurationError(f"{where} must be a mapping")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ModelConfigurationError(f"{where} keys must be strings")
    return cast(Mapping[str, object], value)


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelConfigurationError(f"{where} must be a non-empty string")
    return value.strip()


def load_model_route(
    path: str | Path,
    role: str,
    environment: Mapping[str, str] | None = None,
) -> ModelRoute:
    """Resolve one model role without putting model IDs or secrets in code."""
    selected_environment = os.environ if environment is None else environment
    raw_config: object = cast(
        object, yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    )
    config = _mapping(raw_config, "model configuration")
    if set(config) != {"version", "roles"}:
        raise ModelConfigurationError("model configuration has unknown or missing keys")
    version = config["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ModelConfigurationError("model configuration version must be 1")
    roles = _mapping(config["roles"], "roles")
    if role not in roles:
        raise ModelConfigurationError(f"model role {role} is not configured")
    role_config = _mapping(roles[role], f"roles.{role}")
    expected = {"model", "model_env", "api_key_env", "base_url", "timeout_seconds"}
    if set(role_config) != expected:
        raise ModelConfigurationError(f"roles.{role} has unknown or missing keys")
    configured_model = _text(role_config["model"], f"roles.{role}.model")
    model_env = _text(role_config["model_env"], f"roles.{role}.model_env")
    api_key_env = _text(role_config["api_key_env"], f"roles.{role}.api_key_env")
    model = selected_environment.get(model_env, "").strip() or configured_model
    base_url = _text(role_config["base_url"], f"roles.{role}.base_url").rstrip("/")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ModelConfigurationError(f"{role}.base_url must be an HTTPS URL")
    if parsed_url.query or parsed_url.fragment:
        raise ModelConfigurationError(
            f"{role}.base_url cannot contain query or fragment"
        )
    timeout = role_config["timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int | float)
        or timeout <= 0
    ):
        raise ModelConfigurationError(f"{role}.timeout_seconds must be positive")
    return ModelRoute(role, model, base_url, api_key_env, float(timeout))


def load_api_key(
    route: ModelRoute, environment: Mapping[str, str] | None = None
) -> str:
    selected_environment = os.environ if environment is None else environment
    api_key = selected_environment.get(route.api_key_env, "").strip()
    if not api_key:
        raise ModelConfigurationError(
            f"{route.role}.api_key_env requires environment variable "
            f"{route.api_key_env}"
        )
    return api_key
