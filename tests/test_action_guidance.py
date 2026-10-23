from __future__ import annotations

import unittest

from src.action_guidance import (
    action_explanation,
    action_label,
    default_action_for,
    describe_action,
)
from src.core.types import AnalysisOutcome, SuggestedAction


class ActionGuidanceTests(unittest.TestCase):
    def test_every_action_has_a_label_and_explanation(self) -> None:
        for action in SuggestedAction:
            label = action_label(action)
            explanation = action_explanation(action)
            self.assertTrue(label.strip(), action)
            self.assertGreater(len(explanation.strip()), 20, action)

    def test_every_outcome_has_a_default_action(self) -> None:
        for outcome in AnalysisOutcome:
            self.assertIsInstance(default_action_for(outcome), SuggestedAction)

    def test_describe_action_matches_accessors(self) -> None:
        for action in SuggestedAction:
            self.assertEqual(
                describe_action(action),
                (action_label(action), action_explanation(action)),
            )

    def test_unsafe_recipe_action_is_not_representable(self) -> None:
        self.assertNotIn("UPDATE_RECIPE", {item.value for item in SuggestedAction})


if __name__ == "__main__":
    unittest.main()
