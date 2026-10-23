from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agents.model_transport import OpenAICompatibleTransport
from src.agents.rca_engine import RCAEngine, create_rca_engine
from src.core.sufficiency import PredicateConfig
from src.model_config import ModelConfigurationError, load_model_route


class ModelConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_text = """\
version: 1
roles:
  SYNTHESIS:
    model: fixture/default-model
    model_env: MODEL_ID
    api_key_env: TOKEN
    base_url: https://models.example/v1/
    timeout_seconds: 12
"""

    def write_config(self, directory: str) -> Path:
        config_path = Path(directory) / "models.yaml"
        config_path.write_text(self.config_text, encoding="utf-8")
        return config_path

    def test_environment_model_overrides_configured_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            route = load_model_route(
                self.write_config(directory),
                "SYNTHESIS",
                {"MODEL_ID": "fixture/model-v1"},
            )

        self.assertEqual(route.model, "fixture/model-v1")
        self.assertEqual(route.base_url, "https://models.example/v1")
        self.assertEqual(route.api_key_env, "TOKEN")

    def test_configured_model_is_used_without_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            route = load_model_route(self.write_config(directory), "SYNTHESIS", {})

        self.assertEqual(route.model, "fixture/default-model")

    def test_empty_configured_model_is_rejected(self) -> None:
        self.config_text = self.config_text.replace(
            "model: fixture/default-model", 'model: "  "'
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ModelConfigurationError, "roles.SYNTHESIS.model"
            ):
                load_model_route(self.write_config(directory), "SYNTHESIS", {})

    def test_factory_performs_role_preflight_before_returning_engine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self.write_config(directory)
            with patch.object(
                OpenAICompatibleTransport,
                "list_models",
                return_value=("fixture/model-v1",),
            ) as preflight:
                engine = create_rca_engine(
                    PredicateConfig(),
                    {},
                    config_path,
                    {"MODEL_ID": "fixture/model-v1", "TOKEN": "test-token"},
                )

        self.assertIsInstance(engine, RCAEngine)
        self.assertEqual(preflight.call_args.args[0].role, "SYNTHESIS")


if __name__ == "__main__":
    unittest.main()
