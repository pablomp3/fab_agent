"""Compatibility shim for the key-free demo transport.

The implementation lives in :mod:`src.demo` so the product dashboard can use it
without importing the benchmark harness. Existing benchmark imports keep
working through this module.
"""

from __future__ import annotations

from src.demo import (
    MAPPING_SCHEMA_NAME,
    MAX_ECHO_SIGNALS,
    MODELS_CONFIG,
    EchoEvidenceTransport,
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)

__all__ = [
    "MAPPING_SCHEMA_NAME",
    "MAX_ECHO_SIGNALS",
    "MODELS_CONFIG",
    "EchoEvidenceTransport",
    "ExperimentalEchoTransport",
    "offline_engine_factory",
    "offline_mapping_factory",
]
