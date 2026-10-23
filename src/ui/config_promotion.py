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
            raise DraftConfigError(f"Draft config did not load: {exc}") from exc


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
            f"{target.name} already exists. Choose another name or confirm "
            "replacement."
        )
    target.write_text(draft_yaml, encoding="utf-8")
    return target
