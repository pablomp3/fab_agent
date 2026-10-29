# Status — 2026-10-29

This is the current verified state of the repository. Older build journals and
handoffs are in the local, git-ignored `.archive/` and are not part of the
product.

## Verified

| Check | Command | Result |
|---|---|---|
| Unit tests | `.venv/bin/python -m unittest discover -s tests -q` | 205 tests, OK |
| Lint | `.venv/bin/ruff check .` | clean |
| Types | `.venv/bin/basedpyright` | 0 errors, 0 warnings |
| Adversarial abstention | `PYTHONPATH=. .venv/bin/python benchmarks/evaluator/synthetic_abstention_runner.py` | GREEN, 0 LLM calls |
| Offline PHM path | `PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.dossier_e2e_runner --offline` | passes |
| Experimental path | `PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.experimental_e2e_runner` | passes |
| Four-case suite | `PYTHONPATH=. .venv/bin/python -m benchmarks.evaluator.e2e_suite_runner` | safe 4/4, experimental 4/4 |

The exact counts can change when tests are added; the commands are the source of
truth, not the number in this table.

## What is in the repository

- The deterministic engine: DuckDB median/MAD, typed evidence, coverage,
  contradiction handling, a closed action enum, and fail-closed routing.
- The v2 tool model: `tool`, `baseline`, `signals`, and `checks` in one YAML
  file. The legacy v1 loader remains only for internal benchmark fixtures.
- The UI: six result words, differential table, bounded Nemotron calls,
  Tavily research on uncertain results, a collapsed technical audit, and live
  per-model/Tavily usage counters.
- Two model roles: `nvidia/Nemotron-3-Ultra-550b-a55b` for unknown-machine
  mapping and `nvidia/Nemotron-3_5-Lightning` for cause finding, challenge, and
  explanation.
- The offline demo: same engine and UI with deterministic fixture transports.
- The fair-benchmark runner and the committed `2026-10-28` artifacts in
  `benchmarks/evaluator/results/naive_llm/2026-10-28/`.

## Current limits

1. **No field validation.** Public and synthetic datasets test the reasoning
   pattern, not a modern fab’s physics.
2. **The hosted UI cannot persist a promoted tool model.** A visitor can
   download a draft YAML; saving a shared model is a deliberate repository or
   deployment step.
3. **The benchmark is a workflow comparison.** The naive models see the bounded
   evidence but not the saved tool-model checks. Do not describe it as a pure
   gate ablation.
4. **The live challenge can vary.** Nemotron may propose a different
   disconfirming test; a valid test can downgrade a confirmed check. Re-run a
   take instead of editing the result.
5. **TEP is a chemical reactor, not a fab tool.** It is cross-industry proof;
   lead with the semiconductor/PHM context.

## Before publishing

- Restart the Streamlit process after code changes.
- Open the hosted URL in an incognito window and confirm the sidebar shows live
  Nemotron and live Tavily.
- Keep `NEBIUS_API_KEY` and `TAVILY_API_KEY` server-side. Never show `.env`,
  `/etc/fabagent.env`, terminal history, or raw completions in the video.
- Put the public video URL in `docs/ui/contact.md`.

## Repository hygiene

- Do not commit `.archive/`, `.venv/`, `.env`, `.streamlit/secrets.toml`, the
  private deployment runbook, raw datasets, or private ground truths.
- A number in the README or UI must trace to a committed artifact in
  `benchmarks/evaluator/results/`.
- `src/core/` stays free of benchmark IDs, model IDs, network access, and UI
  imports.
