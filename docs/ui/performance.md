# FabAgent vs a naive LLM

This is a small, deliberately narrow comparison. It is not a broad benchmark.

| System | Safe decisions | What happened |
| --- | ---: | --- |
| Naive LLM | **2 / 5** | Took an immediate action on three cases where the evidence did not support it. |
| FabAgent gate | **4 / 4** | Abstained or vetoed on four adversarial cases; no autonomous action. |

The naive baseline used the same live Nemotron route and the same five cases.
The three unsafe decisions were B4b, B4c, and B4d. The FabAgent gate is
deterministic: it checks the configured candidate, required evidence, and
contradiction rules before any action is offered.

## What this does and does not show

- It shows the difference between a narrative and an evidence-gated decision.
- It does not show field accuracy, uptime, or performance on every tool.
- The public PHM 2018 and TEP samples are demonstration slices, not a
  production validation set.

The comparison artifact is stored in
`benchmarks/evaluator/results/naive_llm_baseline.json`. The adversarial gate
check is stored in `benchmarks/evaluator/results/w3_adversarial_check.json`.
