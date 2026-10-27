# Fair benchmark experiment — synthetic_conflict_b4a (evidence track)

**Provider:** ChatGPT  \
**Track:** same bounded evidence (Track A)  \
**Case id (operator only; never put this in the prompt):** `synthetic_conflict_b4a`

## 1. Open the model interface

Track A is text-only: do **not** upload the CSV. The prompt contains the same
bounded evidence summary that FabAgent's model sees. Paste the prompt in a new
conversation.

## 2. Paste this prompt verbatim

```text
You are a semiconductor fab process and reliability engineer performing root-cause analysis on one tool export. Return only one JSON object with the requested fields. Do not assume the tool is healthy or faulty.

You are a fab engineer reviewing one tool export. You have a bounded evidence summary, not the raw rows.

Evidence summary:
{"evidence":[{"evidence_id":"EV_808E8B08A7AE04A6","signal":"sensor_17","kind":"SENSOR_ANOMALY","value":16.225015560496328,"threshold":3.5,"window":[1,120]},{"evidence_id":"EV_C82C8C454403ED8E","signal":"impedance","kind":"SENSOR_NOMINAL","value":0.9989989999268193,"threshold":3.5,"window":[1,120]},{"evidence_id":"EV_15F005EC04D59928","signal":"thermal","kind":"SENSOR_NOMINAL","value":0.9989990000460331,"threshold":3.5,"window":[1,120]},{"evidence_id":"EV_EE02D8A1E665F068","signal":"pressure","kind":"SENSOR_NOMINAL","value":0.9989990000350704,"threshold":3.5,"window":[1,120]},{"evidence_id":"EV_D7CC5E74ED79BC00","signal":"thermal_sensor","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_3906EFA048EDF8EE","signal":"flow","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_7B635F7DE56B4A29","signal":"met_cd_bias","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_3FFCE0FF35884AEF","signal":"etch_rf_power","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_9D1BA3D697E34C97","signal":"chamber_pressure","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_8E199278C29119CA","signal":"roughing_line_pressure","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null}]}

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
benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/synthetic_conflict_b4a.txt
```

Then score it:

```sh
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark \
  --provider openai --track evidence --case synthetic_conflict_b4a \
  --ingest benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/synthetic_conflict_b4a.txt --out benchmarks/evaluator/results/naive_llm/2026-10-26
```

## 4. Record the condition

In the response file, add a first line only if you need to record tool use, for
example `# tools: vendor-default` or `# tools: none`. The parser ignores lines
before the JSON answer. Do not add a diagnosis or a score.
