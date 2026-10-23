from __future__ import annotations

from typing import overload

from src.core.types import SuggestedAction, Verdict


@overload
def apply_safety_gate(verdict: Verdict) -> SuggestedAction: ...


@overload
def apply_safety_gate(
    verdict: Verdict, supported_action: SuggestedAction
) -> SuggestedAction: ...


def apply_safety_gate(
    verdict: Verdict,
    supported_action: object = SuggestedAction.ESCALATE_TO_ENGINEER,
) -> SuggestedAction:
    if not isinstance(supported_action, SuggestedAction):
        raise TypeError("supported_action must be a typed SuggestedAction value")
    if verdict is Verdict.SUPPORTED:
        return supported_action
    return SuggestedAction.ESCALATE_TO_ENGINEER
