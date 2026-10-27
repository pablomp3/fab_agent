"""FabAgent technician dashboard (W6).

The dashboard is deliberately a glass box: it shows the input preview, the
engineer-controlled tool configuration, the scoped evidence, the model
explanation (clearly labelled as not used for the decision), the Python-owned
verdict and action, and optional external references. It never prints an API
key or a raw model completion.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

import streamlit as st
import yaml

from src.analyze import RunResult, analyze_csv
from src.config_loader import load_relations
from src.core.progress import STAGE_ORDER, ProgressState
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
from src.ui.presentation import (
    GLOSSARY,
)

# Do not reload ``presentation`` here. Streamlit reruns this script, but
# reloading a module that imports new schema classes can fail while an older
# ``src.schemas.models`` is still cached in a running server. Restart the server
# after changing imported modules.

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "ui"
_ABOUT_DOC = _DOCS / "about.md"
_MODELS_DOC = _DOCS / "models.md"
_PERFORMANCE_DOC = _DOCS / "performance.md"
_CONTACT_DOC = _DOCS / "contact.md"
_VERDICTS_DOC = _DOCS / "verdicts.md"
_YAML_DOC = _DOCS / "yaml_guide.md"
_RESULTS_DIR = (
    Path(__file__).resolve().parents[2] / "benchmarks" / "evaluator" / "results"
)
_BENCHMARK_SUMMARY_GLOB = "naive_llm/*/summary.json"

_BEHAVIOR_LABELS = {
    "supported": "Fault pattern present",
    "inconclusive": "Nominal pattern",
    "contradiction": "One sensor only (contradiction)",
}

# The one-click demo should show the product succeeding, not only abstaining.
# The public TEP feed case is a real benchmark case with a confirmed result.
RECOMMENDED_DEMO_KEY = "tep_feed_supported"

_STAGE_LABELS = {
    "read": "Read the CSV — load the engineer's tool export",
    "triage": ("Match tool configuration — find the YAML that describes these columns"),
    "mapping": (
        "Draft column mapping with Nemotron — for unknown tools (experimental)"
    ),
    "duckdb": "Scan the data — compute statistics per column (DuckDB)",
    "python": "Run safety checks — check for abnormal, missing, or conflicting data",
    "model": "Nemotron explanation — plain-language summary (never decides)",
    "gate": "Python safety check — combine evidence and select next step",
    "tavily": "Web references (Tavily) — leads when data is not reliable",
}

_STAGE_ICONS = {
    "pending": ":gray[:material/radio_button_unchecked:]",
    "running": ":blue[:material/autorenew:]",
    "done": ":green[:material/check_circle:]",
    "skipped": ":orange[:material/skip_next:]",
    "failed": ":red[:material/error:]",
}

_STAGE_BADGES = {
    "pending": ":gray[WAITING]",
    "running": ":blue[RUNNING]",
    "done": ":green[DONE]",
    "skipped": ":orange[SKIPPED]",
    "failed": ":red[FAILED]",
}

_ROLE_LABELS = {
    "pressure_candidate": "Possible pressure sensor",
    "temperature_candidate": "Possible temperature sensor",
    "flow_candidate": "Possible flow sensor",
    "rf_power_candidate": "Possible RF power sensor",
    "actuator_candidate": "Possible actuator",
    "candidate_sensor": "Possible sensor",
}


def _table(rows: Sequence[Mapping[str, object]]) -> None:
    st.markdown(presentation.markdown_table([dict(row) for row in rows]))


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


def _load_local_env() -> None:
    """Read the repository .env for local runs without overriding real env vars."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and value:
            os.environ.setdefault(name, value)


_MINIMAL_TOOL_MODEL = """\
tool:
  name: loader_check
  label: Loader check
baseline:
  mode: lead_in
  rows: 1
signals:
  - {name: value, label: Value, unit: null, alert_at: 3.5}
checks: []
"""


def _v2_loader_ready() -> bool:
    """True when the running process can load the current tool model.

    Streamlit caches imported modules. A server started before the current
    loader keeps the old function and reports a cryptic version error. Test the
    real code path instead of inspecting source text, and include the promotion
    validator because it imports its own loader reference.
    """
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tool.yaml"
            path.write_text(_MINIMAL_TOOL_MODEL, encoding="utf-8")
            load_relations(path)
        config_promotion.validate_draft_yaml(_MINIMAL_TOOL_MODEL)
    except Exception:
        return False
    return True


def _model_label() -> str:
    """Return the plain role name, never a model ID or provider detail."""
    try:
        route = load_model_route(DEFAULT_MODELS_CONFIG, "SYNTHESIS")
    except ModelConfigurationError:
        return "Nemotron cause finder (server-side)"
    return f"Nemotron {route.role.casefold()} (server-side)"


_DOT_BLOCK = re.compile(r"```dot\n(.*?)```", re.DOTALL)


def _render_flow_diagram(*, detailed: bool = False) -> None:
    """A compact, product-level picture of the evidence-gated pipeline."""
    st.html(
        """
<style>
.fa-thesis {
  border-left: 4px solid #0B6E99;
  background: #F3F6F8;
  border-radius: 10px;
  padding: 10px 14px;
  margin: 0.2rem 0 0.9rem;
  color: #1F2933;
  font-size: 0.98rem;
}
.fa-flow {
  display: flex;
  align-items: stretch;
  gap: 10px;
  flex-wrap: wrap;
  margin: 0.2rem 0 0.6rem;
}
.fa-step {
  flex: 1 1 190px;
  min-width: 175px;
  background: #F3F6F8;
  border: 1px solid #DCE6EC;
  border-radius: 14px;
  padding: 14px 16px;
}
.fa-step h4 {
  margin: 0 0 4px;
  color: #0B6E99;
  font-size: 0.72rem;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.fa-step p {
  margin: 0;
  color: #1F2933;
  font-size: 0.93rem;
  line-height: 1.35;
}
.fa-step small {
  display: block;
  margin-top: 6px;
  color: #52606D;
  font-size: 0.79rem;
  line-height: 1.3;
}
.fa-step.model { background: #E8F3F8; border-color: #C7E2EE; }
.fa-step.core { background: #0B6E99; border-color: #0B6E99; }
.fa-step.core h4, .fa-step.core p, .fa-step.core small { color: #FFFFFF; }
.fa-step.output { background: #EAF6EF; border-color: #BFE3CD; }
.fa-arrow {
  align-self: center;
  color: #0B6E99;
  font-size: 1.35rem;
  font-weight: 700;
  padding: 0 2px;
}
.fa-caption { color: #52606D; font-size: 0.82rem; margin: 0.1rem 0 0.7rem; }
</style>
<div class="fa-thesis">
  <b>Nemotron proposes.</b> Python checks. The engineer decides.
</div>
<div class="fa-flow">
  <div class="fa-step">
    <h4>1 · Input</h4>
    <p><b>CSV telemetry</b></p>
    <small>Plus an optional tool model: signals, normal reference, fault checks.</small>
  </div>
  <div class="fa-arrow">→</div>
  <div class="fa-step model">
    <h4>2 · Helpers</h4>
    <p><b>NVIDIA Nemotron</b></p>
    <small>Maps columns, proposes causes, challenges the leading cause.</small>
    <small><b>Tavily</b> adds public leads only when the data is uncertain.</small>
  </div>
  <div class="fa-arrow">→</div>
  <div class="fa-step core">
    <h4>3 · Decision</h4>
    <p><b>Python + DuckDB</b></p>
    <small>Baseline → evidence IDs → coverage → contradictions →
    one safe action.</small>
  </div>
  <div class="fa-arrow">→</div>
  <div class="fa-step output">
    <h4>4 · Output</h4>
    <p><b>One of six results</b></p>
    <small>A plain-language next step, an audit trail, and a human confirmation.</small>
  </div>
</div>
<div class="fa-caption">
  The model never receives raw telemetry. It sees a bounded evidence summary
  under 2 KB; every citation is re-resolved by Python.
</div>
"""
    )
    if detailed:
        st.html(
            """
<div class="fa-flow">
  <div class="fa-step">
    <h4>Deterministic core</h4>
    <p><b>baseline → evidence → coverage → checks → gate → action</b></p>
    <small>A contradiction is a hard veto. Missing data is evidence,
    not silence.</small>
  </div>
  <div class="fa-step model">
    <h4>Model boundary</h4>
    <p><b>propose · challenge · explain</b></p>
    <small>The model may add a narrative or a disconfirming test.
    It cannot upgrade a result.</small>
  </div>
  <div class="fa-step output">
    <h4>Proof surface</h4>
    <p><b>evidence IDs + audit</b></p>
    <small>Every result is traceable to the rows, the statistic, and the
    configured check.</small>
  </div>
</div>
"""
        )


def _render_markdown_file(path: Path) -> None:
    """Render a docs page; ```dot blocks become native Graphviz diagrams."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        st.error(f"Could not load {path.name}: {exc}")
        return
    position = 0
    for match in _DOT_BLOCK.finditer(text):
        st.markdown(text[position : match.start()])
        st.graphviz_chart(  # pyright: ignore[reportUnknownMemberType]
            match.group(1), use_container_width=True
        )
        position = match.end()
    st.markdown(text[position:])


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
    visible_rows = [
        {column: row.get(column, "") for column in columns} for row in rows[:5]
    ]
    col_count = len(columns)
    st.caption(
        f"Raw telemetry: {col_count} columns · first {len(visible_rows)} rows preview"
    )
    if not rows:
        st.info("The file has a header but no data rows.")
        return
    _table(visible_rows)
    notes = dict(column_notes)
    with st.expander("What do these columns mean?", expanded=False):
        if notes:
            guide = [
                {
                    "column": column,
                    "first value": rows[0].get(column, ""),
                    "what it means": notes.get(
                        column,
                        "Recorded sensor channel or machine parameter in this run.",
                    ),
                }
                for column in columns
            ]
            _table(guide)
        else:
            guide = [
                {
                    "column": column,
                    "first value": rows[0].get(column, ""),
                    "what it means": (
                        "No plain-language note for this upload; check the tool "
                        "manual or known export specification."
                    ),
                }
                for column in columns
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


def _extract_telemetry_series(
    data: bytes,
    target_signals: list[str] | None = None,
    limit: int = 200,
) -> dict[str, list[float]] | None:
    """Extract sample time-series vectors from CSV data for quick charting."""
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig", errors="ignore")))
        headers = next(reader, None)
        if not headers:
            return None
        candidate_cols: list[str] = []
        if target_signals:
            candidate_cols = [c for c in target_signals if c in headers][:3]
        if not candidate_cols:
            candidate_cols = [c for c in headers if c.lower() != "time"][:2]
        if not candidate_cols:
            return None
        indices = [headers.index(c) for c in candidate_cols]
        series: dict[str, list[float]] = {c: [] for c in candidate_cols}
        rows = list(reader)
        step = max(1, len(rows) // limit)
        for row in rows[::step]:
            for col_name, idx in zip(candidate_cols, indices, strict=True):
                if idx < len(row):
                    try:
                        val = float(row[idx])
                        series[col_name].append(val)
                    except ValueError:
                        pass
        if any(len(vals) > 0 for vals in series.values()):
            return series
    except Exception:
        return None
    return None


def _baseline_text(scenario: object) -> str:
    baseline = getattr(scenario, "baseline", None)
    if baseline is None:
        return "Every row in the upload (legacy default)"
    mode = getattr(baseline, "mode", "")
    if mode == "lead_in":
        return f"First {getattr(baseline, 'rows', '?')} rows of the upload"
    if mode == "nominal_file":
        return "A separate saved normal reference file"
    if mode == "recipe_step":
        return "One normal reference per recipe step"
    return "Configured normal reference"


def _render_config_summary(
    config_path: Path,
    signal_notes: tuple[tuple[str, str], ...],
) -> None:
    try:
        relations = load_relations(config_path)
    except (OSError, ValueError) as exc:
        st.warning(f"The configuration could not be read: {exc}")
        return

    first_scenario = next(iter(relations.scenarios.values()), None)
    st.markdown(f"**Saved tool model:** `{relations.name}`")
    st.caption(f"Normal reference: {_baseline_text(first_scenario)}")

    notes = dict(signal_notes)
    threshold_rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for scenario in relations.scenarios.values():
        for signal in scenario.declared_signals or scenario.signals:
            if signal.name in seen:
                continue
            seen.add(signal.name)
            threshold = (
                f"{signal.robust_z_threshold:g}z"
                if signal.robust_z_threshold is not None
                else presentation.MISSING
            )
            description = relations.signal_labels.get(
                signal.name, notes.get(signal.name, "Sensor channel")
            )
            threshold_rows.append(
                {
                    "Channel": description,
                    "CSV column": signal.name,
                    "Alert level": threshold,
                }
            )
    if threshold_rows:
        st.caption("Signals this tool model watches:")
        _table(threshold_rows)

    check_rows: list[dict[str, object]] = []
    for scenario in relations.scenarios.values():
        labels = relations.signal_labels
        primary = [
            labels.get(signal, signal)
            for signal in sorted(scenario.predicate_config.primary_signals)
        ]
        stay_normal = [
            labels.get(signal, signal)
            for signal in sorted(
                scenario.predicate_config.forbidden_anomaly_signals
            )
        ]
        together = [
            labels.get(signal, signal)
            for signal in sorted(
                scenario.predicate_config.corroboration_signals
            )
        ]
        check_rows.append(
            {
                "Fault check": scenario.candidate.claim,
                "Signals that must move": ", ".join(primary) or presentation.MISSING,
                "Signals that should move together": ", ".join(together)
                or presentation.MISSING,
                "Signals that must stay normal": ", ".join(stay_normal)
                or presentation.MISSING,
                "Next step": presentation.action_label(
                    scenario.supported_action
                ),
            }
        )
    if check_rows:
        st.caption("What counts as a fault:")
        _table(check_rows)
    else:
        st.caption("No fault check is saved yet. The next run stays Unknown Machine.")


def _render_config_editor(
    default_yaml: str | None,
    *,
    key: str,
    default_use: bool,
    config_path: Path | None = None,
    signal_notes: tuple[tuple[str, str], ...] = (),
) -> tuple[str | None, bool]:
    """Return ``(yaml_text, auto_detect)`` for the run.

    The normal view is a readable summary. The raw YAML is an advanced,
    engineer-only surface; a first-time user should never have to read it.
    """
    if default_yaml is None:
        st.caption(
            "No pre-configured tool model matches this tool. FabAgent will use "
            "AI-assisted draft mapping (Auto mode)."
        )
        return None, True

    if config_path is not None:
        _render_config_summary(config_path, signal_notes)
    else:
        st.caption(
            "No saved tool model for this upload. FabAgent will use Auto mode "
            "and guess the columns. You can open Advanced to provide one."
        )

    advanced = st.toggle(
        "Advanced: edit the tool model YAML",
        value=False,
        key=f"{key}_advanced",
        help=(
            "Only change this if you are the engineer who owns this tool model. "
            "The normal view above is enough for a demo."
        ),
    )
    if not advanced:
        if config_path is None:
            return None, True
        use = st.checkbox(
            "Use this tool model for the run",
            value=default_use,
            key=f"{key}_use",
        )
        return (default_yaml, False) if use else (None, True)

    st.caption(
        "Raw YAML for an engineer. Unknown keys or a bad path fail with the "
        "exact location; the run uses this text directly."
    )
    text_key = f"{key}_yaml_text"
    source_key = f"{key}_yaml_source"
    if st.session_state.get(source_key) != default_yaml:
        # A new case or generated file replaces the saved draft, but an edit in
        # the same case is preserved across reruns.
        st.session_state[source_key] = default_yaml
        st.session_state[text_key] = default_yaml
    reload_col, download_col = st.columns([1, 1])
    if reload_col.button(
        "Reload saved YAML",
        key=f"{key}_yaml_reload",
        use_container_width=True,
        help="Replace the editor with the saved tool model.",
    ):
        st.session_state[text_key] = default_yaml
        st.rerun()
    download_col.download_button(
        "Download current YAML",
        data=st.session_state.get(text_key, default_yaml),
        file_name="tool_model.yaml",
        mime="text/yaml",
        key=f"{key}_yaml_download",
        use_container_width=True,
    )
    text = st.text_area(
        "Tool model YAML",
        height=420,
        key=text_key,
        placeholder="Paste or edit the tool model here…",
        help=(
            "Signals, normal reference, and checks live here. Add or remove "
            "lines after reading the comments."
        ),
    )
    if not text.strip() and default_yaml.strip():
        # A stale widget state must never leave a blank editor on screen.
        st.session_state[text_key] = default_yaml
        st.rerun()
    with st.expander("What the YAML means (advanced)", expanded=False):
        _render_markdown_file(_YAML_DOC)
    st.caption(
        "Alert level default is 3.5 robust z-scores. Lower = more sensitive; "
        "higher = stricter."
    )
    use = st.checkbox(
        "Use this tool model for the run",
        value=default_use,
        key=f"{key}_use",
    )
    if not use:
        return None, True
    return text, False


def _tavily_progress_text(result: RunResult) -> str:
    status = result.external_search_status
    if status == "completed":
        return f"{result.external_search_count} reference(s)"
    if status == "not_configured":
        return "skipped — no server key"
    if status == "not_needed":
        return "skipped — safe result did not require external lookup"
    if status == "unavailable":
        return "failed — search was unavailable"
    if status == "disabled":
        return "skipped — disabled in sidebar"
    return "skipped"


def _tavily_progress_state(result: RunResult) -> str:
    if result.external_search_status == "completed":
        return "done"
    if result.external_search_status == "unavailable":
        return "failed"
    return "skipped"


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
        badge = _STAGE_BADGES.get(state, _STAGE_BADGES["pending"])
        title, _, detail = label.partition(" — ")
        if state == "pending":
            text = f":gray[{title}]"
        elif state == "skipped":
            text = f":orange[{title}]"
        else:
            text = f"**{title}**"
        if detail:
            text += f" :gray[— {detail}]"
        lines.append(f"{icon} {badge} {text}")
    return "\n\n".join(lines)


def _resolve_baseline_paths(
    config_yaml: str, config_path: Path | None
) -> str:
    """Make a v2 ``baseline.file`` absolute before the temp-file run.

    The editor passes YAML text to a temporary directory, so a path authored
    relative to the saved config would otherwise resolve against that temp
    directory. The displayed YAML keeps its original relative path.
    """
    if config_path is None:
        return config_yaml
    try:
        raw: object = yaml.safe_load(config_yaml)
    except yaml.YAMLError:
        return config_yaml
    if not isinstance(raw, dict):
        return config_yaml
    data = cast(dict[str, object], raw)
    if data.get("version") not in {None, 2}:
        return config_yaml
    baseline_raw = data.get("baseline")
    if not isinstance(baseline_raw, dict):
        return config_yaml
    baseline = cast(dict[str, object], baseline_raw)
    if baseline.get("mode") != "nominal_file":
        return config_yaml
    file_text = baseline.get("file")
    if not isinstance(file_text, str) or Path(file_text).is_absolute():
        return config_yaml
    baseline["file"] = str((config_path.parent / file_text).resolve())
    return yaml.safe_dump(data, sort_keys=False)


def _prepare_result_context(context: str) -> None:
    """Drop a result that belongs to a different case or input source."""
    if st.session_state.get("result_context") != context:
        st.session_state.pop("result", None)
        st.session_state["result_context"] = context


def _run_analysis(
    data: bytes,
    note: str,
    *,
    demo_mode: bool,
    config_yaml: str | None,
    auto_detect: bool,
    label: str,
    use_tavily: bool,
    context: str,
    config_path: Path | None = None,
) -> RunResult | None:
    original_config_yaml = config_yaml
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "input.csv"
            path.write_bytes(data)
            search_dir: Path | None = None
            if not auto_detect and config_yaml is not None:
                config_yaml = _resolve_baseline_paths(
                    config_yaml, config_path
                )
                config_promotion.validate_draft_yaml(config_yaml)
                config_dir = root / "config"
                config_dir.mkdir()
                (config_dir / "tool.yaml").write_text(config_yaml, encoding="utf-8")
                search_dir = config_dir
            steps: dict[str, ProgressState] = {}
            search_enabled = use_tavily or not _server_has_key("TAVILY_API_KEY")
            with st.status("Running FabAgent Analysis...", expanded=True) as status:
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
                    status.update(label="Run failed", state="error", expanded=True)
                    raise
                markdown_text = _progress_markdown(steps, result=result)
                checklist.markdown(markdown_text)
                status.update(
                    label="Analysis complete",
                    state="complete",
                    expanded=True,
                )
                st.session_state["result_steps_markdown"] = markdown_text
            st.session_state["result_mode"] = "offline" if demo_mode else "live"
            st.session_state["result_label"] = label
            st.session_state["result_context"] = context
            st.session_state["result_config_yaml"] = original_config_yaml
            st.session_state["last_csv_bytes"] = data
            return result
    except config_promotion.DraftConfigError as exc:
        st.error(str(exc))
    except ModelConfigurationError as exc:
        st.error(
            f"{exc}. The deployment must provide the model credential in its "
            "server environment."
        )
    except Exception:
        st.error(
            "The analysis could not run. Check the file and configuration, "
            "then try again."
        )
    return None


def _model_explanation_available(result: RunResult) -> bool:
    """True when a usable model narrative or unverified cause came back."""
    return result.model_called and (
        any(
            item.model_narrative is not None for item in result.output.hypotheses
        )
        or any(
            item.proposed_by_model for item in result.output.differential
        )
    )


def _render_answer_card(result: RunResult) -> None:
    """Render the prominent, plain-English answer card at the top of the result."""
    card = presentation.answer_card(result)
    with st.container(border=True):
        col_badge, col_mode = st.columns([3, 1])
        col_badge.markdown(f"### {card.confidence_badge}")
        mode = str(st.session_state.get("result_mode", "unknown"))
        if mode == "offline":
            col_mode.caption(":orange[Offline demo fixture]")
        elif _model_explanation_available(result):
            col_mode.caption(":green[Live Nemotron]")
        else:
            col_mode.caption(":orange[AI explanation unavailable]")

        _callout(
            card.confidence_tone,
            f"**{card.confidence_label}** — {card.confidence_help}",
        )
        st.markdown(f"#### 💡 {card.headline}")

        with st.container(border=True):
            st.markdown(f"**Recommended Next Step:** {card.action_label}")
            st.caption(card.action_explanation)

        challenge = result.output.challenge
        if challenge is not None:
            if challenge.downgraded:
                st.caption(
                    ":orange[AI challenge: the disconfirming test was not met; "
                    "the result was downgraded.]"
                )
            elif challenge.status.value == "checked":
                st.caption(
                    ":green[AI challenge: checked. The disconfirming test named "
                    "a signal and Python verified it.]"
                )
            else:
                st.caption(
                    ":gray[AI challenge: unavailable; the deterministic result "
                    "is unchanged.]"
                )


def _render_why_summary(result: RunResult) -> None:
    """Render clear bullet points explaining which sensors moved and why."""
    st.markdown("### 🔍 Telemetry Findings: Why we think this")

    anomalies = [
        e for e in result.evidence if e.kind.value == "SENSOR_ANOMALY" and e.signal
    ]
    nominals = [
        e for e in result.evidence if e.kind.value == "SENSOR_NOMINAL" and e.signal
    ]
    missing = [
        e for e in result.evidence if e.kind.value == "MISSING_CHANNEL" and e.signal
    ]

    col_bullets, col_chart = st.columns([1, 1])
    with col_bullets:
        if anomalies:
            st.markdown("**Unusual signals (outside their alert level):**")
            for e in anomalies:
                val_str = presentation.z_text(e.value)
                threshold = (
                    "no alert level configured"
                    if e.threshold is None
                    else f"alert level: {e.threshold:.2f}z"
                )
                name = presentation.signal_label(result, e.signal)
                st.write(
                    f"- :red[**{name}**]: **{val_str}** peak deviation "
                    f"({threshold})"
                )
        if nominals:
            st.markdown("**Signals that stayed normal:**")
            for e in nominals[:3]:
                val_str = presentation.z_text(e.value)
                threshold = (
                    "below the configured level"
                    if e.threshold is None
                    else f"safe \u2264 {e.threshold:.2f}z"
                )
                name = presentation.signal_label(result, e.signal)
                st.write(
                    f"- :green[**{name}**]: **{val_str}** peak deviation "
                    f"({threshold})"
                )
            if len(nominals) > 3:
                st.caption(f"...and {len(nominals) - 3} other signal(s) stayed quiet")
        if missing:
            st.markdown("**Missing signals:**")
            for e in missing:
                name = presentation.signal_label(result, e.signal)
                st.write(f"- :orange[**{name}**]: absent in the CSV export")
        if not anomalies and not nominals and not missing:
            st.info("No sensor channels were evaluated in this run.")

    with col_chart:
        chart_data = {
            presentation.signal_label(result, e.signal): min(
                abs(e.value or 0.0), presentation.DISPLAY_Z_CAP
            )
            for e in result.evidence
            if e.signal and e.value is not None
        }
        if chart_data:
            st.caption(
                "Peak deviation against each signal's alert level. Bars are "
                f"clipped at {presentation.DISPLAY_Z_CAP:g}z; raw values are in Audit."
            )
            st.bar_chart(chart_data)  # pyright: ignore[reportUnknownMemberType]


def _render_differential(result: RunResult) -> None:
    """Show every saved check as a plain-language differential row."""
    rows = presentation.differential_rows(
        result.output,
        result.evidence,
        presentation.signal_labels(result),
    )
    if not rows:
        return
    with st.container(border=True):
        st.markdown("### ⚖️ Possible causes")
        if result.output.alternative_count:
            st.caption(
                f"{result.output.alternative_count + 1} saved checks were "
                "confirmed; the leading cause is shown first."
            )
        else:
            st.caption(
                "Every saved check is scored. A check is never confirmed by a "
                "weighted score; the table shows what moved and what contradicted it."
            )
        _table([asdict(row) for row in rows])


def _render_what_else_moved(result: RunResult) -> None:
    """Surface every declared signal that no saved check explains."""
    rows = presentation.unexplained_rows(result)
    if not rows:
        return
    coverage = result.output.coverage
    large = list(coverage.unexplained_large) if coverage is not None else []
    with st.container(border=True):
        st.markdown("### 👀 What else moved")
        if large:
            st.caption(
                "These declared signals moved outside every saved check. Large "
                "unexplained movements prevent a bare **Fault Confirmed**."
            )
        else:
            st.caption(
                "These declared signals moved outside every saved check. They did "
                "not reach the large-anomaly limit, but nothing was hidden."
            )
        _table([asdict(row) for row in rows])


def _render_measurements_tab(result: RunResult) -> None:
    st.markdown("#### Checked Telemetry Measurements")
    summary = presentation.summarize(result)

    if result.mode == "safe":
        st.caption(
            f"**Configuration**: :green[Known machine] · "
            f"{summary.evidence_count} evidence records checked"
        )
    else:
        st.warning(
            "**Configuration**: :orange[Unknown machine] — AI generated a draft "
            "mapping below"
        )

    last_bytes = st.session_state.get("last_csv_bytes")
    if isinstance(last_bytes, bytes):
        eval_signals = [e.signal for e in result.evidence if e.signal]
        series = _extract_telemetry_series(last_bytes, target_signals=eval_signals)
        if series:
            labels = presentation.signal_labels(result)
            labelled = {
                labels.get(name, name): values for name, values in series.items()
            }
            st.caption("Telemetry time-series profile for evaluated sensor channels:")
            st.line_chart(labelled)  # pyright: ignore[reportUnknownMemberType]

    if not result.evidence:
        st.info("No evidence records were generated.")
        return

    raw_rows = presentation.evidence_rows(result.evidence)
    plain_rows: list[dict[str, object]] = [
        {
            "Status": r.status,
            "Signal": r.signal,
            "Peak deviation": r.how_unusual,
            "Alert level": r.alert_threshold,
            "Window": r.window,
            "Summary": r.summary,
        }
        for r in raw_rows
    ]
    _table(plain_rows)

    if result.output.required_next_checks:
        st.markdown("**Required next safety checks:**")
        for check in result.output.required_next_checks:
            st.write(f"- {check}")

    st.divider()
    st.markdown("### 🔍 Audit")
    st.caption(
        "Raw evidence IDs, internal statuses, model roles, and the challenge are "
        "kept here so the main result stays in plain language."
    )
    audit_rows: list[dict[str, object]] = [
        {
            "Evidence ID": r.evidence_id,
            "Raw status": r.raw_status,
            "Signal": r.signal,
            "Statistic": r.statistic,
            "Value": r.value,
            "Window": r.window,
            "Summary": r.summary,
        }
        for r in raw_rows
    ]
    _table(audit_rows)

    mode = str(st.session_state.get("result_mode", "unknown"))
    audit_summary: list[dict[str, object]] = [
        {"Audit item": "Model roles", "Value": presentation.model_role_text(result)},
        {
            "Audit item": "Evidence payload",
            "Value": presentation.model_payload_text(result),
        },
        {
            "Audit item": "Model transport",
            "Value": (
                "Offline fixture (no network call)"
                if mode == "offline"
                else ("Live model" if result.model_called else "Not called")
            ),
        },
        {
            "Audit item": "Unresolved citations",
            "Value": (
                ", ".join(presentation.unresolved_citations(result))
                or presentation.MISSING
            ),
        },
    ]
    _table(audit_summary)

    challenge_rows = presentation.challenge_audit_rows(result)
    if challenge_rows:
        st.markdown("**Challenge check (audit)**")
        _table(challenge_rows)
    else:
        st.caption("No challenge check was run for this result.")

    gated_rows = [
        asdict(row) for row in presentation.hypothesis_rows(result.output)
    ]
    if gated_rows:
        st.markdown("**Gated conclusion (audit)**")
        _table(gated_rows)

    if result.mapping is not None:
        _render_mapping(result)


def _render_ai_tab(result: RunResult) -> None:
    st.markdown("#### NVIDIA Nemotron AI Explanation")
    mode = str(st.session_state.get("result_mode", "unknown"))
    if mode == "offline":
        st.warning(
            "⚠️ This explanation was produced by a local offline fixture. "
            "The hosted demo uses live NVIDIA Nemotron when the server key is "
            "present; there is no user switch to turn the service off."
        )
    elif _model_explanation_available(result):
        st.success("✓ Live NVIDIA Nemotron (via Nebius Token Factory)")
    else:
        st.warning(
            "AI explanation unavailable for this run. The deterministic Python "
            "result above still applies."
        )

    st.caption(
        "Nemotron provides plain-language summaries for onboarding engineers. "
        "Python independently re-resolves and validates every citation; the "
        "model cannot override the result. Evidence IDs and unresolved citations "
        "are kept in the Audit section."
    )

    narratives = [
        h.model_narrative
        for h in result.output.hypotheses
        if h.model_narrative is not None
    ]
    narrative_rows: list[dict[str, object]] = [
        {
            "What the model said": item.claim,
            "What it thinks happened": item.failure_mode,
            "Why": item.mechanism,
        }
        for item in narratives
    ]
    if narrative_rows:
        _table(narrative_rows)
    else:
        st.info("No AI narrative was generated for this run.")

    cited = sum(len(item.cited_evidence) for item in narratives)
    unresolved = len(presentation.unresolved_citations(result))
    col1, col2 = st.columns(2)
    col1.metric("Evidence citations verified", cited)
    col2.metric("Unresolved citations flagged", unresolved)
    if unresolved:
        st.warning(
            "The model cited evidence IDs Python could not resolve. They are "
            "rejected by safety rules and listed in the Audit section."
        )


def _render_web_tab(result: RunResult) -> None:
    st.markdown("#### Troubleshooting Leads (Tavily Search)")
    st.caption(
        "Tavily web search runs only when telemetry is inconclusive, conflicting, "
        "or unconfigured. Leads are for human investigation and never alter the "
        "safety result."
    )

    if result.external_search_status == "not_needed":
        st.info(
            "External search skipped: The telemetry was consistent and supported "
            "a clear outcome, so external web search was not needed."
        )
        return
    if result.external_search_status == "not_configured":
        st.warning(
            "Tavily is not configured on this server. External references are skipped."
        )
        return

    if result.external_search_query:
        st.markdown(f"**Search query**: `{result.external_search_query}`")

    if result.output.external_sources:
        for source in result.output.external_sources:
            with st.container(border=True):
                title = source.title or "Industrial Troubleshooting Reference"
                st.markdown(f"🔗 **[{title}]({source.url})**")
                if source.snippet:
                    st.caption(source.snippet)
    else:
        st.info("No external references found.")


def _draft_with_check(
    draft_yaml: str,
    *,
    label: str,
    must_move: list[str],
    stay_normal: list[str],
    action: str,
) -> str:
    """Add one engineer-authored check to the model's draft tool model."""
    if not must_move:
        raise config_promotion.DraftConfigError(
            "Choose at least one signal that must move for this fault."
        )
    raw = cast(object, yaml.safe_load(draft_yaml))
    if not isinstance(raw, dict):
        raise config_promotion.DraftConfigError("The draft YAML is not an object.")
    data = cast(dict[str, object], raw)
    checks_raw = data.get("checks", [])
    if not isinstance(checks_raw, list):
        raise config_promotion.DraftConfigError("The draft checks field is not a list.")
    checks = cast(list[object], checks_raw)
    check_id = config_promotion.slugify_config_name(label)
    existing: set[str] = set()
    for item in checks:
        if isinstance(item, dict):
            entry = cast(dict[str, object], item)
            existing.add(str(entry.get("id")))
    suffix = 2
    base_id = check_id
    while check_id in existing:
        check_id = f"{base_id}_{suffix}"
        suffix += 1
    checks.append(
        {
            "id": check_id,
            "label": label,
            "kind": "equipment_fault",
            "must_be_unusual": [
                {"signal": signal, "direction": "any"} for signal in must_move
            ],
            "must_stay_normal": stay_normal,
            "action": action,
            "advice": "Review the named part before changing the recipe.",
        }
    )
    data["checks"] = checks
    return yaml.safe_dump(data, sort_keys=False)


def _render_mapping(result: RunResult) -> None:
    mapping = result.mapping
    if mapping is None:
        return
    st.divider()
    st.subheader("Unknown Machine: AI Draft Mapping")
    st.warning(
        "We do not recognise this machine. Nemotron read the column names and "
        "inferred candidate roles. Review the draft below before trusting."
    )
    mapping_rows = [
        {
            "Column": row.column,
            "Guessed role": _ROLE_LABELS.get(row.role_guess, "Possible sensor"),
            "Guessed unit": row.unit_guess,
        }
        for row in presentation.mapping_signal_rows(mapping)
    ]
    _table(mapping_rows)
    relationship_rows = [
        asdict(row) for row in presentation.mapping_relationship_rows(mapping)
    ]
    if relationship_rows:
        st.markdown("**Guessed relationships**")
        _table(relationship_rows)

    if not result.draft_yaml:
        return
    st.markdown(
        "**Draft tool model YAML** — review the columns and normal reference. "
        "A saved draft with no fault checks stays **Unknown Machine**."
    )
    st.code(result.draft_yaml, language="yaml")
    st.download_button(
        "Download draft configuration",
        data=result.draft_yaml,
        file_name="experimental_draft.yaml",
        mime="text/yaml",
    )
    columns = [row.column for row in presentation.mapping_signal_rows(mapping)]
    with st.form("promote_draft"):
        name = st.text_input("Configuration name", value="experimental_draft")
        check_label = st.text_input(
            "Fault check name",
            value="Reviewed fault pattern",
            help="The engineer's name for the pattern, not a model guess.",
        )
        must_move = st.multiselect(
            "Signals that must move",
            columns,
            default=columns[:1],
            help="All of these must be unusual for the check to confirm.",
        )
        stay_normal = st.multiselect(
            "Signals that must stay normal",
            [column for column in columns if column not in must_move],
            help="If one of these moves, the result is Sensors Disagree.",
        )
        action = st.selectbox(
            "Next step",
            [
                "INSPECT_COMPONENT",
                "ESCALATE_TO_ENGINEER",
                "CONTINUE_MONITORING",
            ],
            format_func=lambda value: value.replace("_", " ").title(),
        )
        overwrite = st.checkbox("Replace existing config with this name")
        save_draft = st.form_submit_button("Save draft without a check")
        save_with_check = st.form_submit_button("Save with this fault check")

    if save_draft or save_with_check:
        try:
            yaml_text = result.draft_yaml
            if save_with_check:
                yaml_text = _draft_with_check(
                    result.draft_yaml,
                    label=check_label,
                    must_move=list(must_move),
                    stay_normal=list(stay_normal),
                    action=str(action),
                )
            saved = config_promotion.save_draft_config(
                yaml_text, name, overwrite=overwrite
            )
        except (config_promotion.DraftConfigError, OSError) as exc:
            st.error(str(exc))
        else:
            if save_with_check:
                st.success(
                    f"Saved {saved.name} with a fault check. Re-run the same "
                    "upload: FabAgent will match this tool model, and the next "
                    "result is deterministic."
                )
            else:
                st.success(
                    f"Saved {saved.name}. It has no fault checks yet, so the next "
                    "run stays **Unknown Machine** until an engineer adds a check."
                )


def _render_result(result: RunResult) -> None:
    # 1. Answer Card at the very top (B2)
    _render_answer_card(result)

    # 2. Why we think this (C1, C4)
    _render_why_summary(result)

    # 3. Differential and coverage, below the result without hiding anomalies.
    _render_differential(result)
    _render_what_else_moved(result)

    # 4. Organized Tabs for deep dive
    tab_measurements, tab_ai, tab_web = st.tabs(
        [
            "📊 Measurements & Audit",
            "🤖 AI explanation (Nemotron)",
            "🌐 Web leads (Tavily)",
        ]
    )
    with tab_measurements:
        _render_measurements_tab(result)
    with tab_ai:
        _render_ai_tab(result)
    with tab_web:
        _render_web_tab(result)


def _render_demo_runner(demo_mode: bool, use_tavily: bool) -> None:
    st.markdown("### Step 1 — Choose a prepared dataset")
    choice = st.selectbox(
        "Prepared dataset",
        list(DEMO_CASES),
        format_func=lambda key: DEMO_CASES[key].label,
        key="demo_choice",
        help="Select a real public dataset or synthetic twin scenario.",
    )
    case: DemoCase = DEMO_CASES[choice]
    context = f"demo:{case.key}"
    _prepare_result_context(context)

    if "Fault Confirmed" in case.label:
        st.markdown(
            "**:red[🔴 Fault Confirmed]** — *Simulates an active equipment failure.*"
        )
    elif "Regular Behavior" in case.label:
        st.markdown(
            "**:green[🟢 Regular Behavior]** — *Simulates normal healthy machine"
            " operation.*"
        )
    elif "Sensors Disagree" in case.label:
        st.markdown(
            "**:orange[🟡 Sensors Disagree]** — *Simulates a"
            " sensor/instrumentation conflict.*"
        )
    elif "Data Incomplete" in case.label:
        st.markdown(
            "**:orange[⚠️ Data Incomplete]** — *Simulates an export with a required"
            " channel missing.*"
        )
    elif "Needs Review" in case.label:
        st.markdown(
            "**:orange[🟠 Needs Review]** — *Simulates a disturbance the saved"
            " checks do not explain.*"
        )
    else:
        st.markdown(
            "**:gray[⚪ Unknown Machine]** — *Simulates an unconfigured machine"
            " export.*"
        )
    st.caption(f"**Source**: {case.source}")
    st.markdown(f"**Expected outcome**: {case.expected}")
    st.info(case.description)
    _render_preview_from_path(case.csv_path, case.column_notes)

    default_yaml: str | None = None
    if case.config_path is not None:
        try:
            default_yaml = case.config_path.read_text(encoding="utf-8")
        except OSError as exc:
            st.error(f"The bundled config could not be read: {exc}")

    config_yaml = default_yaml
    auto_detect = False
    note = case.note

    with st.expander(
        "⚙️ Engineer settings, alert thresholds & notes (optional)",
        expanded=False,
    ):
        config_yaml, auto_detect = _render_config_editor(
            default_yaml,
            key=f"demo_{case.key}",
            default_use=True,
            config_path=case.config_path,
            signal_notes=case.signal_notes,
        )
        note = st.text_area(
            "Engineer note (optional context for Nemotron)",
            value=case.note,
            key=f"note_{case.key}",
            max_chars=1000,
            help=(
                "Context note sent to Nemotron; cannot change the Python safety result."
            ),
        )

    st.markdown("### Step 2 — Run the analysis")
    auto_run = bool(st.session_state.pop("auto_run_demo", False))
    run_clicked = st.button(
        "🚀 Run analysis on this dataset",
        type="primary",
        key=f"run_{case.key}",
        use_container_width=True,
    )
    if run_clicked or auto_run:
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
                context=context,
                config_path=case.config_path,
            )
    else:
        st.caption("The last run for this dataset is shown below.")


def _render_upload_runner(demo_mode: bool, use_tavily: bool) -> None:
    st.markdown("### Step 1 — Upload a CSV tool export")
    uploaded = st.file_uploader(
        "Tool export (CSV)",
        type=["csv"],
        help="Upload CSV telemetry with sensor columns.",
    )
    context = f"upload:{uploaded.name}" if uploaded is not None else "upload:none"
    _prepare_result_context(context)
    preview_data: bytes | None = None
    if uploaded is not None:
        try:
            preview_data = uploaded.getvalue()
            preview_text = preview_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            st.error("The uploaded CSV is not valid UTF-8 text.")
        else:
            _render_preview_from_text(preview_text)
    else:
        st.caption("Upload a factory telemetry CSV to preview and analyze.")

    config_yaml = config_promotion.CUSTOM_TOOL_MODEL_TEMPLATE
    auto_detect = True
    note = ""

    with st.expander(
        "⚙️ Engineer settings, alert thresholds & notes (optional)",
        expanded=False,
    ):
        config_yaml, auto_detect = _render_config_editor(
            config_promotion.CUSTOM_TOOL_MODEL_TEMPLATE,
            key="upload_config",
            default_use=False,
        )
        note = st.text_area(
            "Engineer note (optional context for Nemotron)",
            placeholder="e.g. RF reflectometer excursion on Chamber B",
            max_chars=1000,
            key="upload_note",
            help=(
                "Context note sent to Nemotron; cannot change the Python safety result."
            ),
        )

    st.markdown("### Step 2 — Run the analysis")
    run_clicked = st.button(
        "🚀 Analyze uploaded dataset",
        type="primary",
        disabled=uploaded is None,
        key="run_upload",
        use_container_width=True,
    )
    if run_clicked:
        if preview_data is not None and uploaded is not None:
            st.session_state["result"] = _run_analysis(
                preview_data,
                note,
                demo_mode=demo_mode,
                config_yaml=config_yaml,
                auto_detect=auto_detect,
                label=uploaded.name,
                use_tavily=use_tavily,
                context=context,
            )
    elif uploaded is not None:
        st.caption("The last run for this file is shown below.")


def _render_generator_runner(demo_mode: bool, use_tavily: bool) -> None:
    st.markdown("### Step 1 — Generate a synthetic dataset")
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
    if st.button("Generate synthetic data", key="generate_csv"):
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
            "Generate a seeded synthetic dataset to preview and run through "
            "the safety pipeline."
        )
        return
    context = (
        f"generated:{generated.filename}:{generated.behavior}:{generated.seed}"
    )
    _prepare_result_context(context)
    st.caption(
        f"Generated {generated.filename} · {generated.rows} rows · "
        f"{_behavior_label(generated.behavior)} · seed {generated.seed}"
    )
    _render_preview_from_text(
        generated.csv_bytes.decode("utf-8"),
        generated.template.column_notes,
    )

    default_yaml: str | None = None
    if generated.template.config_path is not None:
        try:
            default_yaml = generated.template.config_path.read_text(encoding="utf-8")
        except OSError as exc:
            st.error(f"The bundled config could not be read: {exc}")

    config_yaml = default_yaml
    auto_detect = False
    note = generated.template.note

    with st.expander(
        "⚙️ Engineer settings, alert thresholds & notes (optional)",
        expanded=False,
    ):
        config_yaml, auto_detect = _render_config_editor(
            default_yaml,
            key=(
                f"generated_{generated.template.key}_{generated.behavior}_"
                f"{generated.seed}"
            ),
            default_use=True,
            config_path=generated.template.config_path,
        )
        note = st.text_area(
            "Engineer note (optional context for Nemotron)",
            value=generated.template.note,
            key=(
                f"generated_note_{generated.template.key}_{generated.behavior}_"
                f"{generated.seed}"
            ),
            max_chars=1000,
        )

    st.markdown("### Step 2 — Run the analysis")
    run_clicked = st.button(
        "🚀 Run analysis on generated dataset",
        type="primary",
        key="run_generated",
        use_container_width=True,
    )
    if run_clicked:
        st.session_state["result"] = _run_analysis(
            generated.csv_bytes,
            note,
            demo_mode=demo_mode,
            config_yaml=config_yaml,
            auto_detect=auto_detect,
            label=generated.filename,
            use_tavily=use_tavily,
            context=context,
            config_path=generated.template.config_path,
        )
    else:
        st.caption("The last run for this generated dataset is shown below.")


def _render_sidebar(live_configured: bool, tavily_configured: bool) -> None:
    with st.sidebar:
        st.markdown("## 🔬 **FabAgent**")
        st.caption("Evidence-Gated Semiconductor Troubleshooting Copilot")
        st.caption(
            "Tells you whether factory sensor data can be trusted, and what to do next."
        )

        with st.popover("📖 Plain-language glossary", use_container_width=True):
            st.markdown("### Terminology Guide")
            st.caption("Clear explanations of industrial safety & AI terms:")
            glossary_items = getattr(presentation, "GLOSSARY", GLOSSARY)
            glossary_rows = [
                {"Term": term, "Plain English meaning": definition}
                for term, definition in glossary_items
            ]
            _table(glossary_rows)

        st.divider()
        st.markdown("### Helper Services")
        st.caption("These are part of the product, not optional switches.")
        if live_configured:
            st.caption(":green[● NVIDIA Nemotron: live on the server]")
        else:
            st.caption(
                ":orange[● NVIDIA Nemotron: offline fixture "
                "(no server key in this environment)]"
            )
            st.caption(
                "The deterministic result still runs. Add the server key to use "
                "live Nemotron."
            )

        if tavily_configured:
            st.caption(":green[● Tavily: enabled for inconclusive results]")
        else:
            st.caption(":gray[● Tavily: no server key, external leads skipped]")

        st.caption(f"Model route: `{_model_label()}`")


def _page_about() -> None:
    st.title("A fab copilot that shows its evidence")
    st.markdown(
        "##### Turn a tool CSV into one defensible next step — with the "
        "evidence, the contradiction, and the audit trail attached."
    )

    _render_flow_diagram()

    col1, col2, col3 = st.columns(3)
    col1.markdown(
        "**Deterministic gate**  \n"
        "DuckDB statistics, evidence IDs, coverage, and contradictions decide "
        "the result. The same input gives the same answer."
    )
    col2.markdown(
        "**Bounded AI**  \n"
        "Nemotron maps columns, proposes causes, and challenges the leader. It "
        "sees a summary under 2 KB, never the raw telemetry."
    )
    col3.markdown(
        "**Honest abstention**  \n"
        "Missing data, a sensor conflict, or an unexplained movement becomes "
        "**Data Incomplete**, **Sensors Disagree**, or **Needs Review** — not a guess."
    )

    st.markdown("")
    demo_col, how_col = st.columns([2, 1])
    if demo_col.button(
        "🚀 Try a demo (30 seconds)",
        type="primary",
        use_container_width=True,
        help="Run the public TEP feed-disturbance demo in one click.",
    ):
        st.session_state["auto_run_demo"] = True
        st.session_state["demo_choice"] = RECOMMENDED_DEMO_KEY
        st.switch_page(_RUN_PAGE)
    if how_col.button(
        "How it works",
        use_container_width=True,
    ):
        st.switch_page(_MODELS_PAGE)

    st.divider()
    _render_markdown_file(_ABOUT_DOC)


def _page_models() -> None:
    st.title("How FabAgent works")
    st.markdown(
        "##### One bounded model layer. One deterministic decision layer. "
        "A human confirms the action."
    )

    _render_flow_diagram(detailed=True)

    with st.expander("The technical division of labour", expanded=True):
        st.markdown(
            "| Layer | Owns | Cannot do |\n"
            "|---|---|---|\n"
            "| **Nemotron** | Column mapping, cause proposals, the disconfirming "
            "challenge, the explanation | Choose the result, choose the action, "
            "or invent evidence |\n"
            "| **Python + DuckDB** | Baseline, evidence IDs, coverage, "
            "contradictions, the six result words, the typed action | Invent "
            "physics, units, or sensor names |\n"
            "| **Tavily** | Public troubleshooting leads on uncertain results | "
            "Change the gate or become evidence |\n"
            "| **The engineer** | The tool model and the final action | Be "
            "replaced by the model |\n"
        )

    _render_markdown_file(_MODELS_DOC)

    st.divider()
    st.subheader("Current server configuration")
    rows: list[dict[str, object]] = [
        {
            "service": "NVIDIA Nemotron (Nebius Token Factory)",
            "route": _model_label(),
            "status": (
                "configured on server (Live calls)"
                if _server_has_key("NEBIUS_API_KEY")
                else "not configured — offline fixture"
            ),
        },
        {
            "service": "Tavily Web Search",
            "route": "public technical search",
            "status": (
                "configured on server"
                if _server_has_key("TAVILY_API_KEY")
                else "not configured — search skipped"
            ),
        },
    ]
    _table(rows)
    st.divider()
    st.subheader("The tool model an engineer edits")
    _render_markdown_file(_YAML_DOC)


def _load_benchmark_summary() -> list[dict[str, object]]:
    """Read the newest committed naive-LLM summary, if one exists."""
    for path in sorted(_RESULTS_DIR.glob(_BENCHMARK_SUMMARY_GLOB), reverse=True):
        try:
            payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        rows = presentation.benchmark_summary_rows(payload)
        if rows:
            return rows
    return []


def _load_baseline_counts() -> tuple[int, int] | None:
    path = _RESULTS_DIR / "naive_llm_baseline.json"
    try:
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    data = cast(dict[str, object], payload)
    safe = data.get("safe_decisions")
    total = data.get("total_cases")
    if (
        isinstance(safe, int)
        and not isinstance(safe, bool)
        and isinstance(total, int)
        and not isinstance(total, bool)
    ):
        return safe, total
    return None


def _page_performance() -> None:
    _render_markdown_file(_PERFORMANCE_DOC)
    st.divider()
    rows = _load_benchmark_summary()
    if rows:
        st.subheader("Measured results")
        _table(rows)
        st.caption(
            "Measured on the fixed case set with the neutral prompt and the same "
            "action menu for every system. This is not field accuracy."
        )
        return
    st.subheader("Benchmark in progress")
    st.info(
        "The fair benchmark has not produced a committed summary yet. No chart "
        "or percentage is shown until it does. The protocol is in "
        "`docs/EVALUATION.md`."
    )
    counts = _load_baseline_counts()
    if counts is not None:
        safe, total = counts
        st.markdown("**Only measured baseline so far**")
        _table(
            [
                {
                    "System": "Nemotron-only (no Python gate)",
                    "Safe decisions": f"{safe}/{total}",
                    "Note": "One small synthetic safety set; not a broad comparison.",
                }
            ]
        )


def _page_contact() -> None:
    _render_markdown_file(_CONTACT_DOC)


def _page_run() -> None:
    st.title("Run a troubleshooting case")
    st.caption(
        "FabAgent checks whether tool telemetry is statistically reliable "
        "before suggesting what to do."
    )

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

    # The model and search services are part of the product. There is no user
    # switch: a server key means live, no key means the deterministic offline
    # fixture, and a failed live call still leaves the Python result intact.
    demo_mode = not _server_has_key("NEBIUS_API_KEY")
    use_tavily = _server_has_key("TAVILY_API_KEY")

    if source == "Prepared dataset":
        _render_demo_runner(demo_mode, use_tavily)
    elif source == "Upload my own CSV":
        _render_upload_runner(demo_mode, use_tavily)
    else:
        _render_generator_runner(demo_mode, use_tavily)

    result = st.session_state.get("result")
    if isinstance(result, RunResult):
        st.divider()
        st.markdown("### Step 3 — Review the result")
        _render_result(result)


_RUN_PAGE = st.Page(
    _page_run,
    title="Run troubleshooting",
    icon=":material/play_circle:",
    url_path="run",
)

_MODELS_PAGE = st.Page(
    _page_models,
    title="How it works",
    icon=":material/hub:",
    url_path="how_it_works",
)


def main() -> None:
    st.set_page_config(page_title="FabAgent", page_icon="\U0001f52c", layout="wide")
    _load_local_env()
    live_configured = _server_has_key("NEBIUS_API_KEY")
    tavily_configured = _server_has_key("TAVILY_API_KEY")
    if not _v2_loader_ready():
        st.error(
            "This Streamlit process is still running an older tool-model loader. "
            "The demo cannot start until the server is restarted once."
        )
        st.code("Ctrl+C\nstreamlit run src/ui/app.py", language="bash")
        st.caption(
            "The files on disk are current; only the running Python process is "
            "stale. A hard refresh is not enough."
        )
        st.stop()
    page = st.navigation(
        {
            "Start here": [
                st.Page(
                    _page_about,
                    title="Start here",
                    icon=":material/rocket_launch:",
                    url_path="about",
                    default=True,
                ),
                _MODELS_PAGE,
            ],
            "Try it": [
                _RUN_PAGE,
            ],
            "Evidence & Proof": [
                st.Page(
                    _page_performance,
                    title="FabAgent vs naive LLM",
                    icon=":material/compare_arrows:",
                    url_path="performance",
                ),
                st.Page(
                    _page_contact,
                    title="Contact & Team",
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
