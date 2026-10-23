from __future__ import annotations

import gzip
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from src.agents.proposal_request import (
    MAX_EVIDENCE_BYTES,
    MAX_REQUEST_BYTES,
    build_proposal_request,
    evidence_summary_bytes,
)
from src.core.duckdb_exec import extract_evidence
from src.core.evidence import EvidenceStore, PayloadTooLarge, build_llm_payload
from src.core.types import SignalSpec
from src.model_config import load_model_route


def main() -> int:
    row_bytes = 10_000
    row_count = 3_000_000
    header = b"channel\n"
    row = b"1" + b" " * (row_bytes - 2) + b"\n"
    repeated_block = gzip.compress(row * 1_000, compresslevel=1, mtime=0)
    first_block = gzip.compress(header + row * 1_000, compresslevel=1, mtime=0)
    uncompressed_bytes = len(header) + row_bytes * row_count

    with TemporaryDirectory() as temporary_directory:
        csv_path = Path(temporary_directory) / "large.csv.gz"
        with csv_path.open("wb") as output:
            output.write(first_block)
            for _ in range((row_count // 1_000) - 1):
                output.write(repeated_block)
        evidence = extract_evidence(csv_path, (SignalSpec("channel"),))
        if not evidence or not evidence[0].provenance.endswith(
            f"({row_count} observations)"
        ):
            return 1
        payload = build_llm_payload(EvidenceStore(evidence))
        payload_bytes = len(payload.encode("utf-8"))
        route = load_model_route(
            Path(__file__).resolve().parents[2] / "config" / "models.yaml",
            "SYNTHESIS",
            {},
        )
        evidence_bytes = evidence_summary_bytes(evidence)
        try:
            request_body = build_proposal_request(
                route.model, evidence, ("equipment_fault",)
            )
            request_bytes: int | None = len(request_body)
        except PayloadTooLarge as exc:
            request_bytes = exc.actual_bytes
        request_ok = request_bytes is not None and request_bytes <= MAX_REQUEST_BYTES
        print(f"uncompressed_csv_bytes={uncompressed_bytes}")
        print(f"compressed_input_bytes={csv_path.stat().st_size}")
        print(f"llm_payload_bytes={payload_bytes}")
        print(f"llm_evidence_bytes={evidence_bytes}")
        print(f"llm_request_bytes={request_bytes}")
        result_path = (
            Path(__file__).resolve().parent / "results" / "w2_payload_check.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        passed = (
            uncompressed_bytes >= 30_000_000_000
            and payload_bytes <= 2_048
            and evidence_bytes <= MAX_EVIDENCE_BYTES
            and request_ok
        )
        result = {
            "gate": "W2",
            "status": "PASS" if passed else "FAIL",
            "run_at_utc": datetime.now(UTC).isoformat(),
            "uncompressed_csv_bytes": uncompressed_bytes,
            "compressed_input_bytes": csv_path.stat().st_size,
            "payload_bytes": payload_bytes,
            "payload_limit_bytes": 2_048,
            "llm_evidence_bytes": evidence_bytes,
            "llm_evidence_limit_bytes": MAX_EVIDENCE_BYTES,
            "llm_request_bytes": request_bytes,
            "llm_request_limit_bytes": MAX_REQUEST_BYTES,
            "rows": row_count,
            "channels": 1,
            "python_version": platform.python_version(),
            "duckdb_version": duckdb.__version__,
            "fixture": "synthetic constant-channel stress stream; unit unknown",
        }
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(
            f"result_file={result_path.relative_to(Path(__file__).resolve().parents[2])}"
        )
        if not passed:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
