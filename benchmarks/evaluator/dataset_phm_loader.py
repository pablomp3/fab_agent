from __future__ import annotations

import csv
from pathlib import Path

PHM_SIGNALS = (
    "FLOWCOOLFLOWRATE",
    "FLOWCOOLPRESSURE",
    "IONGAUGEPRESSURE",
    "ETCHBEAMVOLTAGE",
    "ETCHBEAMCURRENT",
    "ETCHSUPPRESSORVOLTAGE",
    "ETCHSUPPRESSORCURRENT",
)


def _read_rows(path: Path, limit: int | None = None) -> list[list[str]]:
    rows: list[list[str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows.append(header)
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            rows.append(row)
    return rows


def prepare_case(
    raw_dir: Path, processed_dir: Path, score_name: str, nominal_rows: int
) -> tuple[Path, Path]:
    """Copy a score file and write a nominal baseline from its first rows."""
    processed_dir.mkdir(parents=True, exist_ok=True)
    score_path = raw_dir / score_name
    case_path = processed_dir / score_name
    case_path.write_bytes(score_path.read_bytes())
    rows = _read_rows(score_path, limit=nominal_rows)
    nominal_path = processed_dir / f"{score_name[:-4]}_nominal.csv"
    with nominal_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    return case_path, nominal_path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    raw = root / "benchmarks" / "datasets" / "phm2018" / "raw"
    processed = root / "benchmarks" / "datasets" / "phm2018" / "processed"
    prepare_case(raw, processed, "01_M02_DC_score.csv", nominal_rows=1000)
    print("Prepared 01_M02_DC_score.csv + nominal")
