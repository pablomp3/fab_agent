from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch

from src.agents.model_transport import (
    CompletionResponse,
    FailureCategory,
    ModelIntegrationError,
    OpenAICompatibleTransport,
)
from src.model_config import ModelRoute


def route() -> ModelRoute:
    return ModelRoute(
        role="SYNTHESIS",
        model="fixture/model-v1",
        base_url="https://models.example/v1",
        api_key_env="TOKEN",
        timeout_seconds=5.0,
    )


class ModelTransportTests(unittest.TestCase):
    def test_catalog_preflight_uses_models_endpoint_and_bearer_key(self) -> None:
        transport = OpenAICompatibleTransport()
        response = BytesIO(b'{"data":[{"id":"fixture/model-v1"}]}')

        with patch("src.agents.model_transport.urlopen", return_value=response) as call:
            model_ids = transport.list_models(route(), "test-token")

        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://models.example/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(model_ids, ("fixture/model-v1",))

    def test_completion_posts_json_to_chat_completions(self) -> None:
        transport = OpenAICompatibleTransport()
        response = BytesIO(
            b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}'
        )
        request_body = b'{"model":"fixture/model-v1"}'

        with patch("src.agents.model_transport.urlopen", return_value=response) as call:
            content = transport.complete(route(), "test-token", request_body)

        request = call.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://models.example/v1/chat/completions",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, request_body)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(content, CompletionResponse("{}", "stop"))

    def test_completion_invalid_shape_has_sanitized_category(self) -> None:
        transport = OpenAICompatibleTransport()
        response = BytesIO(b'{"choices":[]}')

        with patch("src.agents.model_transport.urlopen", return_value=response):
            with self.assertRaises(ModelIntegrationError) as raised:
                transport.complete(route(), "test-token", b"{}")

        self.assertIs(raised.exception.category, FailureCategory.RESPONSE_SHAPE)

    def test_transport_error_does_not_expose_provider_error_text(self) -> None:
        from urllib.error import URLError

        transport = OpenAICompatibleTransport()
        with patch(
            "src.agents.model_transport.urlopen",
            side_effect=URLError("SYNTHETIC_PROVIDER_TEXT"),
        ):
            with self.assertRaises(ModelIntegrationError) as raised:
                transport.complete(route(), "test-token", b"{}")

        self.assertIs(raised.exception.category, FailureCategory.TRANSPORT)
        self.assertNotIn("SYNTHETIC_PROVIDER_TEXT", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
