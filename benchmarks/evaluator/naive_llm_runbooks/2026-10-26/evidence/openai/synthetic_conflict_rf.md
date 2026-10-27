# Fair benchmark experiment — synthetic_conflict_rf (evidence track)

**Provider:** ChatGPT  \
**Track:** same bounded evidence (Track A)  \
**Case id (operator only; never put this in the prompt):** `synthetic_conflict_rf`

## 1. Open the model interface

Track A is text-only: do **not** upload the CSV. The prompt contains the same
bounded evidence summary that FabAgent's model sees. Paste the prompt in a new
conversation.

## 2. Paste this prompt verbatim

```text
You are a semiconductor fab process and reliability engineer performing root-cause analysis on one tool export. Return only one JSON object with the requested fields. Do not assume the tool is healthy or faulty.

You are a fab engineer reviewing one tool export. You have a bounded evidence summary, not the raw rows.

Evidence summary:
{"evidence":[{"evidence_id":"EV_D928127F979D0BE1","signal":"sensor_17","kind":"SENSOR_ANOMALY","value":303.52038758823784,"threshold":3.5,"window":[1,12]},{"evidence_id":"EV_90C8D2833562FE61","signal":"impedance","kind":"SENSOR_NOMINAL","value":0.0,"threshold":3.5,"window":[1,12]},{"evidence_id":"EV_E6B7D26533D0B4C8","signal":"thermal","kind":"SENSOR_NOMINAL","value":0.0,"threshold":3.5,"window":[1,12]},{"evidence_id":"EV_34797CA4434C3111","signal":"pressure","kind":"SENSOR_NOMINAL","value":0.0,"threshold":3.5,"window":[1,12]},{"evidence_id":"EV_85D9C6EB34D6B488","signal":"thermal_sensor","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_91D35199CE546F57","signal":"flow","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_D6A2D1820CC341D8","signal":"met_cd_bias","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_BAE299736991EAF6","signal":"etch_rf_power","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_342C5527755EC755","signal":"chamber_pressure","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null},{"evidence_id":"EV_51E53381F2D7154B","signal":"roughing_line_pressure","kind":"MISSING_CHANNEL","value":null,"threshold":3.5,"window":null}]}

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
benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/synthetic_conflict_rf.txt
```

Then score it:

```sh
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark \
  --provider openai --track evidence --case synthetic_conflict_rf \
  --ingest benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/synthetic_conflict_rf.txt --out benchmarks/evaluator/results/naive_llm/2026-10-26
```

## 4. Record the condition

In the response file, add a first line only if you need to record tool use, for
example `# tools: vendor-default` or `# tools: none`. The parser ignores lines
before the JSON answer. Do not add a diagnosis or a score.
