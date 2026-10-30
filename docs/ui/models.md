# What each layer does

## 1. Local triage — DuckDB + Python

Local triage starts before any AI model is called. DuckDB reads the machine's
sensor CSV locally on the server:

1. **Match or bootstrap** — if a saved **tool model** (a short YAML description
   of the machine) matches the CSV columns, use it; otherwise switch to Auto
   mode.
2. **Normal reference** — for a saved tool model, compute the median and MAD
   (median absolute deviation) over the machine's normal baseline window.
3. **Evidence records** — emit one record per sensor (`EV_…`): unusual, normal,
   or missing. In Auto mode, the local column profile is sent to the mapper
   first; Python validates the proposed mapping before evidence is computed. Raw
   sensor rows stay in DuckDB; only a bounded summary is sent to the model.

---

## 2. NVIDIA Nemotron — AI reasoning

Nemotron runs on **Nebius Token Factory** and does the four jobs that fixed
rules cannot do alone:

- **Column mapper** (*Day 1 cold-start*) — guesses what each column means when
  an engineer uploads a file from an unknown machine, and drafts a starter YAML
  tool model.
- **Cause finder** — proposes possible causes from the evidence IDs.
- **Challenge check** (*red-team*) — proposes the strongest disconfirming test
  for its own leading cause ("if this were really a coolant fault, which other
  sensor should have moved?").
- **Explanation** — writes the plain-language shift-handoff summary.

| Job | Model on Nebius Token Factory |
|---|---|
| Unknown-machine column mapping | `nvidia/Nemotron-3-Ultra-550b-a55b` |
| Cause finding, challenge, explanation | `nvidia/Nemotron-3_5-Lightning` |

The larger Ultra model is reserved for the one-shot unknown-machine mapping
step; interactive steps stay fast on Lightning. Every response is
schema-validated, and a failed model call leaves the Python result intact.

---

## 3. Python decision + Tavily research

Python makes the final call in a fixed sequence:

1. **Citation check** — re-resolve every `EV_…` ID the model cited; discard any
   invented ID.
2. **Coverage** — check whether every declared sensor is explained, normal, or
   flagged.
3. **Contradiction** — if a sensor that should agree stayed flat, stop at
   **Sensors Disagree**.
4. **Action** — pick one action from a fixed list: inspect the part, keep
   monitoring, check the sensor, get more data, ask an engineer, or review the
   guessed columns. Changing a **recipe** (machine settings) or holding a
   **lot** (wafer batch) is not on that list.
5. **Tavily research (only when unsure)** — when the result is inconclusive,
   conflicting, or from an unknown machine, `build_tavily_query` sends human
   sensor labels (for example `RF power`) and the fault name to Tavily. It
   returns up to three public troubleshooting links as context for the engineer,
   never as evidence for the decision.

### The 3.5z alert level and 5z coverage rule

Each sensor is compared with its normal reference using the median and MAD:

**z = 0.6745 × |value − median| / MAD**

`0.6745 = Φ⁻¹(0.75)` converts MAD to normal-equivalent standard deviations.
**3.5z** is the editable per-sensor alert level; **5z** is the coverage rule
that blocks a bare **Fault Confirmed** when another sensor has a large
unexplained spike. They are statistical screening levels, not physical
tolerances; replace 3.5 with a calibrated limit when one exists.

---

## 4. The engineer

The engineer owns the saved tool model and confirms the final action. The model
cannot replace that judgement.
