# Fair benchmark experiment — phm_nominal (evidence track)

**Provider:** ChatGPT  \
**Track:** same bounded evidence (Track A)  \
**Case id (operator only; never put this in the prompt):** `phm_nominal`

## 1. Open the model interface

Track A is text-only: do **not** upload the CSV. The prompt contains the same
bounded evidence summary that FabAgent's model sees. Paste the prompt in a new
conversation.

## 2. Paste this prompt verbatim

```text
You are a semiconductor fab process and reliability engineer performing root-cause analysis on one tool export. Return only one JSON object with the requested fields. Do not assume the tool is healthy or faulty.

You are a fab engineer reviewing one tool export. You have a bounded evidence summary, not the raw rows.

Evidence summary:
{"evidence":[{"evidence_id":"EV_B15F8C0B3722DF87","signal":"FLOWCOOLFLOWRATE","kind":"SENSOR_NOMINAL","value":2.959543721294817,"threshold":3.5,"window":[1,900]},{"evidence_id":"EV_C724280B1C50317E","signal":"FLOWCOOLPRESSURE","kind":"SENSOR_NOMINAL","value":2.532100865490184,"threshold":3.5,"window":[1,900]},{"evidence_id":"EV_7F9C043C56BA648B","signal":"IONGAUGEPRESSURE","kind":"SENSOR_NOMINAL","value":2.7241687409105952,"threshold":3.5,"window":[1,900]},{"evidence_id":"EV_3C36C31C2F45CF70","signal":"ETCHBEAMVOLTAGE","kind":"SENSOR_NOMINAL","value":1.632477137982313,"threshold":3.5,"window":[1,900]},{"evidence_id":"EV_8691652E5B2F7FCD","signal":"ETCHBEAMCURRENT","kind":"SENSOR_NOMINAL","value":3.372448750980409,"threshold":3.5,"window":[1,900]},{"evidence_id":"EV_EFD692FD7AE2AB4B","signal":"ETCHSUPPRESSORVOLTAGE","kind":"SENSOR_NOMINAL","value":1.4721472581604245,"threshold":3.5,"window":[1,900]},{"evidence_id":"EV_31DD05DF9C621C57","signal":"ETCHSUPPRESSORCURRENT","kind":"SENSOR_NOMINAL","value":0.0,"threshold":3.5,"window":[1,900]}]}

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
benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/phm_nominal.txt
```

Then score it:

```sh
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark \
  --provider openai --track evidence --case phm_nominal \
  --ingest benchmarks/evaluator/naive_llm_runbooks/2026-10-26/responses/evidence/openai/phm_nominal.txt --out benchmarks/evaluator/results/naive_llm/2026-10-26
```

## 4. Record the condition

In the response file, add a first line only if you need to record tool use, for
example `# tools: vendor-default` or `# tools: none`. The parser ignores lines
before the JSON answer. Do not add a diagnosis or a score.
