# FabAgent documentation

This is the canonical documentation set. Superseded build journals, handoffs,
and review notes are kept in the local, git-ignored `.archive/` so the public
product surface stays small and coherent.

## Read in this order

| File | Purpose | Audience |
|---|---|---|
| [`../README.md`](../README.md) | Product overview, quickstart, honest limitations | Judges, new users |
| [`PRODUCT.md`](PRODUCT.md) | What FabAgent is, who it is for, the two modes | Judges, product |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Current architecture, contracts, invariants | Implementers |
| [`UI_VOCABULARY.md`](UI_VOCABULARY.md) | Canonical user-facing words; what never to show | UI implementers |
| [`YAML_GUIDE.md`](YAML_GUIDE.md) | Simplified tool model; what users edit | Engineers, implementers |
| [`EVALUATION.md`](EVALUATION.md) | Fair benchmark vs Gemini/ChatGPT/Nemotron; metrics and rules | Implementers, judges |
| [`DATASETS.md`](DATASETS.md) | PHM 2018, TEP, synthetic twin; sample rules and limits | Implementers, judges |
| [`STATUS.md`](STATUS.md) | What is verified and what is still limited | Implementers |
| [`DEPLOY.md`](DEPLOY.md) | Nebius VM, Docker, systemd, the pre-video checklist | Operators |
| [`ANTI_GOALS.md`](ANTI_GOALS.md) | Hard prohibitions | Everyone |
| [`SUBMISSION.md`](SUBMISSION.md) | Hackathon checklist, track, video, deployment | Maintainers |

## Source-of-truth rules

1. **The product definition is `README.md` + `PRODUCT.md`.**
2. **The implementation contract is `ARCHITECTURE.md`.**
3. **The user-facing words are `UI_VOCABULARY.md`.** If a term is not in that
   file, do not show it to a user.
4. **The YAML contract is `YAML_GUIDE.md`.** There is one user-facing tool-model
   schema. Legacy v1 fixtures are internal to the benchmark tests only.
5. **The benchmark contract is `EVALUATION.md`.** No number goes in the UI or
   README unless it is in a committed artifact and follows the fairness rules.
6. **`STATUS.md` is the only current status document.**

## UI docs that the app reads at runtime

The Streamlit app reads these files directly. Keep the filenames and keep them
short enough to render in one screen:

- [`ui/about.md`](ui/about.md)
- [`ui/models.md`](ui/models.md)
- [`ui/performance.md`](ui/performance.md)
- [`ui/contact.md`](ui/contact.md)
- [`ui/verdicts.md`](ui/verdicts.md)
- [`ui/yaml_guide.md`](ui/yaml_guide.md)

## Historical material

Superseded notes are in `.archive/` inside the working tree and are excluded by
`.gitignore`. They are not part of the public repository and must not be copied
back into the product without being condensed and fact-checked first.
