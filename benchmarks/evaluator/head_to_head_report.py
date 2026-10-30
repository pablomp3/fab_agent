"""Merge the two head-to-head summary files into the UI artifact.

The benchmark runner writes one summary per track. The UI reads a single
``head_to_head.json`` with human model labels. This script only merges existing
scored artifacts; it never calls a model and never invents a score.

    PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.head_to_head_report
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "benchmarks" / "evaluator" / "results" / "naive_llm" / "2026-10-28"
LABELS = {
    "FabAgent (deterministic gate)": "FabAgent (deterministic gate)",
    "Gemini (evidence track)": "Gemini 3.8 Flash (medium)",
    "ChatGPT (evidence track)": "GPT-5.6 Luna",
    "Gemini (raw track)": "Gemini 3.8 Flash (medium)",
    "ChatGPT (raw track)": "GPT-5.6 Luna",
}


def _load(path: Path) -> dict[str, object]:
    payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return cast(dict[str, object], payload)


def _case_ids(payload: dict[str, object]) -> list[str]:
    records = payload.get("cases")
    if not isinstance(records, list):
        return []
    found: set[str] = set()
    for item in cast(list[object], records):
        if isinstance(item, dict):
            case_id = cast(dict[str, object], item).get("case")
            if isinstance(case_id, str):
                found.add(case_id)
    return sorted(found)


def _portable(path: Path) -> str:
    """Return a repo-relative path so the committed artifact is portable."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _track(payload: dict[str, object], source: Path) -> dict[str, object]:
    systems = payload.get("systems")
    if not isinstance(systems, list):
        systems = []
    labelled: list[dict[str, object]] = []
    for item in cast(list[object], systems):
        if not isinstance(item, dict):
            continue
        entry = dict(cast(dict[str, object], item))
        entry["system"] = LABELS.get(str(entry.get("system")), entry.get("system"))
        labelled.append(entry)
    return {
        "systems": labelled,
        "cases": payload.get("cases", []),
        "source": _portable(source),
    }


def build(
    evidence_dir: Path,
    raw_dir: Path,
    out: Path,
) -> dict[str, object]:
    evidence_source = evidence_dir / "summary.json"
    raw_source = raw_dir / "summary.json"
    evidence = _load(evidence_source)
    raw = _load(raw_source)
    cases = sorted(set(_case_ids(evidence)) | set(_case_ids(raw)))
    payload: dict[str, object] = {
        "generated_at": evidence.get("generated_at"),
        "protocol": "docs/EVALUATION.md",
        "case_count": len(cases),
        "cases": cases,
        "note": (
            "Matched head-to-head on the cases completed by every system. Gemini "
            "and ChatGPT were run manually; model labels are the operator-supplied "
            "versions. The FabAgent row is the deterministic gate reference. Do "
            "not compare a partial head-to-head with the full eight-case ablation."
        ),
        "tracks": {
            "evidence": _track(evidence, evidence_source),
            "raw": _track(raw, raw_source),
        },
    }
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=DEFAULT_DIR / "head_to_head" / "evidence",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_DIR / "head_to_head" / "raw",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_DIR / "head_to_head.json")
    args = parser.parse_args(argv)
    payload = build(args.evidence_dir, args.raw_dir, args.out)
    print(f"Wrote {args.out} ({payload['case_count']} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
