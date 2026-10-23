"""FabAgent technician dashboard (W6).

Wrap the product entry point ``analyze_csv`` with a glass-box UI: choose a
synthetic demo sample or upload a CSV, add an engineer note, and see the
triage, the scoped evidence, the configuration-authored candidate, the
Python-gated verdict, the model narrative (labelled as not gated), and the
suggested action label + explanation. Experimental fallback runs also show the
unverified mapping and a reviewable draft config to save.

Demo mode is key-free and deterministic. Live mode needs ``NEBIUS_API_KEY`` in
the environment. The app never prints an API key or a raw model completion.
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import streamlit as st

from src.analyze import RunResult, analyze_csv
from src.demo import (
    ExperimentalEchoTransport,
    offline_engine_factory,
    offline_mapping_factory,
)
from src.model_config import ModelConfigurationError
from src.ui import config_promotion, presentation

_DISCLAIMER = (
    "FabAgent is an evidence-gated troubleshooting copilot. It suggests a typed "
    "next step; a human decides. Results are tied to the configured "
    "relationships and are not field validation."
)

_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "samples"


@dataclass(frozen=True, slots=True)
class DemoCase:
    filename: str
    description: str
    note: str


_DEMO_CASES: dict[str, DemoCase] = {
    "Flowcool excursion (supported)": DemoCase(
        filename="flowcool_supported.csv",
        description=(
            "Both configured flowcool channels move. The gate supports the "
            "configured candidate and recommends inspecting the component."
        ),
        note="Flowcool loop excursion during the RF step.",
    ),
    "Flowcool flat (inconclusive)": DemoCase(
        filename="flowcool_inconclusive.csv",
        description=(
            "The configured channels are present but neither is anomalous. "
            "The gate abstains and asks for the missing evidence."
        ),
        note="Flowcool loop looks normal; check whether anything moved.",
    ),
    "RF contradiction (vetoed)": DemoCase(
        filename="rf_contradiction.csv",
        description=(
            "Sensor 17 is anomalous while every configured corroborating "
            "channel is nominal. The contradiction veto wins over the model's "
            "arc story."
        ),
        note="RF reflectometer excursion on Chamber B.",
    ),
    "Unknown tool export (experimental)": DemoCase(
        filename="unknown_tool.csv",
        description=(
            "No configured schema matches. The experimental fallback proposes "
            "an unverified mapping, marks the evidence, and offers a draft "
            "config to review and save."
        ),
        note="New tool export; no configured schema yet.",
    ),
}


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


def _render_summary(result: RunResult) -> None:
    summary = presentation.summarize(result)
    _callout(presentation.outcome_tone(result.outcome), f"**{summary.outcome_label}**")
    st.markdown(f"### Suggested next step: {summary.action_label}")
    st.write(summary.explanation)
    if summary.detail:
        st.caption(summary.detail)
    top = st.columns(4)
    top[0].metric("Track", "Analysis" if summary.analysis_performed else "No analysis")
    top[1].metric("Model call", "yes" if summary.model_called else "no")
    top[2].metric("Evidence", summary.evidence_count)
    top[3].metric("Hypotheses", summary.hypothesis_count)
    st.caption(f"Mode: {summary.mode_label} · {summary.triage}")


def _render_stepper(result: RunResult) -> None:
    """Show the five stages explicitly, so the gate is not a black box."""
    selection = result.selection
    hypotheses = result.output.hypotheses
    status = hypotheses[0].status.value if hypotheses else "no verdict"
    steps = [
        (
            "1 · Triage",
            selection.scenario_name if selection is not None else "no schema",
        ),
        ("2 · Scope", f"{len(result.evidence)} records"),
        ("3 · Model", "called" if result.model_called else "not called"),
        ("4 · Python gate", status),
        (
            "5 · Action",
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


def _render_conclusion(result: RunResult) -> None:
    output = result.output
    st.subheader("Gated conclusion")
    if not output.hypotheses:
        st.caption(
            "No gated hypothesis was produced for this run. The route and "
            "action above are the result."
        )
    for hypothesis in output.hypotheses:
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
        except config_promotion.DraftConfigError as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Saved {saved.name}. Re-running with these columns now uses the "
                "deterministic safe path."
            )


def _render_result(result: RunResult) -> None:
    _render_summary(result)
    _render_stepper(result)
    if result.mapping is not None:
        _render_mapping(result)
    _render_conclusion(result)
    _render_evidence(result)
    st.divider()
    st.caption(_DISCLAIMER)


def _run_analysis(data: bytes, note: str, *, demo_mode: bool) -> RunResult | None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "upload.csv"
        path.write_bytes(data)
        try:
            with st.spinner("Triaging, scanning evidence, and running the gate..."):
                if demo_mode:
                    transport = ExperimentalEchoTransport()
                    return analyze_csv(
                        path,
                        note,
                        engine_factory=offline_engine_factory(transport),
                        mapping_factory=offline_mapping_factory(transport),
                    )
                return analyze_csv(path, note)
        except ModelConfigurationError as exc:
            st.error(str(exc))
        except Exception:  # a UI boundary must not leak a traceback to the page
            st.error(
                "The analysis could not run. Check the file and the model "
                "configuration, then try again."
            )
    return None


def _render_sample_runner(demo_mode: bool) -> None:
    choice = st.selectbox("Demo sample", list(_DEMO_CASES))
    case = _DEMO_CASES[choice]
    st.info(case.description)
    note = st.text_input("Engineer note (optional)", value=case.note)
    if st.button("Run this sample", type="primary"):
        try:
            data = (_SAMPLE_DIR / case.filename).read_bytes()
        except OSError:
            st.error(f"Sample {case.filename} is not available in this checkout.")
        else:
            st.session_state["result"] = _run_analysis(
                data, note, demo_mode=demo_mode
            )


def _render_upload_runner(demo_mode: bool) -> None:
    uploaded = st.file_uploader("Tool export (CSV)", type=["csv"])
    note = st.text_area(
        "Engineer note (optional)",
        placeholder=(
            "e.g. RF reflectometer excursion on Chamber B, wafer edge thinning"
        ),
        max_chars=1000,
    )
    if st.button("Analyze", type="primary", disabled=uploaded is None):
        if uploaded is not None:
            st.session_state["result"] = _run_analysis(
                uploaded.getvalue(), note, demo_mode=demo_mode
            )


def main() -> None:
    st.set_page_config(page_title="FabAgent", page_icon="\U0001f52c", layout="wide")
    st.title("FabAgent")
    st.caption(
        "Evidence-gated troubleshooting copilot: choose a sample or upload a "
        "tool CSV, then review the triage, evidence, gated conclusion, and next "
        "step."
    )
    with st.sidebar:
        st.header("About this run")
        demo_mode = st.toggle(
            "Demo mode (no API key)",
            value=True,
            help=(
                "Demo mode uses a deterministic local transport that cites the "
                "evidence it receives. The Python gate is the production gate."
            ),
        )
        if demo_mode:
            st.success("Demo mode is on: no provider key is needed.")
        else:
            st.warning(
                "Live mode calls the configured Nebius model. Set "
                "`NEBIUS_API_KEY` in the environment."
            )
        st.write(
            "The deterministic safe path runs first. Only when no configured "
            "tool schema matches does the flow fall back to the unverified "
            "experimental mapping."
        )
        st.caption(
            "The key is never displayed, logged, or stored. Demo samples are "
            "synthetic and are not field validation."
        )
        st.caption(_DISCLAIMER)

    st.subheader("1. Choose an input")
    source = st.radio(
        "Input source",
        ["Demo sample", "Upload my own CSV"],
        horizontal=True,
    )
    st.subheader("2. Run the gate")
    if source == "Demo sample":
        _render_sample_runner(demo_mode)
    else:
        _render_upload_runner(demo_mode)

    result = st.session_state.get("result")
    if isinstance(result, RunResult):
        st.divider()
        _render_result(result)


if __name__ == "__main__":
    main()
