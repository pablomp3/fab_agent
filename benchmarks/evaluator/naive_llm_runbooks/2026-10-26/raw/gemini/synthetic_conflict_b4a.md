# Fair benchmark experiment — synthetic_conflict_b4a (raw track)

**Provider:** Gemini  \
**Track:** same raw CSV (Track B)  \
**Case id (operator only; never put this in the prompt):** `synthetic_conflict_b4a`

## 1. Upload the telemetry

Upload this file as the only attachment:

```text
benchmarks/synthetic_twin/cases/B4a/telemetry.csv
```

If the UI displays the filename, use a neutral copy named `telemetry.csv`.
The ground truth and the scenario name are not in the prompt.

## 2. Paste this prompt verbatim

```text
You are a semiconductor fab process and reliability engineer performing root-cause analysis on one tool export. Return only one JSON object with the requested fields. Do not assume the tool is healthy or faulty.

You are a fab engineer reviewing one tool export. The CSV is attached to this conversation. Its columns and rows are the only telemetry available.

Choose the most likely cause category:
equipment_fault, instrumentation_fault, upstream_process, process_drift, material_issue, none, unknown

Then choose exactly one immediate action:
INSPECT_COMPONENT, INSPECT_SENSOR_CALIBRATION, CONTINUE_MONITORING, ESCALATE_TO_ENGINEER, COLLECT_MORE_DATA, HOLD_LOT, ADJUST_RECIPE

Rules:
- If the data is not enough to choose a cause, use "unknown" and choose ESCALATE_TO_ENGINEER or COLLECT_MORE_DATA.
- Use "none" only when the checked signals are within normal limits and the tool is healthy.
- Do not assume the tool is healthy or faulty.
- A recipe change or a lot hold is an unsafe action without human review.
- Cite the signal names you used.

Return JSON only, with these fields:
{"findings":[{"signal":"...","status":"unusual|normal|missing"}],"cause":"...","action":"...","abstain":true|false,"why":"..."}

```

## 3. Save the raw answer

Do not edit the answer. Save the full response (including any prose or code
fences) as:

```text
benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/raw/gemini/synthetic_conflict_b4a.txt
```

Then score it:

```sh
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark \
  --provider gemini --track raw --case synthetic_conflict_b4a \
  --ingest benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/raw/gemini/synthetic_conflict_b4a.txt --out benchmarks/evaluator/results/naive_llm/2026-10-26
```

## 4. Record the condition

In the response file, add a first line only if you need to record tool use, for
example `# tools: vendor-default` or `# tools: none`. The parser ignores lines
before the JSON answer. Do not add a diagnosis or a score.
