# FabAgent vs naive LLM: a fair benchmark

> **TL;DR:** We measure **safe decisions**, not “decisiveness”. The old 100% vs 0%
> table was based on prompts that leaked the scenario and the answer; it is not
> used. The new protocol is in [`../EVALUATION.md`](../EVALUATION.md); the summary
> is filled only after a run that follows it.

---

## The operational challenge

In high-consequence manufacturing:

- **False alarms** waste time and can lead to unnecessary tool downtime.
- **Unsafe actions** — a recipe change or a lot hold on a single noisy channel —
  can scrap product.
- **Silent overconfidence** — a fluent answer that names a cause without checking
  the companions is worse than an honest “not enough data”.
- **Alert fatigue** — a system that escalates every routine run gets turned off.

The right target is not “always decide”. It is: **decide when the evidence
supports it, check the sensor when it disagrees, and abstain when the data is not
enough.**

---

## What we compare

| System | Same evidence? | Same model? | Gate? |
| --- | --- | --- | --- |
| **FabAgent** | yes | Nemotron | **yes** |
| **Nemotron-only** | yes | yes | no |
| **Gemini** | yes | no | no |
| **ChatGPT** | yes | no | no |

The target is the **ablation**: same Nemotron model, same evidence, with and
without the Python gate. The committed 2026-10-27 run is the first step: the
FabAgent row is the deterministic gate reference, and the Nemotron-only row is
live. The naive prompt does not receive the saved tool-model checks, so this is
a workflow comparison, not yet the pure gate ablation.

The protocol uses the same bounded evidence summary, the same neutral prompt, and
the same action menu for every system. The prompt does not name the dataset, the
scenario, the cause, or the expected action.

---

## Metrics

| Metric | Better |
| --- | --- |
| **Unsafe action rate** — hold lot / adjust recipe on any case, or inspect the part on a nominal/conflict case | lower |
| **Correct cause rate** — category matches the ground truth on attribution cases | higher |
| **Appropriate abstention** — “not enough data” on unmodeled/missing cases | higher |
| **False-alarm rate** — a fault on the nominal case | lower |
| **Evidence accuracy** — cited evidence IDs resolve and support the claim | higher |

Latency and cost are reported as secondary numbers, not the headline.

---

## Current status

| System | Unsafe action rate | Correct cause | Appropriate abstention | False alarm | n |
| --- | --- | --- | --- | --- | --- |
| **FabAgent** (deterministic gate reference) | **0.00** | **1.00** | **1.00** | **0.00** | 8 |
| **Nemotron-only** (live, evidence track) | 0.50 | 0.14 | 0.00 | 1.00 | 8 |
| Gemini | *run pending* | *pending* | *pending* | *pending* | 8 |
| ChatGPT | *run pending* | *pending* | *pending* | *pending* | 8 |

Measured on 2026-10-27; aggregate in
`benchmarks/evaluator/results/naive_llm/2026-10-27/summary.json`.

Two honesty notes:

- The FabAgent row is the **deterministic gate reference** (the verdict does not
  depend on a model narrative), while the Nemotron-only row is live.
- The naive prompt gets the same bounded evidence but **not** the saved
  tool-model checks. This is a workflow comparison (engineer-authored checks +
  gate vs. zero-shot model), not a pure gate ablation.

The old Nemotron-only **2/5 safe** baseline used five different synthetic cases;
it is not comparable to the fixed eight-case set and is not shown in this table.

---

## What this does not prove

- It does not prove field accuracy on a modern fab.
- It does not prove that one model is generally better than another.
- It does not prove that the benchmark cases cover every failure mode.

It does show whether the **decision procedure** — same evidence, same action menu
— makes safer choices on a fixed, balanced case set. That is the claim.

---

## Reproduce it

```sh
# print the neutral prompt for a manual Gemini/ChatGPT run
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark --case 1 --track evidence --print-prompt

# ingest a pasted response
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark --case 1 --provider gemini --ingest response.txt

# API run (keys from env; never logged)
.venv/bin/python -m benchmarks.evaluator.naive_llm_benchmark --provider gemini --track evidence --out results/
```

The ready-to-run Gemini/ChatGPT sheets are in
`benchmarks/evaluator/naive_llm_runbooks/2026-10-26/evidence/` (same bounded
evidence) and `.../raw/` (same uploaded CSV). Each sheet ends with the exact
`--ingest` command.

Each run stores the prompt, the input hash, the model version/date, the raw
output, the parsed action, and the score. A missing or unparsable output is
recorded as a failure, not dropped.
