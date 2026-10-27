# FabAgent documentation

This is the canonical documentation set. Old handoffs, Gemini/Codex critiques,
and the previous evaluation sheets were moved to a git-ignored archive to keep
the product surface small and coherent.

## Read in this order

| File | Purpose | Audience |
|---|---|---|
| [`../README.md`](../README.md) | Product overview, quickstart, honest limitations | Judges, new users |
| [`PRODUCT.md`](PRODUCT.md) | What FabAgent is, who it is for, the two modes | Judges, product |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Current and hybrid architecture, contracts, invariants | Implementers |
| [`HYBRID_IMPLEMENTATION.md`](HYBRID_IMPLEMENTATION.md) | **Implementation entrypoint and prompt** for the hybrid build | The next implementing LLM |
| [`UI_VOCABULARY.md`](UI_VOCABULARY.md) | Canonical user-facing words; what never to show | UI implementers |
| [`YAML_GUIDE.md`](YAML_GUIDE.md) | Simplified tool model; what users edit | Engineers, implementers |
| [`EVALUATION.md`](EVALUATION.md) | Fair benchmark vs Gemini/ChatGPT/Nemotron; metrics and rules | Implementers, judges |
| [`DATASETS.md`](DATASETS.md) | PHM 2018, TEP, synthetic twin; sample rules and limits | Implementers, judges |
| [`STATUS.md`](STATUS.md) | What is verified, what is broken, what is next | Implementers |
| [`ANTI_GOALS.md`](ANTI_GOALS.md) | Hard prohibitions | Everyone |
| [`SUBMISSION.md`](SUBMISSION.md) | Hackathon checklist, track, video, deployment | Pablo |

## Source-of-truth rules

1. **The product definition is `README.md` + `PRODUCT.md`.**
2. **The implementation contract is `HYBRID_IMPLEMENTATION.md` + `ARCHITECTURE.md`.**
3. **The user-facing words are `UI_VOCABULARY.md`.** If a term is not in that
   file, do not show it to a user.
4. **The YAML contract is `YAML_GUIDE.md`.** There is one user-facing tool-model
   schema. Legacy v1 fixtures are internal to the benchmark tests only.
5. **The benchmark contract is `EVALUATION.md`.** No number goes in the UI or
   README unless it is in a committed artifact and follows the fairness rules.
6. **`STATUS.md` is the only status document.** Old handoffs are historical and
   must not be treated as current.

## UI docs that the app reads at runtime

The Streamlit app reads these files directly. Keep the filenames and keep them
short enough to render in one screen:

- [`ui/about.md`](ui/about.md)
- [`ui/models.md`](ui/models.md)
- [`ui/performance.md`](ui/performance.md)
- [`ui/contact.md`](ui/contact.md)
- [`ui/verdicts.md`](ui/verdicts.md)
- [`ui/yaml_guide.md`](ui/yaml_guide.md)

## What was archived

The old root-level `IMPLEMENTATION_STATUS_HANDOFF.md`, `handoff.md`,
`status_readme_gemini_*`, `UI_CRITIQUE_AND_FIX_PLAN.md`,
`INSTRUCTIONS_FOR_CODEX.md`, `kickoff_prompt.md`, `KNOWN_CHALLENGES.md`,
`design_v0.md`, `implementation_context.md`, `anti_goals.md`,
`HOW_IT_WORKS*.md`, `SUGGESTED_ACTIONS.md`, `dataset_validation_defense.md`,
`last_response_from_llm.md`, `other_hackaton_winners.md`, and the old
`docs/evaluation/naive_llm_benchmarks/` sheets are in
`.archive/2026-10-26/` (inside the repo, git-ignored). They are historical; do
not copy them back into the product without condensing them first.
