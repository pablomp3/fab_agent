from __future__ import annotations

import csv
from pathlib import Path

_XMEAS_NAMES = tuple(f"XMEAS({i})" for i in range(1, 42))
_XMV_NAMES = tuple(f"XMV({i})" for i in range(1, 13))


def _read_dat(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(line.split("\t"))
    return rows


def convert_idv(raw_dir: Path, processed_dir: Path, idv: int) -> Path:
    """Convert IDV y.dat/u.dat into a CSV with the three monitored signals."""
    case_dir = raw_dir / f"IDV{idv}" / f"idv{idv}"
    y_rows = _read_dat(case_dir / "y.dat")
    u_rows = _read_dat(case_dir / "u.dat")
    if len(y_rows) != len(u_rows):
        raise ValueError(f"IDV{idv}: y.dat and u.dat row counts differ")
    selected = ("XMEAS(1)", "XMV(3)", "XMEAS(7)")
    indices = {
        "XMEAS(1)": _XMEAS_NAMES.index("XMEAS(1)"),
        "XMV(3)": _XMV_NAMES.index("XMV(3)"),
        "XMEAS(7)": _XMEAS_NAMES.index("XMEAS(7)"),
    }
    out_path = processed_dir / f"IDV{idv}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(selected)
        for y_row, u_row in zip(y_rows, u_rows, strict=True):
            writer.writerow(
                [
                    y_row[indices["XMEAS(1)"]],
                    u_row[indices["XMV(3)"]],
                    y_row[indices["XMEAS(7)"]],
                ]
            )
    return out_path


def make_nominal(csv_path: Path, rows: int) -> Path:
    """Write the first `rows` of a CSV as a nominal baseline file."""
    out_path = csv_path.with_stem(f"{csv_path.stem}_nominal")
    with csv_path.open(encoding="utf-8", newline="") as src:
        reader = csv.reader(src)
        header = next(reader)
        selected = [header] + [next(reader) for _ in range(rows)]
    with out_path.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.writer(dst)
        writer.writerows(selected)
    return out_path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    raw = root / "benchmarks" / "datasets" / "tep" / "raw"
    processed = root / "benchmarks" / "datasets" / "tep" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    for idv in (1, 2, 3, 4, 5, 6, 7, 9, 14, 15):
        case_csv = convert_idv(raw, processed, idv)
        make_nominal(case_csv, rows=6)
        print(f"IDV{idv}: {case_csv} + nominal")
