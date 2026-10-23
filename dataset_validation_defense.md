# FabAgent: Dataset Validity & Architecture Defense

## Overview
FabAgent is a low-integration troubleshooting copilot that performs deterministic, traceable Root Cause Analysis (RCA) without hallucinating physical meanings. It enforces a strict boundary between what is statistically true (analyzed via Python/DuckDB) and what an LLM *thinks* is true, guaranteeing safety when operational interventions are proposed.

---

## 1. Justifying the Validity of the Tests (The "Dataset Mismatch" Problem)

### The Challenge
If a hackathon judge or domain expert asks:
> *"TEP is a chemical plant simulation from 1993, and PHM 2018 is an ion mill. Modern semiconductor fabs use Lam Research etchers and ASML lithography tools. How does performance on these open datasets prove that FabAgent works for modern wafer fabrication?"*

### The Defense
The defense rests entirely on the **Separation of the Engine from the Configuration**.

* **We Are Testing Reasoning Capabilities, Not Specific Tool Physics:**
  We are not claiming that FabAgent possesses pre-trained knowledge of proprietary plasma physics or 2026 lithography chamber geometries out-of-the-box. We are proving that the agent possesses rigorous industrial reasoning capabilities:
  1. The ability to distinguish a root cause from a downstream symptom (demonstrated via the Tennessee Eastman Process / TEP).
  2. The ability to attribute a fault to the correct subsystem rather than mistaking correlated symptoms for the primary failure (demonstrated via PHM 2018 Ion Mill).
  3. The discipline to reject false correlations and abstain when telemetry is insufficient.

* **The "Bring-Your-Own-Export" YAML Architecture:**
  The core intelligence of FabAgent is completely blind to specific datasets, machine brands, or proprietary formats. Benchmark IDs (e.g., `TEP`, `PHM18`, `B1`, `IDV`) are strictly banned from the Python core engine (`src/core/`). 
  
  The engine operates purely on a generic evidence schema:
  - `sensor_name`
  - Robust non-parametric statistics (Median Absolute Deviation / MAD $z$-scores)
  - Time windows and baseline comparisons
  - Boolean constraint predicates (`require_all`, `forbid_any`, `veto_if_any`)
  
  To adapt FabAgent to a modern fab tool (whether an ASML extreme ultraviolet scanner, an Applied Materials CMP tool, or a Lam Research plasma etcher), a process engineer simply writes a declarative configuration file (`config/sensor_relations/*.yaml`). The core algorithms remain completely untouched.

* **The Justification Statement:**
  The open datasets simply instantiate these generic engineering constraints. We justify test validity with this formal guarantee:
  > *"If a process engineer provides the YAML relationship definitions and sensor mappings for their specific modern chamber, FabAgent will execute the exact same mathematically guaranteed safety constraints, hard vetoes, and reasoning paths that are proven on TEP and PHM 2018."*
