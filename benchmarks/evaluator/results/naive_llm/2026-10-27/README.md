# Naive-LLM benchmark — 2026-10-27

Measured on the fixed eight-case set in `benchmarks/evaluator/cases.yaml`,
evidence track, neutral prompt. `summary.json` is the committed aggregate;
`manifest.json` records the prompt/config hashes.

| System | Unsafe action rate | Correct cause | Appropriate abstention | False alarm | n |
|---|---:|---:|---:|---:|---:|
| FabAgent (deterministic gate reference) | 0.00 | 1.00 | 1.00 | 0.00 | 8 |
| Nemotron-only (evidence track, live) | 0.50 | 0.14 | 0.00 | 1.00 | 8 |

Two honesty notes:

- The FabAgent row is the **deterministic gate reference**, not a live Nemotron
  narrative run. The gate result does not depend on the model.
- The naive prompt receives the same bounded evidence but not the saved
  tool-model checks. This is a **workflow comparison** (engineer-authored checks
  + Python gate vs. zero-shot model), not a pure gate ablation. See
  `docs/EVALUATION.md` §8.

The old five-case `naive_llm_baseline.json` is a different case set and is not
comparable; it is not used in the eight-case table.
