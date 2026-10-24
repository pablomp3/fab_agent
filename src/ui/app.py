"""FabAgent technician dashboard (W6).

The dashboard is deliberately a glass box: it shows the input preview, the
editable tool configuration, the scoped evidence, the model narrative (clearly
labelled as not gated), the Python-owned verdict and action, and the optional
external references. It never prints an API key or a raw model completion.

Deployment note: the browser never receives a provider key. The server reads
``NEBIUS_API_KEY`` and optional ``TAVILY_API_KEY`` from its environment. When a
live key is present the dashboard defaults to live Nemotron; when it is absent
the deterministic offline transport exercises the same Python gate.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from src.action_guidance import action_label
from src.agents.proposal_request import evidence_summary_bytes
from src.analyze import RunResult, analyze_csv
from src.config_loader import load_relations
from src.core.progress import STAGE_ORDER, ProgressState
from src.core.types import AnalysisOutcome
from src.demo import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.demo_catalog import DEMO_CASES, DemoCase
from src.demo_data import (
    GENERATOR_TEMPLATES,
    GeneratedDataset,
    generate_demo_csv,
)
from src.dossier import DEFAULT_MODELS_CONFIG
from src.model_config import ModelConfigurationError, load_model_route
from src.ui import config_promotion, presentation

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "ui"
_ABOUT_DOC = _DOCS / "about.md"
_MODELS_DOC = _DOCS / "models.md"
_PERFORMANCE_DOC = _DOCS / "performance.md"
_CONTACT_DOC = _DOCS / "contact.md"
_VERDICTS_DOC = _DOCS / "verdicts.md"
_YAML_DOC = _DOCS / "yaml_guide.md"

_DISCLAIMER = (
    "FabAgent is an evidence-gated troubleshooting copilot. It suggests a typed "
    "next step; a human decides. Results are tied to the configured "
    "relationships and are not field validation."
)

_BEHAVIOR_LABELS = {
    "supported": "Fault pattern present",
    "inconclusive": "Nominal pattern",
    "contradiction": "One sensor only (contradiction)",
}

_STAGE_LABELS = {
    "read": "Read the CSV",
    "triage": "Match the dataset to a tool configuration",
    "mapping": "Ask Nemotron for a draft channel mapping (experimental)",
    "duckdb": "Scan with DuckDB and compute robust statistics",
    "python": "Run Python evidence checks",
    "model": "Ask Nemotron for the narrative",
    "gate": "Apply the Python gate and choose the next action",
    "tavily": "Look up external references with Tavily",
}

_STAGE_ICONS = {
    "pending": ":material/radio_button_unchecked:",
    "running": ":material/pending:",
    "done": ":material/check_circle:",
    "skipped": ":material/skip_next:",
    "failed": ":material/error:",
}

_CUSTOM_CONFIG_TEMPLATE = """\
version: 1
name: custom_tool
provenance: "Replace with the tool manual, calibration source, or engineer review."
signals:
  - name: sensor_a
    unit: null
    robust_z_threshold: 3.5
    threshold_source: "user_configured"
  - name: sensor_b
    unit: null
    robust_z_threshold: 3.5
    threshold_source: "user_configured"
scenarios:
  custom_fault:
    signals:
      - name: sensor_a
        unit: null
        robust_z_threshold: 3.5
        threshold_source: "user_configured"
      - name: sensor_b
        unit: null
        robust_z_threshold: 3.5
        threshold_source: "user_configured"
    predicates:
      primary_signals: [sensor_a, sensor_b]
    rules:
      equipment_fault:
        require_all: [has_primary_signal_anomaly]
        forbid_any: [has_missing_required_evidence]
    candidate:
      claim: custom configured fault
      hypothesis_class: equipment_fault
      cited_signals: [sensor_a, sensor_b]
      root_cause: equipment_fault
      failure_mode: Replace with the failure mode from the tool documentation.
      mechanism: Replace with the mechanism from the tool documentation.
    supported_action: INSPECT_COMPONENT
"""


def _table(rows: list[dict[str, object]]) -> None:
    st.markdown(presentation.markdown_table(rows))


def _callout(tone: presentation.OutcomeTone, message: str) -> None:
    if tone == "success":
        st.success(message)
    elif tone == "warning":
        st.warning(message)
    elif tone == "error":
        st.error(message)
    else:
        st.info(message)


def _behavior_label(value: str) -> str:
    return _BEHAVIOR_LABELS.get(value, value)


def _server_has_key(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _model_label() -> str:
    try:
        return load_model_route(DEFAULT_MODELS_CONFIG, "SYNTHESIS").model
    except ModelConfigurationError:
        return "configured Nemotron route"


def _render_markdown_file(path: Path) -> None:
    try:
        st.markdown(path.read_text(encoding="utf-8"))
    except OSError as exc:
        st.error(f"Could not load {path.name}: {exc}")


def _preview_rows_from_text(
    text: str, limit: int = 5
) -> tuple[list[str], list[dict[str, object]]]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], []
    rows: list[dict[str, object]] = []
    for _, row in zip(range(limit), reader, strict=False):
        rows.append(
            {
                header[index]: row[index] if index < len(row) else ""
                for index in range(len(header))
            }
        )
    return header, rows


def _preview_rows_from_path(
    path: Path, limit: int = 5
) -> tuple[list[str], list[dict[str, object]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        rows: list[dict[str, object]] = []
        for _, row in zip(range(limit), reader, strict=False):
            rows.append(
                {
                    header[index]: row[index] if index < len(row) else ""
                    for index in range(len(header))
                }
            )
    return header, rows


def _render_preview(
    columns: list[str],
    rows: list[dict[str, object]],
    column_notes: tuple[tuple[str, str], ...],
) -> None:
    if not columns:
        st.info("The file has no header.")
        return
    visible = columns[:8]
    visible_rows = [
        {column: row.get(column, "") for column in visible} for row in rows
    ]
    column_note = (
        f" · showing first {len(visible)} columns"
        if len(columns) > len(visible)
        else ""
    )
    st.caption(
        f"{len(columns)} columns · first {len(rows)} rows{column_note}"
    )
    if not rows:
        st.info("The file has a header but no data rows.")
        return
    _table(visible_rows)
    notes = dict(column_notes)
    with st.expander("What do these columns mean?", expanded=True):
        if notes:
            guide = [
                {
                    "column": column,
                    "first value": rows[0].get(column, ""),
                    "what it means": notes[column],
                }
                for column in columns
                if column in notes
            ]
            _table(guide)
            st.caption(
                "Only the important or configured columns are described here. "
                "The other columns remain available in the evidence table."
            )
        else:
            guide = [
                {
                    "column": column,
                    "first value": rows[0].get(column, ""),
                    "what it means": (
                        "No plain-language note for this upload; check the tool "
                        "manual or a known export specification."
                    ),
                }
                for column in visible
            ]
            _table(guide)


def _render_preview_from_text(
    text: str, column_notes: tuple[tuple[str, str], ...] = ()
) -> None:
    try:
        columns, rows = _preview_rows_from_text(text)
    except (UnicodeDecodeError, csv.Error) as exc:
        st.error(f"The file could not be previewed: {exc}")
        return
    _render_preview(columns, rows, column_notes)


def _render_preview_from_path(
    path: Path, column_notes: tuple[tuple[str, str], ...] = ()
) -> None:
    try:
        columns, rows = _preview_rows_from_path(path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        st.error(f"The file could not be previewed: {exc}")
        return
    _render_preview(columns, rows, column_notes)


def _render_config_summary(
    config_path: Path,
    signal_notes: tuple[tuple[str, str], ...],
) -> None:
    try:
        relations = load_relations(config_path)
    except (OSError, ValueError) as exc:
        st.warning(f"The bundled configuration could not be read: {exc}")
        return
    st.markdown(f"**{relations.name}** · {relations.provenance}")
    scenario_rows: list[dict[str, object]] = []
    for name, scenario in sorted(relations.scenarios.items()):
        scenario_rows.append(
            {
                "scenario": name,
                "configured candidate": scenario.candidate.claim,
                "primary channels": ", ".join(
                    sorted(scenario.predicate_config.primary_signals)
                )
                or presentation.MISSING,
                "corroboration": ", ".join(
                    sorted(scenario.predicate_config.corroboration_signals)
                )
                or presentation.MISSING,
                "if supported": action_label(scenario.supported_action),
            }
        )
    st.caption("Configured scenarios")
    _table(scenario_rows)
    notes = dict(signal_notes)
    signal_rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for scenario in relations.scenarios.values():
        for signal in scenario.signals:
            if signal.name in seen:
                continue
            seen.add(signal.name)
            threshold = (
                f"{signal.robust_z_threshold:g}"
                if signal.robust_z_threshold is not None
                else presentation.MISSING
            )
            signal_rows.append(
                {
                    "channel": signal.name,
                    "unit": signal.unit or presentation.MISSING,
                    "anomaly threshold": threshold,
                    "what it means": notes.get(
                        signal.name,
                        "Configured channel; see the YAML and the tool manual.",
                    ),
                }
            )
    if signal_rows:
        st.caption("Configured channels")
        _table(signal_rows)


def _render_config_editor(
    default_yaml: str | None,
    *,
    key: str,
    default_use: bool,
    auto_label: str,
    config_path: Path | None = None,
    signal_notes: tuple[tuple[str, str], ...] = (),
) -> tuple[str | None, bool]:
    """Return ``(yaml_text, auto_detect)`` for the run.

    The editor is intentionally plain text. The same config loader the engine
    uses validates it at run time; a bad edit is rejected before analysis.
    """
    if default_yaml is None:
        st.caption(
            "No bundled config matches this input by design. The safe path will "
            "return no matching schema and the experimental fallback will run."
        )
        with st.expander("What do these YAML fields mean?", expanded=False):
            _render_markdown_file(_YAML_DOC)
        return None, True
    if config_path is not None:
        _render_config_summary(config_path, signal_notes)
    with st.expander("What do these YAML fields mean?", expanded=False):
        _render_markdown_file(_YAML_DOC)
    with st.expander("Edit the YAML", expanded=False):
        st.caption(
            "The run uses this text when the checkbox is on. The config loader "
            "validates it; nothing is saved to the repository from this panel."
        )
        text = st.text_area(
            "Sensor-relations YAML",
            value=default_yaml,
            height=300,
            key=f"{key}_yaml",
        )
        use = st.checkbox(
            "Use this YAML for the run",
            value=default_use,
            key=f"{key}_use",
        )
        st.caption(auto_label)
    if not use:
        return None, True
    return text, False


def _tavily_label(status: str, count: int) -> str:
    if status == "completed":
        return f"{count} refs"
    if status == "not_configured":
        return "not configured"
    if status == "not_needed":
        return "not needed"
    if status == "unavailable":
        return "unavailable"
    if status == "disabled":
        return "disabled"
    return "not run"


def _tavily_progress_text(result: RunResult) -> str:
    status = result.external_search_status
    if status == "completed":
        return f"{result.external_search_count} reference(s)"
    if status == "not_configured":
        return "skipped — no server key"
    if status == "not_needed":
        return "skipped — the safe result did not need it"
    if status == "unavailable":
        return "failed — search was unavailable"
    if status == "disabled":
        return "skipped — turned off"
    return "skipped"


def _tavily_progress_state(result: RunResult) -> str:
    if result.external_search_status == "completed":
        return "done"
    if result.external_search_status == "unavailable":
        return "failed"
    return "skipped"


def _result_progress_text(result: RunResult) -> str:
    if result.outcome is AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING:
        return "UNVERIFIED MAPPING — review the draft, do not treat it as a root cause"
    if result.output.hypotheses:
        return result.output.hypotheses[0].status.value
    return presentation.outcome_label(result.outcome)


def _progress_markdown(
    steps: dict[str, ProgressState],
    result: RunResult | None = None,
) -> str:
    lines: list[str] = []
    for step in STAGE_ORDER:
        state: str = steps.get(step, "pending")
        label = _STAGE_LABELS[step]
        if result is not None and step not in steps:
            state = "skipped"
        if result is not None and step == "mapping" and result.mode == "safe":
            state = "skipped"
        if result is not None and step == "tavily":
            state = _tavily_progress_state(result)
            label = f"Tavily external references: {_tavily_progress_text(result)}"
        icon = _STAGE_ICONS.get(state, _STAGE_ICONS["pending"])
        lines.append(f"{icon} {label}")
    if result is not None:
        lines.append(
            f":material/flag: Result: {_result_progress_text(result)}"
        )
        lines.append(
            f":material/arrow_forward: Next action: "
            f"{action_label(result.suggested_next_action)}"
        )
    return "\n\n".join(lines)


def _run_analysis(
    data: bytes,
    note: str,
    *,
    demo_mode: bool,
    config_yaml: str | None,
    auto_detect: bool,
    label: str,
    use_tavily: bool,
) -> RunResult | None:
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "input.csv"
            path.write_bytes(data)
            search_dir: Path | None = None
            if not auto_detect and config_yaml is not None:
                config_promotion.validate_draft_yaml(config_yaml)
                config_dir = root / "config"
                config_dir.mkdir()
                (config_dir / "tool.yaml").write_text(
                    config_yaml, encoding="utf-8"
                )
                search_dir = config_dir
            steps: dict[str, ProgressState] = {}
            search_enabled = use_tavily or not _server_has_key("TAVILY_API_KEY")
            with st.status("Running FabAgent...", expanded=True) as status:
                checklist = st.empty()

                def progress(step: str, state: ProgressState) -> None:
                    steps[step] = state
                    checklist.markdown(_progress_markdown(steps))

                try:
                    if demo_mode:
                        transport = ExperimentalEchoTransport()
                        if search_dir is None:
                            result = analyze_csv(
                                path,
                                note,
                                engine_factory=offline_engine_factory(transport),
                                mapping_factory=offline_mapping_factory(transport),
                                enable_external_search=search_enabled,
                                progress=progress,
                            )
                        else:
                            result = analyze_csv(
                                path,
                                note,
                                search_dir=search_dir,
                                engine_factory=offline_engine_factory(transport),
                                mapping_factory=offline_mapping_factory(transport),
                                enable_external_search=search_enabled,
                                progress=progress,
                            )
                    else:
                        if search_dir is None:
                            result = analyze_csv(
                                path,
                                note,
                                enable_external_search=search_enabled,
                                progress=progress,
                            )
                        else:
                            result = analyze_csv(
                                path,
                                note,
                                search_dir=search_dir,
                                enable_external_search=search_enabled,
                                progress=progress,
                            )
                except Exception:
                    status.update(
                        label="Run failed", state="error", expanded=True
                    )
                    raise
                checklist.markdown(_progress_markdown(steps, result=result))
                status.update(
                    label="Run complete — result below",
                    state="complete",
                    expanded=True,
                )
            st.session_state["result_mode"] = (
                "offline" if demo_mode else "live"
            )
            st.session_state["result_label"] = label
            st.session_state["result_config_yaml"] = config_yaml
            return result
    except config_promotion.DraftConfigError as exc:
        st.error(str(exc))
    except ModelConfigurationError as exc:
        st.error(
            f"{exc}. The deployment must provide the model credential in its "
            "server environment."
        )
    except Exception:  # a UI boundary must not leak a traceback to the page
        st.error(
            "The analysis could not run. Check the file and the model "
            "configuration, then try again."
        )
    return None


def _verdict_plain(result: RunResult) -> str:
    if result.outcome is AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING:
        return (
            "This is an unverified mapping, not a root cause. Review the draft "
            "mapping before trusting it."
        )
    if not result.output.hypotheses:
        return (
            "No gated hypothesis was produced. Use the route and next action "
            "above; do not infer a fault."
        )
    status = result.output.hypotheses[0].status.value
    if status == "SUPPORTED":
        return (
            "The configured candidate met every required check. A human still "
            "confirms the next step."
        )
    if status == "INSUFFICIENT":
        return (
            "The configured candidate did not meet every required check. This "
            "is not a fault diagnosis; collect or verify the missing evidence."
        )
    if status == "VETOED":
        return (
            "A hard contradiction was found in the configured evidence. Review "
            "the contradiction before acting."
        )
    return "Read the gated conclusion and the evidence table before acting."


def _render_summary(result: RunResult) -> None:
    summary = presentation.summarize(result)
    _callout(presentation.outcome_tone(result.outcome), f"**{summary.outcome_label}**")
    st.markdown(f"### Suggested next step: {summary.action_label}")
    st.write(summary.explanation)
    st.caption(f"What this means: {_verdict_plain(result)}")
    if summary.detail:
        st.caption(summary.detail)
    top = st.columns(4)
    top[0].metric(
        "Analysis", "performed" if summary.analysis_performed else "not performed"
    )
    top[1].metric(
        "Model narrative", "generated" if summary.model_called else "not called"
    )
    top[2].metric("Evidence records", summary.evidence_count)
    top[3].metric("Gated hypotheses", summary.hypothesis_count)
    st.caption(f"Mode: {summary.mode_label} · {summary.triage}")


def _render_stepper(result: RunResult) -> None:
    """Show the five stages explicitly, so the gate is not a black box."""
    selection = result.selection
    hypotheses = result.output.hypotheses
    status = hypotheses[0].status.value if hypotheses else "no verdict"
    if result.outcome is AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING:
        gate_value = "unverified mapping"
    else:
        gate_value = status
    steps = [
        (
            "1 · Triage",
            selection.scenario_name if selection is not None else "no schema",
        ),
        ("2 · Evidence", f"{len(result.evidence)} records"),
        (
            "3 · Narrative",
            "generated" if result.model_called else "not called",
        ),
        ("4 · Python gate", gate_value),
        (
            "5 · Next action",
            presentation.action_label(result.suggested_next_action),
        ),
    ]
    columns = st.columns(len(steps))
    for column, (label, value) in zip(columns, steps, strict=True):
        column.metric(label, value)
    st.caption(
        "The model may propose and explain; only the configured candidate, the "
        "cited evidence, and the Python rules determine the verdict and action."
    )


def _render_calls(result: RunResult) -> None:
    st.subheader("Live calls and bounded data")
    mode = str(st.session_state.get("result_mode", "unknown"))
    narratives = [
        hypothesis.model_narrative
        for hypothesis in result.output.hypotheses
        if hypothesis.model_narrative is not None
    ]
    cited = sum(len(item.cited_evidence) for item in narratives)
    unresolved = sum(len(item.unresolved_citations) for item in narratives)
    evidence_bytes = evidence_summary_bytes(result.evidence) if result.evidence else 0
    columns = st.columns(3)
    if result.model_called:
        model_state = "live call completed" if mode == "live" else "offline fixture"
    else:
        model_state = "not called"
    columns[0].metric("Nemotron", model_state)
    columns[0].caption(
        f"{_model_label()} · {len(narratives)} narrative(s), {cited} citation(s)"
    )
    columns[1].metric("Evidence sent", f"{evidence_bytes} B")
    columns[1].caption(f"{len(result.evidence)} records · bounded to 2 KB")
    columns[2].metric(
        "Tavily",
        _tavily_label(
            result.external_search_status, result.external_search_count
        ),
    )
    if result.external_search_query:
        columns[2].caption(f"query: {result.external_search_query}")
    st.caption(
        "The browser never receives the provider keys, and no raw model "
        "completion is shown. The narrative is separate from the Python gate."
    )
    if unresolved:
        st.warning(
            f"The model cited {unresolved} evidence ID(s) Python could not "
            "resolve. They are shown for transparency and are not gated."
        )
    if result.external_search_status == "not_configured":
        st.caption(
            "Tavily is not configured on this deployment. The server can enable "
            "it with `TAVILY_API_KEY`; external references never change the "
            "verdict."
        )
    if result.output.external_sources:
        rows: list[dict[str, object]] = [
            {
                "title": source.title or "External reference",
                "url": source.url,
                "why": source.why_consulted,
            }
            for source in result.output.external_sources
        ]
        _table(rows)


def _render_conclusion(result: RunResult) -> None:
    output = result.output
    st.subheader("Gated conclusion")
    if not output.hypotheses:
        st.caption(
            "No gated hypothesis was produced for this run. The route and "
            "action above are the result."
        )
    experimental = result.outcome is AnalysisOutcome.EXPERIMENTAL_UNVERIFIED_MAPPING
    for hypothesis in output.hypotheses:
        if experimental:
            st.warning(f"**UNVERIFIED MAPPING** — {hypothesis.claim}")
            st.caption(
                "Internal gate status for the draft mapping: "
                f"{hypothesis.status.value}. This is not a verified root cause."
            )
        else:
            _callout(
                presentation.verdict_tone(hypothesis.status),
                f"**{hypothesis.status.value}** — {hypothesis.claim}",
            )
        columns = st.columns(3)
        columns[0].metric("Root cause", hypothesis.root_cause.value)
        columns[1].metric("Hypothesis class", hypothesis.hypothesis_class)
        columns[2].metric("Citations", len(hypothesis.cited_evidence))
        st.caption(f"Configured failure mode: {hypothesis.failure_mode}")
        st.caption(f"Configured mechanism: {hypothesis.mechanism}")
        if hypothesis.veto_reason:
            st.caption(f"Veto: {hypothesis.veto_reason}")
        narrative = hypothesis.model_narrative
        if narrative is not None and narrative.claim != hypothesis.claim:
            st.caption(
                "The model narrative proposes a different claim. The gate above "
                "follows the configured candidate, not the narrative."
            )
        if hypothesis.status.value == "VETOED":
            st.caption(
                "The Python contradiction veto wins over any model story."
            )

    rows = [asdict(row) for row in presentation.model_narrative_rows(output)]
    if rows:
        with st.expander("Model explanation (not gated)", expanded=False):
            _table(rows)
            st.caption(
                "This is the model's narrative. It is shown for review and is "
                "not used to compute the claim, status, citations, or action "
                "above."
            )

    if output.required_next_checks:
        st.markdown("**Required next checks**")
        for check in output.required_next_checks:
            st.write(f"- {check}")


def _render_evidence(result: RunResult) -> None:
    with st.expander(f"Evidence records ({len(result.evidence)})", expanded=False):
        if not result.evidence:
            st.caption("No evidence was produced for this run.")
            return
        rows = [asdict(row) for row in presentation.evidence_rows(result.evidence)]
        _table(rows)
        st.caption(
            "Unknown units and values are shown as \u2014, never guessed. Every "
            "citation in a hypothesis is re-resolved by Python."
        )


def _render_mapping(result: RunResult) -> None:
    mapping = result.mapping
    if mapping is None:
        return
    st.divider()
    st.subheader("Experimental mapping (unverified)")
    st.warning(
        "This mapping was inferred from column names and summary statistics. It "
        "is not a validated schema: units are not propagated and no physical "
        "root cause is claimed. Review before trusting anything below."
    )
    signals = [asdict(row) for row in presentation.mapping_signal_rows(mapping)]
    _table(signals)
    relationships = [
        asdict(row) for row in presentation.mapping_relationship_rows(mapping)
    ]
    _table(relationships)

    if not result.draft_yaml:
        return
    st.markdown("**Draft config** — save it to turn the next run into the safe path.")
    st.code(result.draft_yaml, language="yaml")
    st.download_button(
        "Download draft config",
        data=result.draft_yaml,
        file_name="experimental_draft.yaml",
        mime="text/yaml",
    )
    with st.form("promote_draft"):
        name = st.text_input("Config name", value="experimental_draft")
        overwrite = st.checkbox("Replace an existing config with this name")
        submitted = st.form_submit_button("Save draft config")
    if submitted:
        try:
            saved = config_promotion.save_draft_config(
                result.draft_yaml, name, overwrite=overwrite
            )
        except (config_promotion.DraftConfigError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Saved {saved.name}. Re-running with these columns now uses the "
                "deterministic safe path."
            )


def _render_result(result: RunResult) -> None:
    _render_summary(result)
    _render_stepper(result)
    _render_calls(result)
    if result.mapping is not None:
        _render_mapping(result)
    _render_conclusion(result)
    _render_evidence(result)
    st.divider()
    st.caption(_DISCLAIMER)


def _render_verdict_legend() -> None:
    with st.expander(
        "What do SUPPORTED, INSUFFICIENT, VETOED, and EXPERIMENTAL mean?",
        expanded=True,
    ):
        _render_markdown_file(_VERDICTS_DOC)


def _render_live_step() -> None:
    use_live_nemotron = bool(st.session_state.get("use_live_nemotron", False))
    use_tavily = bool(st.session_state.get("use_live_tavily", False))
    tavily_configured = _server_has_key("TAVILY_API_KEY")
    with st.container(border=True):
        st.markdown("### Step 4 — Choose live services")
        columns = st.columns(2)
        columns[0].metric(
            "Nemotron", "Live" if use_live_nemotron else "Offline"
        )
        columns[0].caption(
            "Live when the server has a Nebius key. Change this in the "
            "**Live services** panel in the sidebar."
        )
        tavily_value = (
            ("On" if use_tavily else "Off")
            if tavily_configured
            else "Not configured"
        )
        columns[1].metric("Tavily", tavily_value)
        columns[1].caption(
            "Only used for inconclusive or experimental results. Change this in "
            "the sidebar."
        )
        if not use_live_nemotron:
            st.caption(
                "Offline mode uses the deterministic transport through the same "
                "Python gate, so the workflow is still complete without a key."
            )


def _render_demo_runner(demo_mode: bool, use_tavily: bool) -> None:
    with st.container(border=True):
        st.markdown("### Step 2 — Review the dataset")
        choice = st.selectbox(
            "Dataset",
            list(DEMO_CASES),
            format_func=lambda key: DEMO_CASES[key].label,
        )
        case: DemoCase = DEMO_CASES[choice]
        st.caption(f"**{case.source}**")
        st.markdown(f"**What to expect:** {case.expected}")
        st.caption(
            "The expected result is a demo note. The gate still computes the "
            "result from the data and the configuration."
        )
        st.info(case.description)
        _render_preview_from_path(case.csv_path, case.column_notes)

    default_yaml: str | None = None
    if case.config_path is not None:
        try:
            default_yaml = case.config_path.read_text(encoding="utf-8")
        except OSError as exc:
            st.error(f"The bundled config could not be read: {exc}")
    with st.container(border=True):
        st.markdown("### Step 3 — Review the configuration")
        st.caption(
            "The YAML names the channels, thresholds, candidate claim, and the "
            "typed action allowed when the candidate is supported."
        )
        config_yaml, auto_detect = _render_config_editor(
            default_yaml,
            key=f"demo_{case.key}",
            default_use=True,
            auto_label=(
                "Uncheck to let triage auto-detect a bundled config instead of "
                "using this YAML."
            ),
            config_path=case.config_path,
            signal_notes=case.signal_notes,
        )

    _render_live_step()

    with st.container(border=True):
        st.markdown("### Step 5 — Run and read the result")
        _render_verdict_legend()
        note = st.text_area(
            "Engineer note (optional)",
            value=case.note,
            key=f"note_{case.key}",
            max_chars=1000,
            help=(
                "A short context note. It is sent to the narrative model, but it "
                "cannot change the Python verdict or action."
            ),
        )
        if st.button("Run this dataset", type="primary", key=f"run_{case.key}"):
            try:
                data = case.csv_path.read_bytes()
            except OSError as exc:
                st.error(f"The dataset CSV could not be read: {exc}")
            else:
                st.session_state["result"] = _run_analysis(
                    data,
                    note,
                    demo_mode=demo_mode,
                    config_yaml=config_yaml,
                    auto_detect=auto_detect,
                    label=case.label,
                    use_tavily=use_tavily,
                )


def _render_upload_runner(demo_mode: bool, use_tavily: bool) -> None:
    with st.container(border=True):
        st.markdown("### Step 2 — Upload and review the dataset")
        uploaded = st.file_uploader("Tool export (CSV)", type=["csv"])
        if uploaded is None:
            st.caption(
                "Upload a raw tool export. The first rows will be previewed "
                "before anything is sent to a model."
            )
        else:
            try:
                preview_text = uploaded.getvalue().decode("utf-8-sig")
            except UnicodeDecodeError:
                st.error("The uploaded CSV is not valid UTF-8 text.")
            else:
                _render_preview_from_text(preview_text)

    with st.container(border=True):
        st.markdown("### Step 3 — Review the configuration")
        st.caption(
            "Auto-detect tries the bundled tool configurations first. If none "
            "matches, FabAgent falls back to an unverified experimental mapping."
        )
        config_yaml, auto_detect = _render_config_editor(
            _CUSTOM_CONFIG_TEMPLATE,
            key="upload_config",
            default_use=False,
            auto_label=(
                "If unchecked, FabAgent auto-detects from the bundled configs. If "
                "none matches, it runs the experimental fallback."
            ),
        )

    _render_live_step()

    with st.container(border=True):
        st.markdown("### Step 5 — Run and read the result")
        _render_verdict_legend()
        note = st.text_area(
            "Engineer note (optional)",
            placeholder=(
                "e.g. RF reflectometer excursion on Chamber B, wafer edge thinning"
            ),
            max_chars=1000,
            key="upload_note",
            help=(
                "A short context note. It is sent to the narrative model, but it "
                "cannot change the Python verdict or action."
            ),
        )
        if st.button(
            "Analyze this dataset",
            type="primary",
            disabled=uploaded is None,
            key="run_upload",
        ):
            if uploaded is not None:
                st.session_state["result"] = _run_analysis(
                    uploaded.getvalue(),
                    note,
                    demo_mode=demo_mode,
                    config_yaml=config_yaml,
                    auto_detect=auto_detect,
                    label=uploaded.name,
                    use_tavily=use_tavily,
                )


def _render_generator_runner(demo_mode: bool, use_tavily: bool) -> None:
    with st.container(border=True):
        st.markdown("### Step 2 — Generate and review a dataset")
        template_key = st.selectbox(
            "Dataset template",
            list(GENERATOR_TEMPLATES),
            format_func=lambda key: GENERATOR_TEMPLATES[key].label,
        )
        template = GENERATOR_TEMPLATES[template_key]
        st.info(template.description)
        columns = st.columns(3)
        rows = columns[0].slider("Rows", 60, 1200, 240, 20)
        seed = columns[1].number_input("Seed", 0, 999999, 7, 1)
        behavior = columns[2].selectbox(
            "Pattern",
            template.behaviors,
            format_func=_behavior_label,
        )
        st.caption(
            "The generator writes a nominal lead-in and an optional drift after "
            "60% of the rows. It never writes a ground-truth label."
        )
        if st.button("Generate dataset", key="generate_csv"):
            try:
                st.session_state["generated"] = generate_demo_csv(
                    template_key,
                    rows=int(rows),
                    seed=int(seed),
                    behavior=behavior,
                )
            except ValueError as exc:
                st.error(str(exc))

        generated = st.session_state.get("generated")
        if not isinstance(generated, GeneratedDataset):
            st.caption(
                "Generate a seeded synthetic dataset to preview it and run it "
                "through the same workflow."
            )
            return
        st.caption(
            f"Generated {generated.filename} · {generated.rows} rows · "
            f"{_behavior_label(generated.behavior)} · "
            f"seed {generated.seed}"
        )
        _render_preview_from_text(
            generated.csv_bytes.decode("utf-8"),
            generated.template.column_notes,
        )
        st.download_button(
            "Download generated dataset",
            data=generated.csv_bytes,
            file_name=generated.filename,
            mime="text/csv",
        )

    default_yaml: str | None = None
    if generated.template.config_path is not None:
        try:
            default_yaml = generated.template.config_path.read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            st.error(f"The bundled config could not be read: {exc}")
    with st.container(border=True):
        st.markdown("### Step 3 — Review the configuration")
        st.caption(
            "The generated dataset uses the same YAML contract as the prepared "
            "datasets. You can edit it before running."
        )
        config_yaml, auto_detect = _render_config_editor(
            default_yaml,
            key=(
                f"generated_{generated.template.key}_{generated.behavior}_"
                f"{generated.seed}"
            ),
            default_use=True,
            auto_label=(
                "Uncheck to auto-detect a bundled config instead of using this YAML."
            ),
            config_path=generated.template.config_path,
        )

    _render_live_step()

    with st.container(border=True):
        st.markdown("### Step 5 — Run and read the result")
        _render_verdict_legend()
        note = st.text_area(
            "Engineer note (optional)",
            value=generated.template.note,
            key=(
                f"generated_note_{generated.template.key}_{generated.behavior}_"
                f"{generated.seed}"
            ),
            max_chars=1000,
            help=(
                "A short context note. It is sent to the narrative model, but it "
                "cannot change the Python verdict or action."
            ),
        )
        if st.button(
            "Run this dataset",
            type="primary",
            key="run_generated",
        ):
            st.session_state["result"] = _run_analysis(
                generated.csv_bytes,
                note,
                demo_mode=demo_mode,
                config_yaml=config_yaml,
                auto_detect=auto_detect,
                label=generated.filename,
                use_tavily=use_tavily,
            )


def _init_live_state(
    live_configured: bool, tavily_configured: bool
) -> None:
    st.session_state.setdefault("use_live_nemotron", live_configured)
    st.session_state.setdefault("use_live_tavily", tavily_configured)


def _render_sidebar(live_configured: bool, tavily_configured: bool) -> None:
    with st.sidebar:
        st.divider()
        st.header("Live services")
        if live_configured:
            st.toggle(
                "Use live Nemotron",
                key="use_live_nemotron",
                help=(
                    "The server holds the Nebius credential. Turning this off "
                    "uses the deterministic offline transport through the same "
                    "Python gate."
                ),
            )
            st.success("Live Nemotron is available on this server.")
        else:
            st.session_state["use_live_nemotron"] = False
            st.toggle(
                "Use live Nemotron",
                value=False,
                disabled=True,
            )
            st.info(
                "Live Nemotron is not configured. The offline transport "
                "exercises the same triage, evidence, and Python gate."
            )
        if tavily_configured:
            st.toggle(
                "Use live Tavily search",
                key="use_live_tavily",
                help=(
                    "Tavily is optional. It runs only for inconclusive or "
                    "experimental results and cannot change the verdict."
                ),
            )
            st.success("Tavily is available on this server.")
        else:
            st.session_state["use_live_tavily"] = False
            st.toggle(
                "Use live Tavily search",
                value=False,
                disabled=True,
            )
            st.warning(
                "Tavily is not configured. External references are optional and "
                "never change the verdict."
            )
        st.caption(
            "Provider keys stay in the server environment. The browser never "
            "receives them, and this page never displays them."
        )
        st.caption(f"Model route: {_model_label()}")
        st.caption(_DISCLAIMER)


def _page_about() -> None:
    _render_markdown_file(_ABOUT_DOC)


def _page_models() -> None:
    _render_markdown_file(_MODELS_DOC)
    st.subheader("Current server configuration")
    rows: list[dict[str, object]] = [
        {
            "service": "NVIDIA Nemotron",
            "route": _model_label(),
            "credential": (
                "configured on the server"
                if _server_has_key("NEBIUS_API_KEY")
                else "not configured — offline transport"
            ),
        },
        {
            "service": "Tavily",
            "route": "public web search",
            "credential": (
                "configured on the server"
                if _server_has_key("TAVILY_API_KEY")
                else "not configured — search is skipped"
            ),
        },
    ]
    _table(rows)
    st.caption(
        "The browser never receives a provider key. The server-side key is the "
        "only credential used for a live call."
    )


def _page_performance() -> None:
    _render_markdown_file(_PERFORMANCE_DOC)


def _page_contact() -> None:
    _render_markdown_file(_CONTACT_DOC)


def _page_run() -> None:
    st.title("Run a troubleshooting case")
    st.markdown(
        "Follow the five steps below. The workflow is the same whether you use "
        "a prepared dataset, your own CSV, or a generated dataset."
    )
    st.info(
        "New here? Open **What is FabAgent?** in the sidebar for the component "
        "diagram and the one-minute explanation."
    )
    with st.container(border=True):
        st.markdown("### Step 1 — Choose a dataset")
        source = st.segmented_control(
            "Input source",
            [
                "Prepared dataset",
                "Upload my own CSV",
                "Generate synthetic dataset",
            ],
            default="Prepared dataset",
            label_visibility="collapsed",
        )
        source = source or "Prepared dataset"
        st.caption(
            "A dataset here means a CSV export plus the YAML configuration that "
            "describes its channels and the candidate Python is allowed to test."
        )

    use_live_nemotron = bool(st.session_state.get("use_live_nemotron", False))
    use_tavily = bool(st.session_state.get("use_live_tavily", False))
    demo_mode = not use_live_nemotron
    if source == "Prepared dataset":
        _render_demo_runner(demo_mode, use_tavily)
    elif source == "Upload my own CSV":
        _render_upload_runner(demo_mode, use_tavily)
    else:
        _render_generator_runner(demo_mode, use_tavily)

    result = st.session_state.get("result")
    if isinstance(result, RunResult):
        st.divider()
        st.header("Result")
        label = st.session_state.get("result_label")
        if isinstance(label, str) and label:
            st.caption(f"Last run: {label}")
        _render_result(result)


def main() -> None:
    st.set_page_config(page_title="FabAgent", page_icon="\U0001f52c", layout="wide")
    live_configured = _server_has_key("NEBIUS_API_KEY")
    tavily_configured = _server_has_key("TAVILY_API_KEY")
    _init_live_state(live_configured, tavily_configured)
    page = st.navigation(
        {
            "Start here": [
                st.Page(
                    _page_about,
                    title="What is FabAgent?",
                    icon=":material/info:",
                    url_path="about",
                ),
                st.Page(
                    _page_models,
                    title="Models and tools",
                    icon=":material/hub:",
                    url_path="models",
                ),
            ],
            "Try it": [
                st.Page(
                    _page_run,
                    title="Run a troubleshooting case",
                    icon=":material/play_circle:",
                    url_path="run",
                    default=True,
                ),
            ],
            "Evidence": [
                st.Page(
                    _page_performance,
                    title="FabAgent vs naive LLMs",
                    icon=":material/compare_arrows:",
                    url_path="performance",
                ),
                st.Page(
                    _page_contact,
                    title="Contact",
                    icon=":material/mail:",
                    url_path="contact",
                ),
            ],
        },
        position="sidebar",
        expanded=True,
    )
    _render_sidebar(live_configured, tavily_configured)
    page.run()


if __name__ == "__main__":
    main()
