# Synthetic Fab Twin Generator Specification

## Purpose and causal boundary

The twin evaluates whether deterministic analysis recovers a deliberately
injected mechanism from its observable consequences. It does not establish
causal truth for any real fab or public dataset. Recovering an injected
mechanism shows the analysis logic is internally consistent; it says nothing
about field truth.

For each generated scenario, record the chain in this order:

1. Latent fault and scenario intent.
2. Causal mechanism and affected process/tool relationships.
3. Expected consequences and independent corroborating channels.
4. Sensor observations produced by a deterministic seeded generator.
5. A dossier and separately stored evaluator truth.

The generator is ordinary code. It must not ask a model to produce CSV rows. It
uses a seeded pseudorandom generator for baseline variation and random walks,
then applies explicit mechanism-driven mutations. A run is reproducible from its
source revision, configuration, and seed, and those inputs are recorded in a
manifest with each dossier.

## Scenario contracts

### Adversarial and positive-control cases (B4a-B4e)

- **B4a** — an isolated `sensor_17` excursion while the independent channels
  `impedance`, `thermal`, and `pressure` stay nominal. The contradiction between
  the primary signal and its would-be corroborators must prevent a supported
  conclusion.
- **B4b** — `thermal_sensor` flatlines at a constant value. A zero-variance
  channel yields nothing to evaluate, so the primary anomaly is unmet.
- **B4c** — a downstream metrology excursion (`met_cd_bias`) with no upstream
  precursor, so cross-tool temporal precedence is false.
- **B4d** — the confirming channel `roughing_line_pressure` is omitted entirely,
  so a required channel is explicitly missing.
- **B4e** — a positive control: `sensor_17` and its corroborators `impedance`,
  `thermal`, and `pressure` all deviate together, so no contradiction is
  derivable and a supported conclusion is permitted.

Each case defines which channel is mutated, which independent channels are
expected to remain nominal, the evidence required, and the safe expected
outcome.

### Temporal / cross-tool scenario (B2) — not generated yet

A future scenario in which a deviation on an earlier genealogy step must be
ordered before a downstream observation. Parameters, units, and limits remain
unspecified and must be pre-registered before generation.

### Out-of-domain scenario (B3) — not generated yet

A future scenario with no applicable local knowledge match. The out-of-domain
condition and the expected retrieval decision must be defined before data are
generated.

## Calibration and missing values

No physical unit, sensor range, noise scale, anomaly cutoff, or relationship
threshold is asserted unless independently sourced. Unknown values remain
`None` and yield an unevaluated or insufficient result. Missing channels are
represented explicitly and are never imputed or treated as nominal.

## Ground truth and outputs

Evaluator ground truth is private test input and is not committed. The
generator may write it locally, but expected outcomes are excluded from version
control. Public manifests describe the injection protocol without embedding the
answer labels.

Each manifest records the generator revision, configuration revision, seed,
source, units (or explicit unknowns), transformations, and output checksums.
Accuracy or performance figures are not published until an evaluator has
produced a measured result file.

## Generated-parameter protocol

The cases use dimensionless simulation parameters:

- 120 observations sampled at 1 Hz.
- Baseline `10 + N(0, 1)` with a small cumulative `N(0, 0.05)` drift.
- Robust MAD z-score threshold 3.5.
- Source tag `simulation_parameter:synthetic_twin_v1`, with a null unit or
  `dimensionless_simulation_unit`.
- Seeds 42-45 for B4a-B4d and 46 for B4e.

Time indices are one-based and inclusive. B4a injects `sensor_17` at indices
50-70; B4b flatlines `thermal_sensor` at 10.0 for indices 30-120; B4c injects
one `met_cd_bias` excursion at index 120 with a robust z of 4.2 while the
upstream channels are clamped below 1.2; B4d injects `chamber_pressure` at
indices 40-60 and omits `roughing_line_pressure` entirely; B4e injects
`sensor_17` at indices 50-70 and `impedance`, `thermal`, and `pressure` at the
same indices.

These are reproducible benchmark construction parameters only, not physical
calibration.
