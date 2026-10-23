"""Streamlit-free presentation helpers for the technician dashboard.

Everything here is deterministic and importable without starting a Streamlit
server, so the wording and tables can be unit-tested. The app in ``app.py``
only wires widgets to these values; config promotion lives in
``config_promotion.py``. Nothing here changes a verdict, invents a unit, or
reads an API key. The raw action enum is never returned for display;
:func:`src.action_guidance.action_label` and the outcome labels below are used
instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.action_guidance import action_explanation, action_label
from src.agents.mapping_request import ValidatedMapping
from src.analyze import RunResult
from src.core.types import AnalysisOutcome, Evidence, Verdict
from src.schemas.models import RCAOutputModel

MISSING = "\u2014"  # an em dash; used where a value is genuinely absent.
OutcomeTone = Literal["success", "info", "warning", "error"]

_OUTCOME_LABELS: dict[AnalysisOutcome, str] = {
    AnalysisOutcome.INPUT_UNREADABLE: "Input file could not be read",
    AnalysisOutcome.INPUT_MALFORMED: "Input is not a readable CSV",
    AnalysisOutcome.NO_DATA_ROWS: "No readings in the file",
    AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA: "No matching tool schema",
    AnalysisOutcome.NO_USABLE_NUMERIC_COLUMNS: "No usable numeric columns",
    AnalysisOutcome.EVIDENCE_TOO_LARGE: "Evidence budget exceeded",
    AnalysisOutcome.MODEL_REJECTED: "Model output could not be used",
    AnalysisOutcome.NO_PROPOSALS: "Model returned no usable proposal",
    AnalysisOutcome.ANALYSIS_CONTRADICTED: "Analysis found a contradiction",
    AnalysisOutcome.ANALYSIS_SUPPORTED: "Analysis supported a cause",
    AnalysisOutcome.ANALYSIS_INCONCLUSIVE: "Analysis was inconclusive",
    AnalysisOutcome.EXPERIMENTAL_MAPPING_REJECTED: "Mapping could not be validated",
    AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING: (
        "Unverified mapping (experimental)"
    ),
}

_OUTCOME_TONES: dict[AnalysisOutcome, OutcomeTone] = {
    AnalysisOutcome.INPUT_UNREADABLE: "error",
    AnalysisOutcome.INPUT_MALFORMED: "error",
    AnalysisOutcome.NO_DATA_ROWS: "warning",
    AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA: "warning",
    AnalysisOutcome.NO_USABLE_NUMERIC_COLUMNS: "warning",
    AnalysisOutcome.EVIDENCE_TOO_LARGE: "warning",
    AnalysisOutcome.MODEL_REJECTED: "error",
    AnalysisOutcome.NO_PROPOSALS: "warning",
    AnalysisOutcome.ANALYSIS_CONTRADICTED: "warning",
    AnalysisOutcome.ANALYSIS_SUPPORTED: "success",
    AnalysisOutcome.ANALYSIS_INCONCLUSIVE: "info",
    AnalysisOutcome.EXPERIMENTAL_MAPPING_REJECTED: "warning",
    AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING: "warning",
}


def outcome_label(outcome: AnalysisOutcome) -> str:
    """Human-readable route name; never the raw enum token."""
    return _OUTCOME_LABELS.get(outcome, outcome.value.replace("_", " ").title())


def outcome_tone(outcome: AnalysisOutcome) -> OutcomeTone:
    """A coarse tone the app maps to a Streamlit callout."""
    return _OUTCOME_TONES.get(outcome, "info")


_VERDICT_TONES: dict[Verdict, OutcomeTone] = {
    Verdict.SUPPORTED: "success",
    Verdict.VETOED: "error",
    Verdict.INSUFFICIENT: "warning",
}


def verdict_tone(verdict: Verdict) -> OutcomeTone:
    """A coarse tone for a Python-gated hypothesis verdict."""
    return _VERDICT_TONES.get(verdict, "info")


@dataclass(frozen=True, slots=True)
class RunSummary:
    outcome_label: str
    action_label: str
    explanation: str
    mode_label: str
    detail: str | None
    analysis_performed: bool
    model_called: bool
    evidence_count: int
    hypothesis_count: int
    triage: str


def _triage_text(result: RunResult) -> str:
    selection = result.selection
    if selection is None:
        return "No configured tool schema matched; used the experimental fallback."
    coverage = f"{selection.signal_coverage:.0%}"
    return (
        f"{selection.config_name} / {selection.scenario_name} "
        f"({len(selection.matched_signals)} channels matched, {coverage} coverage)"
    )


def summarize(result: RunResult) -> RunSummary:
    """Build the header values shown for every run."""
    mode_label = (
        "Experimental fallback (unverified)"
        if result.fallback_used
        else "Deterministic safe path"
    )
    return RunSummary(
        outcome_label=outcome_label(result.outcome),
        action_label=action_label(result.suggested_next_action),
        explanation=result.explanation or action_explanation(
            result.suggested_next_action
        ),
        mode_label=mode_label,
        detail=result.detail,
        analysis_performed=result.analysis_performed,
        model_called=result.model_called,
        evidence_count=len(result.evidence),
        hypothesis_count=len(result.output.hypotheses),
        triage=_triage_text(result),
    )


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    evidence_id: str
    kind: str
    signal: str
    statistic: str
    value: str
    unit: str
    window: str
    summary: str


def _value_text(value: float | None) -> str:
    return MISSING if value is None else f"{value:.4g}"


def _window_text(window: tuple[int, int] | None) -> str:
    return MISSING if window is None else f"{window[0]}\u2013{window[1]}"


def evidence_rows(evidence: tuple[Evidence, ...]) -> list[EvidenceRow]:
    """One row per evidence record. Absent units/values stay explicit."""
    return [
        EvidenceRow(
            evidence_id=item.evidence_id,
            kind=item.kind.value,
            signal=item.signal or MISSING,
            statistic=item.statistic or MISSING,
            value=_value_text(item.value),
            unit=item.unit or MISSING,
            window=_window_text(item.window),
            summary=item.summary,
        )
        for item in evidence
    ]


@dataclass(frozen=True, slots=True)
class HypothesisRow:
    claim: str
    status: str
    root_cause: str
    failure_mode: str
    mechanism: str
    cited_evidence: str
    veto_reason: str


def hypothesis_rows(output: RCAOutputModel) -> list[HypothesisRow]:
    """One row per Python-gated hypothesis, including its verdict."""
    return [
        HypothesisRow(
            claim=item.claim,
            status=item.status.value,
            root_cause=item.root_cause.value,
            failure_mode=item.failure_mode,
            mechanism=item.mechanism,
            cited_evidence=", ".join(item.cited_evidence) or MISSING,
            veto_reason=item.veto_reason or MISSING,
        )
        for item in output.hypotheses
    ]


@dataclass(frozen=True, slots=True)
class ModelNarrativeRow:
    claim: str
    root_cause: str
    failure_mode: str
    mechanism: str
    hypothesis_class: str
    cited_evidence: str
    unresolved_citations: str


def model_narrative_rows(output: RCAOutputModel) -> list[ModelNarrativeRow]:
    """The model's explanation, kept separate from the gated conclusion."""
    rows: list[ModelNarrativeRow] = []
    for hypothesis in output.hypotheses:
        narrative = hypothesis.model_narrative
        if narrative is None:
            continue
        rows.append(
            ModelNarrativeRow(
                claim=narrative.claim,
                root_cause=narrative.root_cause.value,
                failure_mode=narrative.failure_mode,
                mechanism=narrative.mechanism,
                hypothesis_class=narrative.hypothesis_class,
                cited_evidence=", ".join(narrative.cited_evidence) or MISSING,
                unresolved_citations=(
                    ", ".join(narrative.unresolved_citations) or MISSING
                ),
            )
        )
    return rows


@dataclass(frozen=True, slots=True)
class MappingSignalRow:
    column: str
    role_guess: str
    unit_guess: str


@dataclass(frozen=True, slots=True)
class MappingRelationshipRow:
    primary: str
    corroborating: str
    rationale: str


def mapping_signal_rows(mapping: ValidatedMapping) -> list[MappingSignalRow]:
    """The model's guessed roles/units, surfaced only as an unverified draft."""
    return [
        MappingSignalRow(
            column=item.column,
            role_guess=item.role_guess,
            unit_guess=item.unit_guess or MISSING,
        )
        for item in mapping.signals
    ]


def mapping_relationship_rows(
    mapping: ValidatedMapping,
) -> list[MappingRelationshipRow]:
    return [
        MappingRelationshipRow(
            primary=item.primary,
            corroborating=", ".join(item.corroborating) or MISSING,
            rationale=item.rationale,
        )
        for item in mapping.relationships
    ]


def _cell_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def markdown_table(rows: list[dict[str, object]]) -> str:
    """Render presentation rows as a GitHub-flavored Markdown table.

    Used instead of ``st.dataframe``/``st.table`` because Streamlit's own
    annotations resolve to ``Unknown`` under basedpyright strict; this keeps the
    UI fully type-checked. Cell text is escaped so a pipe or newline in a
    summary cannot break the table.
    """
    if not rows:
        return ""
    headers = [str(key) for key in rows[0]]
    pretty = [header.replace("_", " ").strip().capitalize() for header in headers]
    lines = [
        "| " + " | ".join(pretty) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [_cell_text(row.get(header)) for header in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
