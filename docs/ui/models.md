# How Nemotron and Tavily are used

FabAgent uses two external services, and both are optional. The Python gate works
without either one.

## NVIDIA Nemotron through Nebius Token Factory

Nemotron is the **narrative generator**, not the decision maker.

- It receives a bounded evidence summary: channel names, robust statistics,
  verdict-relevant predicates, and a short engineer note.
- It returns a proposed explanation with evidence IDs.
- Python resolves every cited ID, reapplies the configured candidate, and owns
  the verdict and next action.
- If the model is unavailable or returns invalid JSON, the deterministic gate
  still runs and the failure is recorded as a sanitized category.

The model never receives the raw CSV, the full telemetry table, or an API key.

## Tavily search

Tavily is an **optional external reference lookup** for the engineer. It runs
only when the result is inconclusive or experimental.

- The query is built from anomalous signal names and the configured claim.
- It does **not** include raw values, the full engineer note, or telemetry.
- Up to three public references are shown with their URLs and why they were
  consulted.
- References are not evidence. They cannot change the verdict, citations, or
  action.

## What is sent

| Service | Sent | Not sent |
| --- | --- | --- |
| Nemotron | Bounded evidence summary, short engineer note, configured candidate context | Raw CSV, full telemetry, API key |
| Tavily | Anomalous signal names and the configured claim | Raw values, full engineer note, telemetry |

Provider keys stay in the server environment. The browser never receives them.
