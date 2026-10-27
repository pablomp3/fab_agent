# Fair benchmark experiment — phm_coolant_coverage (evidence track)

**Provider:** ChatGPT  \
**Track:** same bounded evidence (Track A)  \
**Case id (operator only; never put this in the prompt):** `phm_coolant_coverage`

## 1. Open the model interface

Track A is text-only: do **not** upload the CSV. The prompt contains the same
bounded evidence summary that FabAgent's model sees. Paste the prompt in a new
conversation.

## 2. Paste this prompt verbatim

```text
You are a semiconductor fab process and reliability engineer performing root-cause analysis on one tool export. Return only one JSON object with the requested fields. Do not assume the tool is healthy or faulty.

You are a fab engineer reviewing one tool export. You have a bounded evidence summary, not the raw rows.

Evidence summary:
{"evidence":[{"evidence_id":"EV_D0C6F06DF895BA55","signal":"FLOWCOOLFLOWRATE","kind":"SENSOR_ANOMALY","value":1172.3183180463072,"threshold":3.5,"window":[1,1000]},{"evidence_id":"EV_C2B0F2537A3E2C68","signal":"FLOWCOOLPRESSURE","kind":"SENSOR_ANOMALY","value":691.3575225554899,"threshold":3.5,"window":[1,1000]},{"evidence_id":"EV_0A34FA7188724BC5","signal":"IONGAUGEPRESSURE","kind":"SENSOR_ANOMALY","value":11.276491436942127,"threshold":3.5,"window":[1,1000]},{"evidence_id":"EV_8C64CBA7FF46A632","signal":"ETCHBEAMVOLTAGE","kind":"SENSOR_ANOMALY","value":604.8875692334616,"threshold":3.5,"window":[1,1000]},{"evidence_id":"EV_104DD4EC49FA8098","signal":"ETCHBEAMCURRENT","kind":"SENSOR_ANOMALY","value":2858.7383626489773,"threshold":3.5,"window":[1,1000]},{"evidence_id":"EV_2A76BFB37598611B","signal":"ETCHSUPPRESSORVOLTAGE","kind":"SENSOR_ANOMALY","value":884.5620539222213,"threshold":3.5,"window":[1,1000]},{"evidence_id":"EV_EB2AE213A64AFEA3","signal":"ETCHSUPPRESSORCURRENT","kind":"SENSOR_NOMINAL","value":0.0,"threshold":3.5,"window":[1,1000]}]}

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
benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/phm_coolant_coverage.txt
```

Then score it:

```sh
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark \
  --provider openai --track evidence --case phm_coolant_coverage \
  --ingest benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/phm_coolant_coverage.txt --out benchmarks/evaluator/results/naive_llm/2026-10-26
```

## 4. Record the condition

In the response file, add a first line only if you need to record tool use, for
example `# tools: vendor-default` or `# tools: none`. The parser ignores lines
before the JSON answer. Do not add a diagnosis or a score.
