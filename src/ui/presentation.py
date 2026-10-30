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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from src.action_guidance import action_explanation, action_label
from src.agents.mapping_request import ValidatedMapping
from src.agents.proposal_request import MAX_EVIDENCE_BYTES, evidence_summary_bytes
from src.analyze import RunResult
from src.core.types import AnalysisOutcome, Evidence, EvidenceKind, Verdict
from src.schemas.models import DifferentialEntryModel, RCAOutputModel

MISSING = "\u2014"  # an em dash; used where a value is genuinely absent.
OutcomeTone = Literal["success", "info", "warning", "error"]
ResultWord = Literal[
    "Fault Confirmed",
    "Regular Behavior",
    "Sensors Disagree",
    "Data Incomplete",
    "Needs Review",
    "Unknown Machine",
]

# The only six words a user may see as a result. The mapping from the internal
# Python route to these words lives here, once, so every page agrees.
RESULT_WORDS: tuple[ResultWord, ...] = (
    "Fault Confirmed",
    "Regular Behavior",
    "Sensors Disagree",
    "Data Incomplete",
    "Needs Review",
    "Unknown Machine",
)

_RESULT_BADGES: dict[ResultWord, str] = {
    "Fault Confirmed": "[\U0001f534 FAULT CONFIRMED]",
    "Regular Behavior": "[\U0001f7e2 REGULAR BEHAVIOR]",
    "Sensors Disagree": "[\U0001f7e1 SENSORS DISAGREE]",
    "Data Incomplete": "[\u26a0 DATA INCOMPLETE]",
    "Needs Review": "[\U0001f7e0 NEEDS REVIEW]",
    "Unknown Machine": "[\u26aa UNKNOWN MACHINE]",
}

_RESULT_TONES: dict[ResultWord, OutcomeTone] = {
    "Fault Confirmed": "success",
    "Regular Behavior": "info",
    "Sensors Disagree": "error",
    "Data Incomplete": "warning",
    "Needs Review": "warning",
    "Unknown Machine": "warning",
}

PLAIN_VERDICT: dict[Verdict, str] = {
    Verdict.SUPPORTED: "Fault Confirmed",
    Verdict.INSUFFICIENT: "Not enough evidence",
    Verdict.VETOED: "Sensors Disagree",
}


def verdict_label(verdict: Verdict) -> str:
    """Return plain-English label for a safety verdict."""
    return PLAIN_VERDICT.get(verdict, verdict.value)


PLAIN_OUTCOME: dict[AnalysisOutcome, str] = {
    AnalysisOutcome.INPUT_UNREADABLE: "Input file could not be read",
    AnalysisOutcome.INPUT_MALFORMED: "Input is not a readable CSV",
    AnalysisOutcome.NO_DATA_ROWS: "No readings in the file",
    AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA: "Unknown machine (no matching config)",
    AnalysisOutcome.NO_USABLE_NUMERIC_COLUMNS: "No usable numeric columns",
    AnalysisOutcome.EVIDENCE_TOO_LARGE: "Evidence budget exceeded",
    AnalysisOutcome.MODEL_REJECTED: "AI explanation could not be used",
    AnalysisOutcome.NO_PROPOSALS: "AI returned no usable explanation",
    AnalysisOutcome.ANALYSIS_CONTRADICTED: "Sensors Disagree",
    AnalysisOutcome.ANALYSIS_SUPPORTED: "Fault Confirmed",
    AnalysisOutcome.ANALYSIS_INCONCLUSIVE: "Analysis inconclusive",
    AnalysisOutcome.EXPERIMENTAL_MAPPING_REJECTED: "Draft mapping rejected",
    AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING: (
        "Unknown machine — guessed column meanings, please review"
    ),
}

_OUTCOME_LABELS: dict[AnalysisOutcome, str] = PLAIN_OUTCOME

_OUTCOME_TONES: dict[AnalysisOutcome, OutcomeTone] = {
    AnalysisOutcome.INPUT_UNREADABLE: "error",
    AnalysisOutcome.INPUT_MALFORMED: "error",
    AnalysisOutcome.NO_DATA_ROWS: "warning",
    AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA: "warning",
    AnalysisOutcome.NO_USABLE_NUMERIC_COLUMNS: "warning",
    AnalysisOutcome.EVIDENCE_TOO_LARGE: "warning",
    AnalysisOutcome.MODEL_REJECTED: "error",
    AnalysisOutcome.NO_PROPOSALS: "warning",
    AnalysisOutcome.ANALYSIS_CONTRADICTED: "error",
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


def _anomalies(result: RunResult) -> list[Evidence]:
    return [
        item
        for item in result.evidence
        if item.kind is EvidenceKind.SENSOR_ANOMALY and item.signal is not None
    ]


def _missing(result: RunResult) -> list[Evidence]:
    return [
        item
        for item in result.evidence
        if item.kind is EvidenceKind.MISSING_CHANNEL and item.signal is not None
    ]


def signal_label(result: RunResult, signal: str | None) -> str:
    """Return the engineer-facing label for a signal, or its column name."""
    if signal is None:
        return MISSING
    labels = dict(result.signal_labels)
    return labels.get(signal, signal)


def signal_labels(result: RunResult) -> dict[str, str]:
    """The saved tool-model labels, keyed by CSV column name."""
    return dict(result.signal_labels)


def _signal_list(result: RunResult, items: list[Evidence], limit: int = 3) -> str:
    names = [signal_label(result, item.signal) for item in items if item.signal]
    return ", ".join(names[:limit])


def _headline_entry(output: RCAOutputModel) -> DifferentialEntryModel | None:
    if output.headline_check is None:
        return None
    for item in output.differential:
        if item.check == output.headline_check:
            return item
    return None


def _entry_anomalies(
    result: RunResult, entry: DifferentialEntryModel
) -> list[Evidence]:
    by_id = {item.evidence_id: item for item in result.evidence}
    return [
        by_id[evidence_id]
        for evidence_id in entry.evidence_for
        if evidence_id in by_id
        and by_id[evidence_id].kind is EvidenceKind.SENSOR_ANOMALY
        and by_id[evidence_id].signal is not None
    ]


def result_word(result: RunResult) -> ResultWord | None:
    """Map a Python-owned run to one of the six user-facing result words.

    ``None`` means the run never reached an analysis result (for example an
    unreadable file); those routes keep their own short label. The order is a
    severity order, never a score: contradiction first, then a confirmed check,
    then missing data, then an unexplained anomaly. When a differential exists,
    its Python-chosen headline decides the word; a non-headline row can never
    override it.
    """
    outcome = result.outcome
    if outcome in {
        AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING,
        AnalysisOutcome.NO_MATCHING_TOOL_SCHEMA,
    }:
        return "Unknown Machine"
    if outcome in {AnalysisOutcome.MODEL_REJECTED, AnalysisOutcome.NO_PROPOSALS}:
        return "Needs Review"

    headline = _headline_entry(result.output)
    if headline is not None:
        if headline.status is Verdict.VETOED:
            return "Sensors Disagree"
        if headline.status is Verdict.SUPPORTED:
            return "Fault Confirmed"
        if headline.missing_signals:
            return "Data Incomplete"

    if not result.output.differential:
        statuses = {item.status for item in result.output.hypotheses}
        if (
            outcome is AnalysisOutcome.ANALYSIS_CONTRADICTED
            or Verdict.VETOED in statuses
        ):
            return "Sensors Disagree"
        if (
            outcome is AnalysisOutcome.ANALYSIS_SUPPORTED
            or Verdict.SUPPORTED in statuses
        ):
            return "Fault Confirmed"

    if _missing(result):
        return "Data Incomplete"
    if any(item.proposed_by_model for item in result.output.differential):
        # A model-proposed cause with no saved check is never a confirmation.
        return "Needs Review"
    if _anomalies(result):
        # Anomalies that no confirmed check explains; never hide them behind a
        # green "Regular Behavior".
        return "Needs Review"
    if outcome is AnalysisOutcome.ANALYSIS_INCONCLUSIVE:
        return "Regular Behavior"
    return None


def result_badge(word: ResultWord) -> str:
    """Return the badge text for a result word."""
    return _RESULT_BADGES[word]


def result_tone(word: ResultWord) -> OutcomeTone:
    """Return the Streamlit tone for a result word."""
    return _RESULT_TONES[word]


RESULT_GLOSSARY: list[tuple[str, str]] = [
    (
        "Fault Confirmed",
        "The evidence supports the suspected fault. Inspect the named part.",
    ),
    (
        "Regular Behavior",
        "Every checked signal stayed within its alert level. Keep monitoring.",
    ),
    (
        "Sensors Disagree",
        "One signal moved but the signals that should agree stayed normal. "
        "Check the sensor first.",
    ),
    (
        "Data Incomplete",
        "A required signal is missing from the export. Get the missing data.",
    ),
    (
        "Needs Review",
        "The data is not enough to confirm or rule out a cause, or a large signal "
        "is unexplained. Ask an engineer to review.",
    ),
    (
        "Unknown Machine",
        "No saved tool model matches the export. Review the guessed columns before "
        "trusting them.",
    ),
]

TERM_GLOSSARY: list[tuple[str, str]] = [
    (
        "Fab & tool",
        "A fab is a semiconductor factory where chips are made. A tool is one "
        "machine inside the fab (for example an etcher, deposition chamber, or "
        "ion mill) that streams dozens of sensor channels.",
    ),
    (
        "Wafer, lot & scrap",
        "A wafer is the thin silicon disc that hundreds of chips are built on. "
        "Wafers move through the factory in batches called lots (typically 25 "
        "wafers). If a faulty tool ruins a wafer, it is scrapped.",
    ),
    (
        "Recipe",
        "The exact step-by-step settings (temperatures, pressures, gas flows, RF "
        "power) a tool uses to process a wafer. Changing a recipe on a false "
        "alarm can ruin good wafers.",
    ),
    (
        "Robust z-score",
        "Peak deviation from normal: 0.6745 × |value − median| / MAD. 0.6745 is "
        "Φ⁻¹(0.75), the 75th percentile of the standard normal; for normal data "
        "MAD ≈ 0.6745σ, so the result is in normal-equivalent sigma units. MAD "
        "stops a few fault points from inflating “normal”.",
    ),
    (
        "Alert level (3.5z)",
        "The per-signal screening level (`alert_at`, default 3.5). If the data "
        "were normal, a two-sided 3.5z tail is about 0.047% (roughly 1 in 2,150). "
        "It is a statistical screening choice, editable by the engineer, not a "
        "physics-derived tolerance. Use a tool manual or calibrated limit when "
        "one exists.",
    ),
    (
        "Coverage limit (5z)",
        "Statistical coverage policy: an unexplained anomaly at or above 5z "
        "prevents a bare Fault Confirmed, even when another check passed. If the "
        "data were normal, a two-sided 5z tail is about 0.00006% (roughly 1 in "
        "1.7 million). It is not a sensor calibration and cannot be lowered by a "
        "YAML file.",
    ),
    (
        "Evidence ID",
        "A stable ID for one signal finding. NVIDIA Nemotron may cite only these "
        "IDs; Python resolves every citation.",
    ),
    (
        "Model payload (2 KB)",
        "The bounded statistical summary sent to the model. Raw telemetry never "
        "leaves DuckDB.",
    ),
    (
        "NVIDIA Nemotron",
        "The AI reasoning layer: column mapping, cause proposals, the challenge "
        "check, and the explanation. It never chooses the result or the action.",
    ),
    (
        "Tavily research",
        "Public troubleshooting leads on uncertain results. Context for a human, "
        "never evidence for the gate.",
    ),
]

GLOSSARY: list[tuple[str, str]] = [*RESULT_GLOSSARY, *TERM_GLOSSARY]


@dataclass(frozen=True, slots=True)
class AnswerCard:
    headline: str
    confidence_label: str
    confidence_badge: str
    confidence_tone: OutcomeTone
    confidence_help: str
    action_label: str
    action_explanation: str


DISPLAY_Z_CAP = 50.0


def z_text(value: float | None) -> str:
    """Format a robust z for a human; keep the raw value in Audit.

    A near-zero MAD can produce z-scores in the thousands. That is a valid
    calculation but a useless display; cap it and let Audit keep the number.
    """
    if value is None:
        return MISSING
    magnitude = abs(value)
    if magnitude >= DISPLAY_Z_CAP:
        return f"≥{DISPLAY_Z_CAP:g}z"
    return f"{value:.2f}z"


def _z_text(item: Evidence) -> str:
    return z_text(item.value)


def answer_card(result: RunResult) -> AnswerCard:
    """Build the high-level plain-English answer card for judges and technicians."""
    next_action_lbl = action_label(result.suggested_next_action)
    next_action_expl = result.explanation or action_explanation(
        result.suggested_next_action
    )
    word = result_word(result)

    if word is None:
        # The run never reached an analysis result (for example, an unreadable
        # file). Keep the route label instead of forcing one of the six words.
        return AnswerCard(
            headline=outcome_label(result.outcome),
            confidence_label=outcome_label(result.outcome),
            confidence_badge="[\u26aa STOPPED]",
            confidence_tone=outcome_tone(result.outcome),
            confidence_help="The analysis could not evaluate any equipment fault.",
            action_label=next_action_lbl,
            action_explanation=next_action_expl,
        )

    anomalies = _anomalies(result)
    missing = _missing(result)
    claim = result.output.hypotheses[0].claim if result.output.hypotheses else None

    if word == "Unknown Machine":
        headline = (
            "We do not recognise this machine. Below is our best guess of what "
            "the columns mean; please review it before trusting."
        )
        help_text = (
            "No saved tool model matched this export. Column roles are "
            "AI-inferred drafts."
        )
    elif word == "Sensors Disagree":
        headline = (
            "One sensor moved but the sensor that should agree stayed normal. "
            "This usually means a sensor or data problem, not a real equipment "
            "fault."
        )
        help_text = (
            "The signals that should agree with each other do not. "
            "Check the sensor before acting on the reading."
        )
    elif word == "Fault Confirmed":
        entry = _headline_entry(result.output)
        moved = _entry_anomalies(result, entry) if entry is not None else anomalies
        if moved:
            detail = " and ".join(
                f"{signal_label(result, item.signal)} ({_z_text(item)})"
                for item in moved[:2]
            )
            headline = (
                f"{detail} moved past the alert threshold, confirming "
                f"{claim or 'the suspected fault'}."
            )
        else:
            headline = f"The evidence confirms {claim or 'the suspected fault'}."
        help_text = (
            "The saved check's required signals moved past the alert threshold, "
            "and no contradiction was found in this check."
        )
    elif word == "Data Incomplete":
        headline = (
            f"Required signals are missing from the file: "
            f"{_signal_list(result, missing)}. A fault cannot be judged without them."
        )
        help_text = "Required telemetry columns are absent in the uploaded CSV."
    elif word == "Needs Review":
        challenge = result.output.challenge
        proposed = next(
            (
                item
                for item in result.output.differential
                if item.proposed_by_model
            ),
            None,
        )
        if challenge is not None and challenge.downgraded:
            headline = (
                "The saved check passed, but the AI challenge check found a test "
                "it did not meet. An engineer should review this run before acting."
            )
            help_text = (
                "A challenge check is a disconfirming test, not a new result. The "
                "differential keeps both sides visible."
            )
        elif proposed is not None:
            headline = (
                f"The AI proposed a possible cause ({proposed.title}), but there "
                "is no saved check to confirm or reject it. An engineer should "
                "review this run."
            )
            help_text = (
                "This cause is not saved. Add and test a saved check before "
                "treating it as a fault."
            )
        elif anomalies:
            coverage = result.output.coverage
            unexplained = (
                list(coverage.unexplained_large) if coverage is not None else []
            )
            if unexplained:
                detail = ", ".join(
                    signal_label(result, signal) for signal in unexplained[:3]
                )
                if len(unexplained) > 3:
                    detail += f", and {len(unexplained) - 3} more"
                entry = _headline_entry(result.output)
                passed = _entry_anomalies(result, entry) if entry is not None else []
                passed_names = ", ".join(
                    signal_label(result, item.signal) for item in passed[:3]
                )
                if passed_names:
                    headline = (
                        f"The saved check on {passed_names} passed, but {detail} "
                        "also moved and nothing explains them. We will not confirm "
                        "a single cause until those movements are reviewed."
                    )
                else:
                    headline = (
                        "These signals moved past the alert threshold but are not "
                        f"explained by the saved check: {detail}. An engineer "
                        "should review this run."
                    )
                help_text = (
                    "The saved check did not account for every large movement. "
                    "Nothing was proven; review the differential before acting."
                )
            else:
                detail = " and ".join(
                    f"{signal_label(result, item.signal)} ({_z_text(item)})"
                    for item in anomalies[:2]
                )
                headline = (
                    f"{detail} moved, but no saved check explains it. "
                    "An engineer should review this run."
                )
                help_text = (
                    "Nothing was proven. Review what moved and what was missing "
                    "before acting."
                )
        else:
            headline = (
                "The data is not enough to confirm or rule out a cause. "
                "An engineer should review this run."
            )
            help_text = (
                "Nothing was proven. Review what moved and what was missing "
                "before acting."
            )
    else:  # Regular Behavior
        headline = (
            "Every checked signal stayed below its alert threshold. No fault "
            "pattern was found in this data."
        )
        help_text = "The checked signals stayed within their configured alert limits."

    return AnswerCard(
        headline=headline,
        confidence_label=word,
        confidence_badge=result_badge(word),
        confidence_tone=result_tone(word),
        confidence_help=help_text,
        action_label=next_action_lbl,
        action_explanation=next_action_expl,
    )


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
        return (
            "Unknown machine (no saved tool model matched; the columns were "
            "guessed)"
        )
    coverage = f"{selection.signal_coverage:.0%}"
    return (
        f"{selection.config_name} / {selection.scenario_name} "
        f"({len(selection.matched_signals)} channels matched, {coverage} coverage)"
    )


def summarize(result: RunResult) -> RunSummary:
    """Build the header values shown for every run."""
    mode_label = (
        "Unknown machine (guessed columns)"
        if result.fallback_used
        else "Known machine (Safe path)"
    )
    word = result_word(result)
    return RunSummary(
        outcome_label=word or outcome_label(result.outcome),
        action_label=action_label(result.suggested_next_action),
        explanation=result.explanation
        or action_explanation(result.suggested_next_action),
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
    status: str
    signal: str
    how_unusual: str
    value: str
    unit: str
    statistic: str
    window: str
    summary: str
    evidence_id: str
    alert_threshold: str
    raw_status: str


def _value_text(value: float | None) -> str:
    return MISSING if value is None else f"{value:.4g}"


def _window_text(window: tuple[int, int] | None) -> str:
    return MISSING if window is None else f"{window[0]}\u2013{window[1]}"


def _evidence_status(kind_val: str) -> str:
    if kind_val == "SENSOR_ANOMALY":
        return ":red[Unusual]"
    if kind_val == "SENSOR_NOMINAL":
        return ":green[Normal]"
    if kind_val == "MISSING_CHANNEL":
        return ":orange[Missing]"
    return ":gray[No data]"


def _how_unusual(value: float | None) -> str:
    if value is None:
        return MISSING
    return z_text(value)


def _threshold_text(value: float | None) -> str:
    return MISSING if value is None else f"{value:.2f}z"


def evidence_rows(evidence: tuple[Evidence, ...]) -> list[EvidenceRow]:
    """One row per evidence record, sorted with unusual signals first."""

    def _sort_key(item: Evidence) -> tuple[int, float]:
        kind_prio = 3
        if item.kind.value == "SENSOR_ANOMALY":
            kind_prio = 0
        elif item.kind.value == "MISSING_CHANNEL":
            kind_prio = 1
        elif item.kind.value == "SENSOR_NOMINAL":
            kind_prio = 2
        val_prio = -(item.value or 0.0)
        return (kind_prio, val_prio)

    sorted_evidence = sorted(evidence, key=_sort_key)
    return [
        EvidenceRow(
            status=_evidence_status(item.kind.value),
            signal=item.signal or MISSING,
            how_unusual=_how_unusual(item.value),
            value=_value_text(item.value),
            unit=item.unit or MISSING,
            statistic=item.statistic or MISSING,
            window=_window_text(item.window),
            summary=item.summary,
            evidence_id=item.evidence_id,
            alert_threshold=_threshold_text(item.threshold),
            raw_status=item.kind.value,
        )
        for item in sorted_evidence
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
class DifferentialRow:
    possible_cause: str
    evidence_for: str
    evidence_against: str
    result: str


def _entry_result(entry: DifferentialEntryModel) -> str:
    if entry.proposed_by_model:
        return "Needs Review"
    if entry.status is Verdict.SUPPORTED:
        return "Fault Confirmed"
    if entry.status is Verdict.VETOED:
        return "Sensors Disagree"
    if entry.missing_signals:
        return "Data Incomplete"
    if entry.has_anomaly or entry.challenge_failed:
        return "Needs Review"
    return "Regular Behavior"


def _evidence_names(
    evidence_ids: list[str],
    evidence: tuple[Evidence, ...],
    labels: Mapping[str, str] | None = None,
) -> str:
    by_id = {item.evidence_id: item for item in evidence}
    label_map = {} if labels is None else dict(labels)
    names: list[str] = []
    for evidence_id in evidence_ids:
        item = by_id.get(evidence_id)
        name = (
            item.signal
            if item is not None and item.signal is not None
            else evidence_id
        )
        name = label_map.get(name, name)
        if name not in names:
            names.append(name)
    return ", ".join(names) or MISSING


def differential_rows(
    output: RCAOutputModel,
    evidence: tuple[Evidence, ...] = (),
    labels: Mapping[str, str] | None = None,
) -> list[DifferentialRow]:
    """One plain-language row per saved check plus any unverified proposal."""
    return [
        DifferentialRow(
            possible_cause=item.title,
            evidence_for=_evidence_names(item.evidence_for, evidence, labels),
            evidence_against=_evidence_names(item.evidence_against, evidence, labels),
            result=_entry_result(item),
        )
        for item in output.differential
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


@dataclass(frozen=True, slots=True)
class UnexplainedRow:
    signal: str
    peak_deviation: str
    meaning: str


def unexplained_rows(result: RunResult) -> list[UnexplainedRow]:
    """Declared signals that moved outside every saved check.

    This is the "What else moved" card. It never hides a moderate anomaly; the
    large subset is labelled because it is the subset that changes the headline
    to **Needs Review**.
    """
    coverage = result.output.coverage
    if coverage is None:
        return []
    large = set(coverage.unexplained_large)
    anomalies = {
        item.signal: item
        for item in result.evidence
        if item.kind is EvidenceKind.SENSOR_ANOMALY and item.signal is not None
    }
    rows: list[UnexplainedRow] = []
    for signal in coverage.unexplained:
        item = anomalies.get(signal)
        rows.append(
            UnexplainedRow(
                signal=signal_label(result, signal),
                peak_deviation=MISSING if item is None else _z_text(item),
                meaning=(
                    "Large, unexplained"
                    if signal in large
                    else "Unexplained, below the large-anomaly limit"
                ),
            )
        )
    rows.sort(key=lambda row: row.signal)
    return rows


def model_roles(result: RunResult) -> tuple[str, ...]:
    """The plain role names that took part in this run.

    Model IDs are configuration, not user-facing copy, so this never returns
    one. The explanation is written by the cause finder in the same call.
    """
    roles: list[str] = []
    if result.mapping is not None:
        roles.append("column mapper")
    roles.append("cause finder")
    if result.output.challenge is not None:
        roles.append("challenge check")
    return tuple(roles)


def model_role_text(result: RunResult) -> str:
    return "Nemotron: " + ", ".join(model_roles(result))


def model_payload_bytes(result: RunResult) -> int:
    """Size of the bounded evidence summary Python sent to the model."""
    return evidence_summary_bytes(result.evidence)


def model_payload_text(result: RunResult) -> str:
    return f"{model_payload_bytes(result)} bytes / {MAX_EVIDENCE_BYTES} limit"


def unresolved_citations(result: RunResult) -> tuple[str, ...]:
    """Evidence IDs the model cited that Python could not resolve (audit only)."""
    seen: list[str] = []
    for hypothesis in result.output.hypotheses:
        narrative = hypothesis.model_narrative
        if narrative is None:
            continue
        for evidence_id in narrative.unresolved_citations:
            if evidence_id not in seen:
                seen.append(evidence_id)
    return tuple(seen)


def challenge_audit_rows(result: RunResult) -> list[dict[str, str]]:
    """One audit-only row for the model-proposed challenge, if any."""
    challenge = result.output.challenge
    if challenge is None:
        return []
    return [
        {
            "Status": challenge.status.value,
            "Challenge": challenge.text or MISSING,
            "Expected": challenge.expected or MISSING,
            "Expectation met": (
                MISSING
                if challenge.expectation_met is None
                else ("Yes" if challenge.expectation_met else "No")
            ),
            "Downgraded": "Yes" if challenge.downgraded else "No",
            "Evidence IDs": ", ".join(challenge.cited_evidence) or MISSING,
            "Note": challenge.note or MISSING,
        }
    ]


_BENCHMARK_SYSTEM_KEYS = (
    "system",
    "unsafe_action_rate",
    "correct_cause_rate",
    "appropriate_abstention",
    "false_alarm_rate",
    "evidence_accuracy",
    "n",
)


def benchmark_summary_rows(payload: object) -> list[dict[str, object]]:
    """Validate a committed naive-LLM summary for the performance page.

    The page must never invent a number. An unreadable or unexpected payload
    returns an empty list, and the caller says "benchmark in progress".
    """
    if not isinstance(payload, dict):
        return []
    data = cast(dict[str, object], payload)
    raw = data.get("systems")
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, object]] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            return []
        entry = cast(dict[str, object], item)
        row: dict[str, object] = {}
        for key in _BENCHMARK_SYSTEM_KEYS:
            if key not in entry:
                return []
            row[key] = entry[key]
        rows.append(row)
    return rows


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


def _pretty_header(header: str) -> str:
    """Humanize snake_case headers without destroying proper nouns."""
    text = header.replace("_", " ").strip()
    if "_" in header or text.islower():
        return text.capitalize()
    return text


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
    pretty = [_pretty_header(header) for header in headers]
    lines = [
        "| " + " | ".join(pretty) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [_cell_text(row.get(header)) for header in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
