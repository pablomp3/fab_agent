# Reading the YAML configuration

The YAML is the tool-specific contract. It tells FabAgent which columns matter,
how to test them, and which conclusion Python is allowed to assess.

| Field | What it means |
| --- | --- |
| `signals` | The CSV columns to scan, with an optional unit and robust threshold. |
| `robust_z_threshold` | How many robust standard deviations count as an anomaly. Higher is stricter. |
| `primary_signals` | Channels that must move for the candidate to be supported. |
| `corroboration_signals` | Supporting channels. They cannot replace a missing primary channel. |
| `rules` | Python predicates and vetoes, such as a missing-evidence or contradiction check. |
| `candidate.claim` | The configured conclusion Python is allowed to test. The model does not choose it. |
| `supported_action` | The typed next action offered when the candidate is supported. |

A configured channel with no evidence forces **INSUFFICIENT**. A contradiction
rule forces **VETOED**. The model narrative is not part of either decision.
