# What each layer does

## 1. NVIDIA Nemotron — AI reasoning

Nemotron has four bounded jobs:

- **Column mapper** — proposes what each column means for an unknown export.
- **Cause finder** — proposes possible causes with evidence IDs.
- **Challenge check** — proposes the strongest disconfirming test for the
  leading cause.
- **Explanation** — writes the plain-language summary.

The hosted demo uses two exact models from Nebius Token Factory:

| Job | Model |
|---|---|
| Unknown-machine column mapping | `nvidia/Nemotron-3-Ultra-550b-a55b` |
| Cause finding, challenge, explanation | `nvidia/Nemotron-3_5-Lightning` |

The larger Ultra model is reserved for the hard unknown-export mapping step;
ordinary synthesis stays fast on Lightning. The **Live runtime usage** panel on
the How it works page shows actual calls by model and by Tavily.

Every response is schema-validated. Python resolves every cited evidence ID;
unresolved citations are discarded. A failed model call leaves the deterministic
result intact.

### What the model sees

A small statistical summary, under 2 KB: signal names and engineer labels,
median/MAD-based robust z-scores, nominal/anomaly/missing flags, evidence IDs,
and the engineer's short note. It never sees the raw CSV or the API key.

---

## 2. Tavily — external research

Tavily runs only when public engineering knowledge can help:

- **When:** inconclusive, contradictory, or unknown-machine results.
- **What it sends:** anomalous sensor labels or the suspected fault label — not
  raw values, timestamps, or confidential notes.
- **What it returns:** up to three public references. They are leads for a human,
  never evidence for the gate.

---

## 3. Python + DuckDB — deterministic decision

The decision runs as a short sequence:

1. **Baseline** — a lead-in window or a saved normal run defines “normal”.
2. **Evidence** — one record per declared signal: anomaly, nominal, or missing.
3. **Coverage** — every declared signal is explained, nominal, or flagged.
4. **Contradiction** — a signal that should agree did not; this is a hard stop.
5. **Action** — a small typed enum: inspect, monitor, escalate, or collect data.

### The 3.5z alert level

Each signal is compared with the normal reference using the median and MAD:

```text
z = 0.6745 × |value − median| / MAD
```

`0.6745 = Φ⁻¹(0.75)` converts MAD to normal-equivalent sigma units. **3.5z** is
the editable per-signal alert level; **5z** is the coverage limit that blocks a
bare **Fault Confirmed** when a large signal is unexplained. They are statistical
screening levels, not physics tolerances; replace 3.5 with a calibrated limit
when one exists.

### Audit trail

Every finding has an evidence ID. The technical audit shows the raw status,
statistic, window, and bounded payload size. Unresolved model citations are
rejected and listed there.

---

## 4. The engineer

The engineer owns the saved tool model and the final action. The model cannot
replace that judgement.
