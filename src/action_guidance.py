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
    SuggestedAction.FIX_INPUT_FILE: "Fix the file",
    SuggestedAction.FIX_FILE_FORMAT: "Fix the file",
    SuggestedAction.PROVIDE_MORE_DATA: "Provide more data",
    SuggestedAction.CHECK_COLUMN_FORMAT: "Check the columns",
    SuggestedAction.AUTHOR_TOOL_CONFIG: "Describe the machine",
    SuggestedAction.FIX_COLUMNS_AND_RETRY: "Fix the columns and retry",
    SuggestedAction.REVIEW_DRAFT_MAPPING: "Review the guessed columns",
    SuggestedAction.REDUCE_CHANNELS: "Use fewer channels",
    SuggestedAction.RETRY_ANALYSIS: "Try again",
    SuggestedAction.REVIEW_CHANNEL_FINDINGS: "Review the channel findings",
    SuggestedAction.COLLECT_MORE_DATA: "Get the missing data",
    SuggestedAction.REVIEW_CONTRADICTION: "Check the sensor first",
    SuggestedAction.INSPECT_COMPONENT: "Inspect the part",
    SuggestedAction.CONTINUE_MONITORING: "Keep monitoring",
    SuggestedAction.ESCALATE_TO_ENGINEER: "Ask an engineer to review",
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
        "This export does not match a saved tool model. Describe the machine "
        "and save a model, so the next run is deterministic."
    ),
    SuggestedAction.FIX_COLUMNS_AND_RETRY: (
        "The suggested channel mapping could not be used (a column was unknown, "
        "non-numeric, constant, or duplicated). Nothing was scanned; fix the "
        "export and retry."
    ),
    SuggestedAction.REVIEW_DRAFT_MAPPING: (
        "The columns were guessed from names and statistics. This is unverified, "
        "so review the guessed columns before trusting any result."
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
        "The data is not enough to confirm or rule out a cause. Get the missing "
        "readings or a longer run, then try again."
    ),
    SuggestedAction.REVIEW_CONTRADICTION: (
        "One signal moved while the sensor that should agree stayed normal. "
        "Check the sensor first; do not change the recipe."
    ),
    SuggestedAction.INSPECT_COMPONENT: (
        "The evidence supports a fault. Inspect the named part; a human decides "
        "the action."
    ),
    SuggestedAction.CONTINUE_MONITORING: (
        "No fault pattern was found in the checked signals. Keep monitoring "
        "the channel and re-run if the tool behaviour changes."
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
