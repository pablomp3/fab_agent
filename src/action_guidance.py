from __future__ import annotations

from src.core.types import AnalysisOutcome, SuggestedAction

# One deterministic default action per route. The engine overrides the
# ANALYSIS_SUPPORTED action with the scenario's declared ``supported_action``.
_DEFAULT_ACTION: dict[AnalysisOutcome, SuggestedAction] = {
    AnalysisOutcome.INPUT_UNREADABLE: SuggestedAction.FIX_INPUT_FILE,
    AnalysisOutcome.INPUT_MALFORMED: SuggestedAction.FIX_FILE_FORMAT,
    AnalysisOutcome.NO_DATA_ROWS: SuggestedAction.PROVIDE_MORE_DATA,
    AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA: SuggestedAction.AUTHOR_TOOL_CONFIG,
    AnalysisOutcome.NO_USABLE_NUMERIC_COLUMNS: SuggestedAction.CHECK_COLUMN_FORMAT,
    AnalysisOutcome.EVIDENCE_TOO_LARGE: SuggestedAction.REDUCE_CHANNELS,
    AnalysisOutcome.MODEL_REJECTED: SuggestedAction.RETRY_ANALYSIS,
    AnalysisOutcome.NO_PROPOSALS: SuggestedAction.REVIEW_CHANNEL_FINDINGS,
    AnalysisOutcome.ANALYSIS_CONTRADICTED: SuggestedAction.REVIEW_CONTRADICTION,
    AnalysisOutcome.ANALYSIS_SUPPORTED: SuggestedAction.ESCALATE_TO_ENGINEER,
    AnalysisOutcome.ANALYSIS_INCONCLUSIVE: SuggestedAction.COLLECT_MORE_DATA,
    AnalysisOutcome.EXPERIMENTAL_MAPPING_REJECTED: (
        SuggestedAction.FIX_COLUMNS_AND_RETRY
    ),
    AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING: (
        SuggestedAction.REVIEW_DRAFT_MAPPING
    ),
}

# A short, user-facing label. Displayed next to the outcome; never the raw enum.
_LABEL: dict[SuggestedAction, str] = {
    SuggestedAction.FIX_INPUT_FILE: "Fix the file path",
    SuggestedAction.FIX_FILE_FORMAT: "Re-export the file",
    SuggestedAction.PROVIDE_MORE_DATA: "Provide data rows",
    SuggestedAction.CHECK_COLUMN_FORMAT: "Check the columns",
    SuggestedAction.AUTHOR_TOOL_CONFIG: "Add a tool schema",
    SuggestedAction.FIX_COLUMNS_AND_RETRY: "Fix the columns and retry",
    SuggestedAction.REVIEW_DRAFT_MAPPING: "Review the draft mapping",
    SuggestedAction.REDUCE_CHANNELS: "Use fewer channels",
    SuggestedAction.RETRY_ANALYSIS: "Retry the analysis",
    SuggestedAction.REVIEW_CHANNEL_FINDINGS: "Review the channel findings",
    SuggestedAction.COLLECT_MORE_DATA: "Collect more data",
    SuggestedAction.REVIEW_CONTRADICTION: "Check the contradiction",
    SuggestedAction.INSPECT_COMPONENT: "Inspect the component",
    SuggestedAction.CONTINUE_MONITORING: "Continue monitoring",
    SuggestedAction.ESCALATE_TO_ENGINEER: "Escalate to an engineer",
}

# One short sentence of context so the user understands why. Deterministic
# Python text; nothing here changes a verdict or is parsed as an instruction.
_EXPLANATION: dict[SuggestedAction, str] = {
    SuggestedAction.FIX_INPUT_FILE: (
        "I could not open the file you gave me. Check the path and permissions, "
        "then upload it again."
    ),
    SuggestedAction.FIX_FILE_FORMAT: (
        "The file is not readable as a CSV (an encoding or delimiter problem). "
        "Re-export it as a UTF-8 CSV."
    ),
    SuggestedAction.PROVIDE_MORE_DATA: (
        "The file has a header but no readings, so there is nothing to check."
    ),
    SuggestedAction.CHECK_COLUMN_FORMAT: (
        "No numeric column varies, so no signal can be scored. Check that the "
        "sensor columns are numeric and not frozen."
    ),
    SuggestedAction.AUTHOR_TOOL_CONFIG: (
        "This export does not match any configured tool. Add a tool config, or "
        "try experimental mode for a first look."
    ),
    SuggestedAction.FIX_COLUMNS_AND_RETRY: (
        "The suggested channel mapping could not be used (a column was unknown, "
        "non-numeric, constant, or duplicated). Nothing was scanned; fix the "
        "export and retry."
    ),
    SuggestedAction.REVIEW_DRAFT_MAPPING: (
        "I inferred these channels from names and statistics. This is unverified, "
        "so review the draft config before trusting any result."
    ),
    SuggestedAction.REDUCE_CHANNELS: (
        "More channels were selected than fit in one safe pass. Use fewer "
        "channels, or split the file."
    ),
    SuggestedAction.RETRY_ANALYSIS: (
        "The model call failed or returned nothing usable. This can be transient; "
        "retry, and if it persists review the channel findings."
    ),
    SuggestedAction.REVIEW_CHANNEL_FINDINGS: (
        "The model did not produce a usable proposal. The channel findings are "
        "still valid, so review them directly."
    ),
    SuggestedAction.COLLECT_MORE_DATA: (
        "Nothing was proven. Review what moved and what was missing, then decide "
        "whether to collect more data."
    ),
    SuggestedAction.REVIEW_CONTRADICTION: (
        "Two signals disagree, so the proposed cause is rejected. Check whether a "
        "sensor is faulty or the channels are mislabeled."
    ),
    SuggestedAction.INSPECT_COMPONENT: (
        "The evidence supports a fault. Inspect the named component; a human "
        "decides the action."
    ),
    SuggestedAction.CONTINUE_MONITORING: (
        "The evidence supports a fault but it is not urgent; keep monitoring the "
        "channel."
    ),
    SuggestedAction.ESCALATE_TO_ENGINEER: (
        "A human should review this run before any action is taken."
    ),
}


def default_action_for(outcome: AnalysisOutcome) -> SuggestedAction:
    """Return the deterministic action for a route taken by a run."""
    try:
        return _DEFAULT_ACTION[outcome]
    except KeyError as exc:  # pragma: no cover - guards a future enum addition
        raise ValueError(f"no default action for outcome: {outcome}") from exc


def action_label(action: SuggestedAction) -> str:
    """Return the short, user-facing label for an action."""
    return _LABEL[action]


def action_explanation(action: SuggestedAction) -> str:
    """Return the short, user-facing explanation for an action."""
    return _EXPLANATION[action]


def describe_action(action: SuggestedAction) -> tuple[str, str]:
    """Return ``(label, explanation)`` for an action."""
    return _LABEL[action], _EXPLANATION[action]
