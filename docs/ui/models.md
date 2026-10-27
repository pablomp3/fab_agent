# How Nemotron, Python, and Tavily work together

The product is deliberately split into a **decision layer** and a
**helper layer**.

| Layer | What it owns | What it must never do |
| --- | --- | --- |
| **Python + DuckDB** | Normal reference, statistics, evidence IDs, coverage, contradictions, the six results, the typed action | Invent physics, units, sensor names, or a threshold |
| **NVIDIA Nemotron** | Column mapping, cause proposals, the disconfirming challenge, the explanation | Choose the result, choose the action, or cite evidence Python did not produce |
| **Tavily** | Public troubleshooting leads when the data is uncertain | Become evidence or alter the gate |
| **The engineer** | The saved tool model and the final action | Be replaced by the model |

> **The rule:** the model proposes; Python checks; the engineer decides.

---

## 1. NVIDIA Nemotron on Nebius Token Factory

Nemotron has four narrow jobs:

- **Column mapper** — proposes what each column means for an unknown export.
- **Cause finder** — proposes possible causes with evidence IDs.
- **Challenge check** — proposes the strongest disconfirming test for the
  leading cause.
- **Explanation** — writes the one-paragraph summary.

Every response is schema-validated and bounded. Python resolves every cited
evidence ID; unresolved citations are discarded. A failed model call still
leaves the deterministic result intact.

### What the model sees

A small statistical summary, under 2 KB:

- signal names and engineer labels,
- median/MAD-based robust z-scores,
- nominal / anomaly / missing flags,
- evidence IDs,
- the engineer's short note.

It never sees the raw CSV, the full rows, the API key, or the browser.

---

## 2. The deterministic core

The result is computed by Python, not by the model:

```
baseline → evidence → coverage → fault checks → gate → typed action
```

- **Baseline:** a lead-in, a separate normal file, or a recipe step.
- **Evidence:** one record per declared signal: anomaly, nominal, or missing.
- **Coverage:** every declared signal is explained, nominal, contradicted, or
  unexplained. A large unexplained movement prevents a bare **Fault Confirmed**.
- **Contradiction:** a signal that should stay normal moved, or the signals that
  should agree did not. This is a hard veto.
- **Action:** a small typed enum. No recipe change, no lot hold.

---

## 3. Tavily

Tavily is a bounded research assistant for the cases where public engineering
knowledge helps:

- **When it runs:** only on inconclusive, contradictory, or unknown-machine
  results.
- **What it sends:** anomalous sensor labels or the suspected fault label, not
  raw values, timestamps, or confidential notes.
- **What it returns:** up to three public references. They are leads for a
  human, never evidence for the gate.

---

## 4. Why this architecture is safer

A fluent answer is not a safe answer. The risky failure is a confident recipe
change or tool stop on a single noisy channel.

FabAgent makes that failure structurally hard:

- a contradiction cannot be outvoted;
- a missing required channel is **Data Incomplete**, not silence;
- a model-proposed cause without a saved check is **Needs Review**;
- the action enum cannot represent a recipe change or a lot hold;
- every result has an evidence trail and a human confirmation.

That is the product: **useful AI with a deterministic brake.**
