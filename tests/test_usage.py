from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch

from src.agents.model_transport import OpenAICompatibleTransport
from src.model_config import ModelRoute
from src.usage import USAGE, UsageTracker


def _route(role: str = "SYNTHESIS", model: str = "fixture/model-v1") -> ModelRoute:
    return ModelRoute(
        role=role,
        model=model,
        base_url="https://models.example/v1",
        api_key_env="TOKEN",
        timeout_seconds=5.0,
    )


class UsageTrackerTests(unittest.TestCase):
    def test_counts_are_grouped_and_sorted(self) -> None:
        tracker = UsageTracker()
        tracker.record(provider="Tavily", model="tavily-search", role="RESEARCH")
        tracker.record(
            provider="Nebius Token Factory",
            model="fixture/model-v1",
            role="SYNTHESIS",
        )
        tracker.record(
            provider="Nebius Token Factory",
            model="fixture/model-v1",
            role="SYNTHESIS",
        )

        snapshot = tracker.snapshot()

        self.assertEqual(
            [(item.provider, item.model, item.role, item.calls) for item in snapshot],
            [
                ("Nebius Token Factory", "fixture/model-v1", "SYNTHESIS", 2),
                ("Tavily", "tavily-search", "RESEARCH", 1),
            ],
        )

    def test_reset_clears_the_counter(self) -> None:
        tracker = UsageTracker()
        tracker.record(provider="Tavily", model="tavily-search", role="RESEARCH")
        tracker.reset()
        self.assertEqual(tracker.snapshot(), ())

    def test_live_transport_records_the_exact_model_and_role(self) -> None:
        USAGE.reset()
        response = BytesIO(
            b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}'
        )
        with patch(
            "src.agents.model_transport.urlopen", return_value=response
        ):
            OpenAICompatibleTransport().complete(
                _route(role="MAPPING", model="nvidia/Nemotron-3-Ultra-550b-a55b"),
                "test-token",
                b"{}",
            )

        snapshot = USAGE.snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0].provider, "Nebius Token Factory")
        self.assertEqual(snapshot[0].model, "nvidia/Nemotron-3-Ultra-550b-a55b")
        self.assertEqual(snapshot[0].role, "MAPPING")
        self.assertEqual(snapshot[0].calls, 1)


if __name__ == "__main__":
    unittest.main()
