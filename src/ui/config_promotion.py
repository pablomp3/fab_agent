"""Promote an experimental draft mapping to a saved sensor-relations config.

A draft is written only after it round-trips through the *same* config loader
the engine uses, so a saved file is guaranteed to load. Saving is a local file
authoring step (not a tool action); it refuses to overwrite an existing config
unless the caller explicitly confirms, so a reviewed draft can never silently
replace a trusted schema.
"""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from src.config_loader import load_relations

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "sensor_relations"
CUSTOM_TOOL_MODEL_TEMPLATE = """\
# Tool model — edit the values after each comment.
# Signals are the only columns FabAgent reads. Use the exact CSV header names.
tool:
  # A short id and a name the user sees.
  name: custom_tool
  label: Custom tool
  description: "Replace with the tool manual, calibration source, or engineer review."

baseline:
  # What "normal" means:
  #   lead_in      = first N rows of this file
  #   nominal_file = a separate, known-good CSV (add `file: path.csv`)
  mode: lead_in
  rows: 50

signals:
  # One line per sensor. `label` is what the UI shows; `unit: null` means unknown.
  # `alert_at` is the robust-z sensitivity. 3.5 is the product default.
  - {name: sensor_a, label: Sensor A, unit: null, alert_at: 3.5}
  - {name: sensor_b, label: Sensor B, unit: null, alert_at: 3.5}

checks:
  # A check is one fault pattern. All `must_be_unusual` signals must move.
  # If any `must_stay_normal` signal moves, the result is Sensors Disagree.
  # No checks means no diagnosis: the next run stays Unknown Machine.
  - id: custom_fault
    label: Custom configured fault
    kind: equipment_fault
    must_be_unusual:
      - {signal: sensor_a, direction: any}
      - {signal: sensor_b, direction: any}
    must_stay_normal: []
    action: INSPECT_COMPONENT
    advice: Inspect the part before changing the recipe.
"""
_CONFIG_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class DraftConfigError(ValueError):
    """Raised when a draft cannot be safely promoted to a saved config."""


def slugify_config_name(name: str) -> str:
    """Return a safe lowercase config filename stem, or raise."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug or not _CONFIG_NAME.match(slug):
        raise DraftConfigError(
            "Use a name starting with a letter, then letters, digits, or "
            "underscores (max 64 characters)."
        )
    return slug


def validate_draft_yaml(draft_yaml: str) -> None:
    """Reject a draft that the real config loader cannot read.

    The draft is validated through the same ``load_relations`` path the engine
    uses. No file is written here.
    """
    if not draft_yaml.strip():
        raise DraftConfigError("The draft config is empty.")
    with TemporaryDirectory() as temp_dir:
        candidate = Path(temp_dir) / "draft.yaml"
        candidate.write_text(draft_yaml, encoding="utf-8")
        try:
            load_relations(candidate)
        except (ValueError, yaml.YAMLError, OSError) as exc:
            message = str(exc)
            if "unknown keys" in message and (
                "baseline" in message or "checks" in message or "tool" in message
            ):
                raise DraftConfigError(
                    "The running Streamlit server loaded an older config loader. "
                    "Restart it once (`Ctrl+C`, then "
                    "`streamlit run src/ui/app.py`); the tool model itself is fine."
                ) from exc
            raise DraftConfigError(f"Draft config did not load: {message}") from exc


def save_draft_config(
    draft_yaml: str,
    name: str,
    *,
    config_dir: str | Path = DEFAULT_CONFIG_DIR,
    overwrite: bool = False,
) -> Path:
    """Save a validated experimental draft as a sensor-relations config."""
    slug = slugify_config_name(name)
    validate_draft_yaml(draft_yaml)
    target = Path(config_dir) / f"{slug}.yaml"
    if target.exists() and not overwrite:
        raise DraftConfigError(
            f"{target.name} already exists. Choose another name or confirm replacement."
        )
    target.write_text(draft_yaml, encoding="utf-8")
    return target
