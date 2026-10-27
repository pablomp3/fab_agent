# Naive-LLM experiment kit — raw track

This directory contains copy/paste sheets for Gemini and ChatGPT for the
balanced case set in `benchmarks/evaluator/cases.yaml`. The prompts are neutral:
no case name, dataset name, scenario, alarm note, cause, or expected action.

## Cases

- `phm_coolant_coverage`
- `phm_nominal`
- `tep_feed_disturbance`
- `tep_unmodeled`
- `synthetic_conflict_b4a`
- `missing_coolant_flow`
- `synthetic_positive_b4e`
- `synthetic_conflict_rf`

## Method

For each provider and case:

1. Open `gemini/<case>.md` or `openai/<case>.md`.
2. Upload the telemetry file the sheet names.
3. Paste the prompt exactly.
4. Save the raw response under `responses/raw/<provider>/<case>.txt`.
5. Score it with the command in the sheet.

Each ingest writes a per-case artifact and refreshes `summary.json` under:

```text
benchmarks/evaluator/results/naive_llm/2026-10-26
```

A missing or unparsable response is recorded as a failure, not dropped. The
runner never prints keys or raw completions.

## Other track

Generate the other track with `--runbook-track evidence` or `--runbook-track raw`.
The raw prompt does not contain any scenario description either.

## Protocol

See `docs/EVALUATION.md`. Do not quote a number until `summary.json` exists and
the per-case artifacts are committed.
