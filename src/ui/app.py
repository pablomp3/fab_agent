"""FabAgent technician dashboard.

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
from typing import TypedDict, cast

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
from src.model_config import ModelConfigurationError
from src.ui import config_promotion, presentation
from src.ui.presentation import RESULT_GLOSSARY, TERM_GLOSSARY

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
_HEAD_TO_HEAD_GLOB = "naive_llm/*/head_to_head.json"
_CASE_LABELS = {
    "phm_coolant_coverage": "PHM ion-mill coolant window",
    "phm_nominal": "PHM healthy production",
    "tep_feed_disturbance": "TEP feed disturbance",
    "tep_unmodeled": "TEP unmodeled disturbance",
    "synthetic_conflict_b4a": "Synthetic B4a sensor conflict",
    "missing_coolant_flow": "PHM coolant, missing flow channel",
    "synthetic_positive_b4e": "Synthetic B4e positive control",
    "synthetic_conflict_rf": "Synthetic RF sensor conflict",
}
_BENCHMARK_ACTION_LABELS = {
    "INSPECT_COMPONENT": "Inspect the part",
    "INSPECT_SENSOR_CALIBRATION": "Check the sensor",
    "CONTINUE_MONITORING": "Keep monitoring",
    "ESCALATE_TO_ENGINEER": "Ask an engineer",
    "COLLECT_MORE_DATA": "Get more data",
    "HOLD_LOT": "Hold the lot",
    "ADJUST_RECIPE": "Change the recipe",
    "UNPARSABLE": "No usable answer",
}

_BEHAVIOR_LABELS = {
    "supported": "Fault pattern present",
    "inconclusive": "Nominal pattern",
    "contradiction": "One sensor only (contradiction)",
}

# The one-click demo should lead with a semiconductor case, not the
# cross-industry TEP reactor. The synthetic coolant case is a clean positive
# control; the video can then show the real PHM case and its honest abstention.
RECOMMENDED_DEMO_KEY = "synthetic_flowcool_supported"

_STAGE_LABELS = {
    "read": "Read the CSV — load the engineer's tool export",
    "triage": ("Match tool configuration — find the YAML that describes these columns"),
    "mapping": (
        "NVIDIA Nemotron mapping — guess column roles (experimental)"
    ),
    "duckdb": "Scan the data — compute statistics per column (DuckDB)",
    "python": "Run safety checks — check for abnormal, missing, or conflicting data",
    "model": (
        "NVIDIA Nemotron reasoning — propose, challenge, and explain "
        "(never decides)"
    ),
    "gate": "Python decision gate — select one safe next step",
    "tavily": "Tavily research — public leads when the data is uncertain",
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


_DOT_BLOCK = re.compile(r"```dot\n(.*?)```", re.DOTALL)
_EVIDENCE_ID = re.compile(r"\bEV_[A-F0-9]{8,}\b")


def _plain_model_text(text: str) -> str:
    """Keep raw evidence IDs in the audit view, not in the main AI narrative."""
    return _EVIDENCE_ID.sub("the cited evidence", text)



def _render_flow_diagram() -> None:
    """One vertical flow: input -> AI reasoning -> Python decision -> result."""
    st.html(
        """
<style>
.fa-vflow { max-width: 760px; margin: 0.4rem auto 1.1rem; }
.fa-vbox {
  border-radius: 12px;
  padding: 14px 18px;
  border: 1px solid #DCE6EC;
  background: #F3F6F8;
}
.fa-vbox h4 {
  margin: 0 0 4px;
  font-size: 0.72rem;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: #0B6E99;
}
.fa-vbox p { margin: 0; color: #1F2933; font-size: 0.95rem; }
.fa-vbox small { display: block; margin-top: 5px; color: #52606D; font-size: 0.82rem; }
.fa-vbox.ai { background: #E8F3F8; border-color: #C7E2EE; }
.fa-vbox.core { background: #0B6E99; border-color: #0B6E99; }
.fa-vbox.core h4, .fa-vbox.core p, .fa-vbox.core small { color: #FFFFFF; }
.fa-vbox.output { background: #EAF6EF; border-color: #BFE3CD; }
.fa-vline { width: 2px; height: 18px; background: #9FB3C8; margin: 0 auto; }
.fa-steps { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.fa-steps span {
  border: 1px solid rgba(255,255,255,0.42);
  background: rgba(255,255,255,0.14);
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 0.8rem;
}
</style>
<div class="fa-vflow">
  <div class="fa-vbox">
    <h4>1 · Input</h4>
    <p><b>CSV export + optional tool model</b></p>
    <small>Signals, a normal reference, and the engineer's saved fault checks.</small>
  </div>
  <div class="fa-vline"></div>
  <div class="fa-vbox ai">
    <h4>2 · AI reasoning</h4>
    <p><b>NVIDIA Nemotron</b></p>
    <small>Maps unknown columns · proposes causes · challenges the leading cause ·
    writes the explanation.</small>
    <small><b>Tavily research</b> adds public troubleshooting leads when the data is
    uncertain.</small>
  </div>
  <div class="fa-vline"></div>
  <div class="fa-vbox core">
    <h4>3 · Deterministic decision</h4>
    <p><b>Python + DuckDB</b></p>
    <div class="fa-steps">
      <span>Baseline</span><span>Evidence</span><span>Coverage</span>
      <span>Contradiction</span><span>Action</span>
    </div>
    <small>Every declared signal is scored. Missing data and contradictions are
    hard stops. The model cannot change this result.</small>
  </div>
  <div class="fa-vline"></div>
  <div class="fa-vbox output">
    <h4>4 · Result</h4>
    <p><b>One of six outcomes + one safe next step</b></p>
    <small>With the evidence, the contradiction, and the audit trail attached.</small>
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
) -> tuple[str | None, bool, bool]:
    """Return ``(yaml_text, auto_detect, force_experimental)`` for the run.

    ``force_experimental`` is true only when the engineer explicitly turns off a
    saved tool model. In that case the run must not silently triage a different
    saved config; it goes straight to the bounded Auto mapping path.

    The normal view is a readable summary. The raw YAML is an advanced,
    engineer-only surface; a first-time user should never have to read it.
    """
    if default_yaml is None:
        st.info(
            "FabAgent will try to match a saved tool model. If none matches, it "
            "uses experimental Auto mode: NVIDIA Nemotron guesses the column "
            "roles, and the result stays unverified until an engineer saves a "
            "model."
        )
        return None, True, False

    if config_path is not None:
        _render_config_summary(config_path, signal_notes)
        use_model = st.toggle(
            "Use this saved tool model for the run",
            value=default_use,
            key=f"{key}_use",
            help=(
                "On: deterministic RCA from the saved signals, normal "
                "reference, and fault checks. Off: force experimental Auto "
                "mode, where Nemotron guesses the column roles."
            ),
        )
        if not use_model:
            st.warning(
                "Auto mode is forced for this run. NVIDIA Nemotron will guess "
                "what each column means, saved tool models are bypassed, and the "
                "result stays **Unknown Machine** until an engineer reviews and "
                "saves a tool model. For a known tool, keep the saved model on."
            )
            return None, True, True
    else:
        st.info(
            "No tool model is selected for this upload. FabAgent will try a "
            "saved match first; if none matches, it uses experimental Auto mode "
            "unless you provide a tool model below."
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
            return None, True, False
        return default_yaml, False, False

    st.caption(
        "Raw YAML for an engineer. Unknown keys or a bad path fail with the "
        "exact location; the run uses this text directly."
    )
    st.caption(
        "`baseline.file` is a server-side reference to a saved normal run. "
        "Leave it unchanged unless you are moving the tool model."
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
        width="stretch",
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
        width="stretch",
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
    return text, False, False


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
        return "skipped — disabled for this run"
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
    force_experimental: bool = False,
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
                                force_experimental=force_experimental,
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
                                force_experimental=force_experimental,
                                progress=progress,
                            )
                    else:
                        if search_dir is None:
                            result = analyze_csv(
                                path,
                                note,
                                enable_external_search=search_enabled,
                                force_experimental=force_experimental,
                                progress=progress,
                            )
                        else:
                            result = analyze_csv(
                                path,
                                note,
                                search_dir=search_dir,
                                enable_external_search=search_enabled,
                                force_experimental=force_experimental,
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
        st.caption(
            "Python owns this decision. NVIDIA Nemotron explains and challenges "
            "it; Tavily adds public research. Neither can change the result."
        )

        with st.container(border=True):
            st.markdown(f"**Recommended Next Step:** {card.action_label}")
            st.caption(card.action_explanation)

        challenge = result.output.challenge
        if challenge is not None and (
            challenge.downgraded or challenge.status.value == "checked"
        ):
            if challenge.downgraded:
                st.caption(
                    ":orange[NVIDIA Nemotron challenge: the disconfirming test "
                    "was not met; the result was downgraded.]"
                )
            else:
                st.caption(
                    ":green[NVIDIA Nemotron challenge: checked. The model named "
                    "a disconfirming signal, and Python verified it.]"
                )


def _render_why_summary(result: RunResult) -> None:
    """Render clear bullet points explaining which sensors moved and why."""
    st.markdown("### 🔍 Telemetry findings: what moved and why")

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
                "Robust z = 0.6745 × |peak − median| / MAD over the normal "
                "reference. 3.5z is the default alert level; bars are clipped at "
                f"{presentation.DISPLAY_Z_CAP:g}z. Raw values are in the "
                "technical audit."
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


def _render_telemetry_measurements(result: RunResult) -> None:
    """One consolidated telemetry table, with raw audit data folded away."""
    st.markdown("#### Telemetry measurements")
    summary = presentation.summarize(result)

    if result.mode == "safe":
        st.caption(
            f"**Configuration**: :green[Known machine] · "
            f"{summary.evidence_count} evidence records checked"
        )
    else:
        st.warning(
            "**Configuration**: :orange[Unknown machine] — NVIDIA Nemotron "
            "generated a draft mapping below"
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
            st.caption("Telemetry time-series profile for the evaluated channels:")
            st.line_chart(labelled)  # pyright: ignore[reportUnknownMemberType]

    if not result.evidence:
        st.info("No evidence records were generated.")
        return

    raw_rows = presentation.evidence_rows(result.evidence)
    plain_rows: list[dict[str, object]] = [
        {
            "Signal": presentation.signal_label(result, r.signal),
            "Status": r.status,
            "Peak deviation": r.how_unusual,
            "Alert level": r.alert_threshold,
            "What it means": r.summary,
        }
        for r in raw_rows
    ]
    st.caption(
        "One row per declared channel. Peak deviation is a robust z-score; "
        "values of 50z or more are shown as ≥50z."
    )
    with st.expander(
        "How the robust z-score and the 3.5z alert level work",
        expanded=False,
    ):
        st.markdown(
            "Each declared signal is compared with the normal reference using "
            "the median and MAD. The peak absolute score is:\n\n"
            "`z = 0.6745 × |value − median| / MAD`\n\n"
            "`0.6745 = Φ⁻¹(0.75)` makes this normal-equivalent sigma. **3.5z** "
            "is the editable per-signal alert; **5z** is the coverage limit that "
            "blocks a bare **Fault Confirmed** when a large signal is unexplained. "
            "They are screening levels, not physics tolerances; use a calibrated "
            "limit when available."
        )
    _table(plain_rows)

    if result.output.required_next_checks:
        st.markdown("**Required next safety checks:**")
        for check in result.output.required_next_checks:
            st.write(f"- {check}")

    with st.expander(
        "Technical audit — evidence IDs, raw statistics, and model boundary",
        expanded=False,
    ):
        st.caption(
            "For reviewers. The evidence payload row proves that the model saw "
            "a bounded statistical summary under 2 KB, never the raw telemetry. "
            "Python resolves every citation before it is used."
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
            {
                "Audit item": "AI reasoning roles",
                "Value": presentation.model_role_text(result),
            },
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


def _render_nemotron_explanation(result: RunResult) -> None:
    """The NVIDIA Nemotron reasoning layer, kept separate from the decision."""
    st.markdown("#### NVIDIA Nemotron explanation")
    mode = str(st.session_state.get("result_mode", "unknown"))
    if mode == "offline":
        st.caption(
            ":orange[Offline Nemotron fixture · the hosted demo uses live NVIDIA "
            "Nemotron on Nebius Token Factory.]"
        )
    elif _model_explanation_available(result):
        st.caption(":green[● Live NVIDIA Nemotron · Nebius Token Factory]")
    else:
        st.warning(
            "NVIDIA Nemotron did not return a usable explanation for this run. "
            "The deterministic Python result above still applies."
        )

    st.caption(
        "Nemotron maps unknown columns, proposes causes, challenges the leading "
        "cause, and writes this explanation. Python resolves every cited evidence "
        "ID and owns the decision; the model cannot override the result."
    )

    narratives = [
        hypothesis.model_narrative
        for hypothesis in result.output.hypotheses
        if hypothesis.model_narrative is not None
    ]
    proposed = [
        item for item in result.output.differential if item.proposed_by_model
    ]
    if narratives:
        for narrative in narratives:
            with st.container(border=True):
                st.markdown(f"**{_plain_model_text(narrative.claim)}**")
                st.markdown(_plain_model_text(narrative.mechanism))
                st.caption(
                    "Proposed failure mode: "
                    f"{_plain_model_text(narrative.failure_mode)}"
                )
    elif proposed:
        st.markdown("**Unverified causes proposed by NVIDIA Nemotron**")
        st.caption(
            "The model proposed these from the guessed mapping. No saved check "
            "exists, so Python cannot confirm or reject them; the main result "
            "stays **Unknown Machine**."
        )
        for item in proposed:
            with st.container(border=True):
                st.markdown(f"**{_plain_model_text(item.title)}**")
                if item.reason:
                    st.markdown(_plain_model_text(item.reason))
                st.caption(
                    "Unverified model proposal; it is not used for the result or "
                    "the action."
                )
    else:
        st.info(
            "NVIDIA Nemotron did not return a usable explanation or cause for "
            "this run. The deterministic Python result above still applies."
        )

    if narratives:
        cited = sum(len(item.cited_evidence) for item in narratives)
        unresolved = len(presentation.unresolved_citations(result))
        col1, col2 = st.columns(2)
        col1.metric("Citations verified by Python", cited)
        col2.metric("Unresolved citations flagged", unresolved)
        if unresolved:
            st.warning(
                "The model cited evidence IDs Python could not resolve. They are "
                "rejected by the safety rules and listed in the technical audit."
            )
    elif proposed:
        st.caption(
            f"{len(proposed)} unverified cause(s) proposed. Python keeps the "
            "result at **Unknown Machine** until a saved check exists."
        )

    challenge = result.output.challenge
    if challenge is None:
        st.caption("Challenge check: not run for this result.")
    elif challenge.downgraded:
        st.caption(
            ":orange[Challenge check: the disconfirming test was not met; the "
            "result was downgraded.]"
        )
    elif challenge.status.value == "checked":
        st.caption(
            ":green[Challenge check: checked. The model named a disconfirming "
            "signal, and Python verified it.]"
        )
    else:
        st.caption(
            "Challenge check: the model did not return a usable disconfirming "
            "test for this run. The Python result is unchanged."
        )


def _render_web_tab(result: RunResult) -> None:
    st.markdown("#### Tavily research: public troubleshooting leads")
    st.caption(
        "Tavily is the external research layer. It runs when telemetry is "
        "inconclusive, conflicting, or unconfigured, sends only bounded signal "
        "names, and returns public leads. Its references are context for a human, "
        "never evidence for the safety gate."
    )

    status = result.external_search_status
    if status == "not_needed":
        st.info(
            "Tavily was on standby for this run: the telemetry was conclusive, so "
            "no external lookup was needed. Run the PHM coolant or RF "
            "sensor-conflict demo to see live research leads."
        )
        return
    if status == "not_configured":
        st.warning(
            "Tavily is not configured on this server. Public research leads are "
            "skipped; the deterministic result is unchanged."
        )
        return
    if status == "unavailable":
        st.warning(
            "Tavily was configured but the search failed for this run. The "
            "deterministic result is unchanged."
        )
        return
    if status == "disabled":
        st.info("Tavily research was disabled for this run.")
        return

    if result.external_search_query:
        st.markdown(f"**Search query**: `{result.external_search_query}`")

    if result.output.external_sources:
        st.caption(
            f"{len(result.output.external_sources)} public reference(s) returned. "
            "Tavily does not rank or decide; the engineer judges relevance."
        )
        for source in result.output.external_sources:
            with st.container(border=True):
                title = source.title or "Industrial troubleshooting reference"
                st.markdown(f"🔗 **[{title}]({source.url})**")
                if source.snippet:
                    st.caption(source.snippet)
    else:
        st.info("Tavily returned no public references for this run.")


def _render_mapping(result: RunResult) -> None:
    mapping = result.mapping
    if mapping is None:
        return
    st.markdown("#### Unknown machine — draft mapping")
    st.warning(
        "This machine is not configured. NVIDIA Nemotron guessed the roles below "
        "from the column names and bounded statistics. Treat them as unverified "
        "until an engineer reviews the draft."
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
    with st.expander(
        "Review or download the draft tool model YAML",
        expanded=False,
    ):
        st.caption(
            "This draft is **not saved on the server**. The hosted app is "
            "stateless and does not write shared tool models. Download this "
            "file, edit it, then paste it into **Engineer settings → Advanced: "
            "edit the tool model YAML** on a later run to make the result "
            "deterministic."
        )
        st.code(result.draft_yaml, language="yaml")
        st.download_button(
            "Download draft YAML",
            data=result.draft_yaml,
            file_name="experimental_draft.yaml",
            mime="text/yaml",
            width="stretch",
        )


def _render_result(result: RunResult) -> None:
    # 1. The Python-owned decision is always visible.
    _render_answer_card(result)

    # 2. Two clear surfaces: the result evidence + AI explanation, and the
    #    external research leads. No third "audit" tab competing with the result.
    tab_main, tab_research = st.tabs(
        [
            "📊 Result & AI explanation",
            "🌐 Tavily research",
        ]
    )
    with tab_main:
        if result.mapping is not None:
            _render_mapping(result)
        _render_why_summary(result)
        _render_differential(result)
        _render_what_else_moved(result)
        _render_telemetry_measurements(result)
        _render_nemotron_explanation(result)
    with tab_research:
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

    st.caption(f"**Source:** {case.source}")
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
    force_experimental = False
    note = case.note

    with st.expander(
        "⚙️ Engineer settings (tool model & note, optional)",
        expanded=False,
    ):
        config_yaml, auto_detect, force_experimental = _render_config_editor(
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
                force_experimental=force_experimental,
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
    force_experimental = False
    note = ""

    with st.expander(
        "⚙️ Engineer settings (tool model & note, optional)",
        expanded=False,
    ):
        config_yaml, auto_detect, force_experimental = _render_config_editor(
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
                force_experimental=force_experimental,
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
    force_experimental = False
    note = generated.template.note

    with st.expander(
        "⚙️ Engineer settings (tool model & note, optional)",
        expanded=False,
    ):
        config_yaml, auto_detect, force_experimental = _render_config_editor(
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
            force_experimental=force_experimental,
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
        st.caption("A manufacturing copilot with a focus on semiconductors")
        st.caption(
            "Deterministic troubleshooting and RCA for manufacturing and "
            "industrial operations."
        )

        with st.popover("📖 Possible outcomes & plain language", width="stretch"):
            st.markdown("### Possible outcomes")
            st.caption(
                "Every run returns exactly one of these six results. Internal "
                "engine states stay out of the main flow."
            )
            _table(
                [
                    {"Outcome": term, "What it means": definition}
                    for term, definition in RESULT_GLOSSARY
                ]
            )
            st.markdown("### Numbers & layers")
            _table(
                [
                    {"Term": term, "Plain English meaning": definition}
                    for term, definition in TERM_GLOSSARY
                ]
            )

        st.divider()
        st.markdown("### AI reasoning layer")
        st.markdown("**NVIDIA Nemotron**")
        if live_configured:
            st.caption(":green[● Live on Nebius Token Factory]")
        else:
            st.caption(
                ":orange[● Offline fixture · no server key in this environment]"
            )
        st.caption(
            "Maps unknown columns · proposes causes · challenges the leader · "
            "writes the explanation."
        )

        st.markdown("**Tavily research**")
        if tavily_configured:
            st.caption(":green[● Live for uncertain results]")
        else:
            st.caption(":gray[● No server key · external leads skipped]")
        st.caption(
            "Finds public troubleshooting references when the data is uncertain."
        )

        st.divider()
        st.markdown("### Deterministic decision layer")
        st.caption(":green[● Python + DuckDB · always on]")
        st.caption(
            "Owns the baseline, coverage, contradictions, the six results, and "
            "the safe next step."
        )


def _page_about() -> None:
    st.title("FabAgent: a manufacturing copilot with a focus on semiconductors")
    st.markdown(
        "##### Deterministic troubleshooting and root-cause analysis for "
        "manufacturing and industrial operations, with a focus on semiconductor "
        "fabs."
    )
    st.markdown(
        "> **FabAgent turns a tool export into one defensible next step.** "
        "NVIDIA Nemotron reasons over the evidence. Tavily adds public research "
        "when the data is uncertain. Python checks every claim and owns the "
        "result. The engineer decides."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        with st.container(border=True):
            st.markdown("#### One safe next step")
            st.caption(
                "DuckDB statistics, evidence IDs, coverage, and contradictions "
                "decide the result. The same input gives the same answer."
            )
    with col2:
        with st.container(border=True):
            st.markdown("#### NVIDIA Nemotron")
            st.caption(
                "Maps unknown columns, proposes causes, challenges the leading "
                "cause, and writes the explanation. It sees a bounded summary "
                "under 2 KB, never the raw telemetry."
            )
    with col3:
        with st.container(border=True):
            st.markdown("#### Tavily research")
            st.caption(
                "Finds public troubleshooting references when the data is "
                "uncertain. Its leads are context for a human, never evidence "
                "for the safety gate."
            )

    st.markdown("#### Start with a prepared case")
    demo_col, conflict_col, how_col = st.columns(3)
    if demo_col.button(
        "🚀 Try a one-click demo",
        type="primary",
        width="stretch",
        help="Run a clean semiconductor coolant positive control in one click.",
    ):
        st.session_state["auto_run_demo"] = True
        st.session_state["demo_choice"] = RECOMMENDED_DEMO_KEY
        st.switch_page(_RUN_PAGE)
    if conflict_col.button(
        "See a sensor conflict",
        width="stretch",
        help=(
            "Show an RF sensor that disagrees with its companions, plus live "
            "Tavily research."
        ),
    ):
        st.session_state["auto_run_demo"] = True
        st.session_state["demo_choice"] = "synthetic_rf_veto"
        st.switch_page(_RUN_PAGE)
    if how_col.button(
        "How it works",
        width="stretch",
    ):
        st.switch_page(_MODELS_PAGE)

    st.divider()
    _render_markdown_file(_ABOUT_DOC)


def _page_models() -> None:
    st.title("How FabAgent works")
    st.markdown(
        "##### The technical path: NVIDIA Nemotron and Tavily reason over the "
        "evidence, Python decides, and the engineer acts."
    )

    _render_flow_diagram()

    _render_markdown_file(_MODELS_DOC)

    st.divider()
    st.subheader("Current server configuration")
    rows: list[dict[str, object]] = [
        {
            "Layer": "NVIDIA Nemotron (Nebius Token Factory)",
            "Role": "Mapping, cause finding, challenge, explanation",
        },
        {
            "Layer": "Tavily research",
            "Role": "Public troubleshooting leads on uncertain results",
        },
        {
            "Layer": "Python + DuckDB",
            "Role": "Deterministic decision, coverage, and safe action",
        },
    ]
    _table(rows)
    st.divider()
    st.subheader("The tool model an engineer edits")
    _render_markdown_file(_YAML_DOC)


def _load_benchmark_payload() -> dict[str, object] | None:
    """Read the newest committed naive-LLM summary, if one exists."""
    for path in sorted(_RESULTS_DIR.glob(_BENCHMARK_SUMMARY_GLOB), reverse=True):
        try:
            payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return cast(dict[str, object], payload)
    return None


def _load_head_to_head() -> dict[str, object] | None:
    """Read the newest matched head-to-head artifact, if one exists."""
    for path in sorted(_RESULTS_DIR.glob(_HEAD_TO_HEAD_GLOB), reverse=True):
        try:
            payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return cast(dict[str, object], payload)
    return None


_SYSTEM_PROVIDERS = {
    "FabAgent (deterministic gate)": "fabagent",
    "Nemotron-only (evidence track)": "nebius",
    "Gemini 3.8 Flash (medium)": "gemini",
    "GPT-5.6 Luna": "openai",
}


class _ProviderStats(TypedDict):
    n: int
    unsafe: int
    cause_ok: int
    cause_n: int
    abst_ok: int
    abst_n: int
    false_alarm: int
    false_alarm_n: int
    evidence: float | None


def _system_provider(system: str) -> str | None:
    if system in _SYSTEM_PROVIDERS:
        return _SYSTEM_PROVIDERS[system]
    lowered = system.casefold()
    if "gemini" in lowered:
        return "gemini"
    if "gpt" in lowered or "chatgpt" in lowered:
        return "openai"
    if "nemotron-only" in lowered:
        return "nebius"
    if "fabagent" in lowered:
        return "fabagent"
    return None


def _display_system(system: str) -> str:
    if system == "FabAgent (deterministic gate)":
        return "FabAgent"
    if system == "Nemotron-only (evidence track)":
        return "Nemotron-only (no Python gate)"
    return system


def _provider_stats(
    records: Sequence[Mapping[str, object]], provider: str
) -> _ProviderStats | None:
    subset = [
        record
        for record in records
        if str(record.get("provider", "")) == provider
    ]
    if not subset:
        return None
    unsafe = sum(1 for record in subset if record.get("unsafe") is True)
    cause_scored = [
        record for record in subset if record.get("correct_cause") is not None
    ]
    cause_ok = sum(
        1 for record in cause_scored if record.get("correct_cause") is True
    )
    abst_scored = [
        record
        for record in subset
        if record.get("appropriate_abstention") is not None
    ]
    abst_ok = sum(
        1
        for record in abst_scored
        if record.get("appropriate_abstention") is True
    )
    false_alarm_scored = [
        record for record in subset if record.get("false_alarm") is not None
    ]
    false_alarm = sum(
        1 for record in false_alarm_scored if record.get("false_alarm") is True
    )
    evidence_values: list[float] = []
    for record in subset:
        value = record.get("evidence_accuracy")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            evidence_values.append(float(value))
    return {
        "n": len(subset),
        "unsafe": unsafe,
        "cause_ok": cause_ok,
        "cause_n": len(cause_scored),
        "abst_ok": abst_ok,
        "abst_n": len(abst_scored),
        "false_alarm": false_alarm,
        "false_alarm_n": len(false_alarm_scored),
        "evidence": (
            sum(evidence_values) / len(evidence_values)
            if evidence_values
            else None
        ),
    }


def _metric_text(
    numerator: int, denominator: int, tone: str | None
) -> str:
    if denominator <= 0:
        return presentation.MISSING
    text = f"{numerator}/{denominator} ({numerator / denominator:.0%})"
    return f":{tone}[**{text}**]" if tone is not None else text


def _benchmark_display_rows(
    rows: Sequence[Mapping[str, object]],
    case_records: Sequence[Mapping[str, object]] = (),
    *,
    include_false_alarm: bool = False,
) -> list[dict[str, object]]:
    display: list[dict[str, object]] = []
    for row in rows:
        raw_system = str(row.get("system", presentation.MISSING))
        provider = _system_provider(raw_system)
        system = _display_system(raw_system)
        item = (
            _provider_stats(case_records, provider)
            if provider is not None
            else None
        )
        n = item["n"] if item is not None else 0
        unsafe = item["unsafe"] if item is not None else 0
        cause_ok = item["cause_ok"] if item is not None else 0
        cause_n = item["cause_n"] if item is not None else 0
        abst_ok = item["abst_ok"] if item is not None else 0
        abst_n = item["abst_n"] if item is not None else 0
        evidence = (
            item["evidence"]
            if item is not None and item["evidence"] is not None
            else row.get("evidence_accuracy")
        )
        evidence_text = presentation.MISSING
        if isinstance(evidence, (int, float)) and not isinstance(evidence, bool):
            evidence_text = f"{float(evidence):.0%}"
            evidence_tone = (
                "green"
                if float(evidence) >= 0.99
                else ("red" if float(evidence) < 0.7 else "orange")
            )
            evidence_text = f":{evidence_tone}[**{evidence_text}**]"
        cause_tone = (
            "green"
            if cause_n > 0 and cause_ok == cause_n
            else ("red" if cause_ok == 0 else "orange")
        )
        abst_tone = (
            "green"
            if abst_n > 0 and abst_ok == abst_n
            else ("red" if abst_ok == 0 else "orange")
        )
        display_row: dict[str, object] = {
            "System": system,
            "Unsafe actions": _metric_text(
                unsafe, n, "green" if unsafe == 0 else "red"
            ),
            "Correct cause": _metric_text(cause_ok, cause_n, cause_tone),
            "Appropriate abstention": _metric_text(
                abst_ok, abst_n, abst_tone
            ),
            "Evidence accuracy": evidence_text,
        }
        if include_false_alarm:
            false_alarm = item["false_alarm"] if item is not None else 0
            false_alarm_n = (
                item["false_alarm_n"] if item is not None else 0
            )
            display_row["False alarm"] = _metric_text(
                false_alarm,
                false_alarm_n,
                "green" if false_alarm == 0 else "red",
            )
        display.append(display_row)
    return display


def _head_to_head_track(
    payload: Mapping[str, object], track: str
) -> dict[str, object] | None:
    tracks = payload.get("tracks")
    if not isinstance(tracks, dict):
        return None
    data = cast(dict[str, object], tracks).get(track)
    if not isinstance(data, dict):
        return None
    return cast(dict[str, object], data)


def _track_table_data(
    track: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[Mapping[str, object]]]:
    systems = track.get("systems")
    rows = (
        presentation.benchmark_summary_rows(
            {"systems": cast(list[object], systems)}
        )
        if isinstance(systems, list)
        else []
    )
    raw_cases = track.get("cases")
    case_records: list[Mapping[str, object]] = []
    if isinstance(raw_cases, list):
        for item in cast(list[object], raw_cases):
            if isinstance(item, dict):
                case_records.append(cast(dict[str, object], item))
    return rows, case_records


def _head_to_head_case_rows(
    track: Mapping[str, object],
) -> list[dict[str, object]]:
    raw_cases = track.get("cases")
    if not isinstance(raw_cases, list):
        return []
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    for item in cast(list[object], raw_cases):
        if not isinstance(item, dict):
            continue
        record = cast(dict[str, object], item)
        case_id = record.get("case")
        provider = record.get("provider")
        if isinstance(case_id, str) and isinstance(provider, str):
            by_key[(case_id, provider)] = record
    rows: list[dict[str, object]] = []
    providers = (
        ("FabAgent", "fabagent"),
        ("Gemini 3.8 Flash", "gemini"),
        ("GPT-5.6 Luna", "openai"),
    )
    for case_id, label in _CASE_LABELS.items():
        if not any((case_id, provider) in by_key for _, provider in providers):
            continue
        row: dict[str, object] = {"Case": label}
        for column, provider in providers:
            record = by_key.get((case_id, provider))
            if record is None:
                row[column] = presentation.MISSING
                continue
            action = str(record.get("action", ""))
            text = _BENCHMARK_ACTION_LABELS.get(
                action, action or presentation.MISSING
            )
            if record.get("unsafe") is True:
                text = f":red[**{text}**]"
            row[column] = text
        rows.append(row)
    return rows


def _total_sentence(
    rows: Sequence[Mapping[str, object]],
    case_records: Sequence[Mapping[str, object]],
) -> str:
    parts: list[str] = []
    for row in rows:
        raw_system = str(row.get("system", presentation.MISSING))
        system = _display_system(raw_system)
        provider = _system_provider(raw_system)
        if provider is None:
            continue
        stats = _provider_stats(case_records, provider)
        if stats is None:
            continue
        parts.append(
            f"{system}: {stats['n'] - stats['unsafe']}/{stats['n']} safe, "
            f"{stats['cause_ok']}/{stats['cause_n']} correct causes"
        )
    return "; ".join(parts)


def _page_performance() -> None:
    _render_markdown_file(_PERFORMANCE_DOC)
    head = _load_head_to_head()
    if head is None:
        st.subheader("Benchmark in progress")
        st.info(
            "The fair benchmark has not produced a committed summary yet. No "
            "chart or percentage is shown until it does."
        )
        return

    st.markdown("### Datasets evaluated")
    dataset_columns = st.columns(3)
    with dataset_columns[0]:
        with st.container(border=True):
            st.markdown("#### Synthetic twin")
            st.caption(
                "**What it is:** a seeded simulator with an injected fault and "
                "recorded expected sensor consequences."
            )
            st.caption(
                "**Why it matters:** the right answer is written down before "
                "FabAgent runs."
            )
            st.caption(
                "**What it proves:** whether the system recovers the injected "
                "cause or abstains."
            )
    with dataset_columns[1]:
        with st.container(border=True):
            st.markdown("#### PHM 2018 — ion mill")
            st.caption(
                "**What it is:** real ion-mill telemetry with a published "
                "coolant-fault label."
            )
            st.caption(
                "**Why it matters:** a real equipment export with a documented "
                "fault."
            )
            st.caption(
                "**What it proves:** equipment-subsystem reasoning and "
                "contradiction handling."
            )
    with dataset_columns[2]:
        with st.container(border=True):
            st.markdown("#### TEP — chemical reactor")
            st.caption(
                "**What it is:** a public chemical-reactor simulation with known "
                "disturbance IDs."
            )
            st.caption(
                "**Why it matters:** a second known-answer set with a cause and "
                "a symptom."
            )
            st.caption(
                "**What it proves:** cause-vs-symptom reasoning and abstention."
            )
    st.info(
        "**How we know the answer:** the synthetic fault and expected "
        "consequences were recorded before the run; PHM and TEP labels are "
        "published with the datasets. These known-answer tests prove the decision "
        "pattern; field accuracy needs a real fab pilot."
    )

    evidence = _head_to_head_track(head, "evidence")
    raw = _head_to_head_track(head, "raw")

    if evidence is not None:
        rows, records = _track_table_data(evidence)
        if rows:
            st.subheader("Benchmark 1 — FabAgent vs frontier LLM (only prompts)")
            _table(_benchmark_display_rows(rows, records))
            totals = _total_sentence(rows, records)
            if totals:
                st.caption(f"**Totals:** {totals}.")
            st.caption(
                "Four completed cases. The models receive the same neutral "
                "prompt and bounded evidence summary. Cause is scored only where "
                "the dataset defines a cause; the PHM coolant case tests coverage "
                "and abstention."
            )
            case_rows = _head_to_head_case_rows(evidence)
            if case_rows:
                st.markdown("#### What each model recommended")
                _table(case_rows)

    if raw is not None:
        rows, records = _track_table_data(raw)
        if rows:
            st.subheader(
                "Benchmark 2 — FabAgent vs frontier LLM (prompt + raw CSV data)"
            )
            _table(_benchmark_display_rows(rows, records))
            totals = _total_sentence(rows, records)
            if totals:
                st.caption(f"**Totals:** {totals}.")
            st.caption(
                "Same four completed cases, with the raw CSV attached. This "
                "tests column reading and mapping as well as the decision."
            )

    payload = _load_benchmark_payload()
    summary_rows = presentation.benchmark_summary_rows(payload) if payload else []
    ablation = [
        row
        for row in summary_rows
        if str(row.get("system", "")).startswith(("FabAgent", "Nemotron-only"))
    ]
    ablation_records: list[Mapping[str, object]] = []
    raw_cases = payload.get("cases") if payload is not None else None
    if isinstance(raw_cases, list):
        for item in cast(list[object], raw_cases):
            if isinstance(item, dict):
                ablation_records.append(cast(dict[str, object], item))
    if ablation:
        st.subheader(
            "Benchmark 3 — FabAgent workflow vs Nemotron-only (same model, "
            "same evidence)"
        )
        _table(
            _benchmark_display_rows(
                ablation, ablation_records, include_false_alarm=True
            )
        )
        totals = _total_sentence(ablation, ablation_records)
        if totals:
            st.caption(f"**Totals:** {totals}.")
        st.caption(
            "Eight complete cases. The same model and bounded evidence, but "
            "FabAgent also receives the saved tool-model checks and the Python "
            "gate. This is a workflow comparison, not a pure gate ablation. "
            "Seven cases have a scored cause; the PHM coolant case is the "
            "coverage case."
        )

    st.markdown("### What this shows")
    st.markdown(
        "- **FabAgent is the only system that is both safe and correct.** It has "
        "zero unsafe actions and the correct cause on every scored case.\n"
        "- **Gemini's unsafe call is on missing data.** It recommends inspecting "
        "the physical part when a required coolant-flow channel is absent — the "
        "exact failure the gate prevents.\n"
        "- **GPT-5.6 is safe by not committing.** It recommends the same cautious "
        "action repeatedly and gets only the missing-channel `unknown` case "
        "right; it misses the feed disturbance and the RF conflict.\n"
        "- **The risk is two-sided:** one model acts on incomplete data, while "
        "the other never solves attribution. FabAgent does neither.\n"
        "- **The workflow is the difference:** with the same Nemotron model and "
        "the same evidence, saved checks plus the gate turn 6/8 safe into 8/8 "
        "safe and remove the false alarm on the healthy run. Because the naive "
        "arm does not receive the saved checks, this is a workflow comparison, "
        "not a pure gate ablation."
    )
    st.caption(
        "Known-answer tests and a workflow comparison. Field accuracy needs a "
        "real fab pilot with engineer-confirmed outcomes. The naive models did "
        "not receive the saved tool-model checks."
    )

def _page_contact() -> None:
    _render_markdown_file(_CONTACT_DOC)


def _page_run() -> None:
    st.title("Run a troubleshooting case")
    st.caption(
        "FabAgent checks whether tool telemetry is statistically reliable "
        "before suggesting what to do. Bring a CSV export from any manufacturing "
        "tool; semiconductor fabs are the first target."
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
        st.markdown("### Step 3 — Decision and evidence")
        st.caption(
            "Python has already computed the decision. The tabs below show the "
            "telemetry evidence, the NVIDIA Nemotron explanation, and Tavily "
            "research leads; none of them can change the result."
        )
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
                    title="FabAgent vs frontier LLM",
                    icon=":material/compare_arrows:",
                    url_path="performance",
                ),
                st.Page(
                    _page_contact,
                    title="Project & contact",
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
