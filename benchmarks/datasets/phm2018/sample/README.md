# PHM 2018 Ion Mill representative sample slices

These small CSV slices are committed to the repository so the shape and
behavior of the real PHM 2018 ion-mill data are visible without checking in the
585 MB score file.

| File | Rows | What it shows |
|---|---|---|
| `M02_DC_01_sample.csv` | 1,000 (header + 1,000) | A window centered on the first zero-TTF fault event in run `01_M02_DC_01` (`Flowcool leak`, time = 56612312). The in-file robust baseline absorbs the excursion, so this fault-centered slice is **inconclusive**; it remains the benchmark window used by the E2E suite. |
| `M02_DC_01_demo_sample.csv` | 970 (header + 970) | A prepared demo slice with a stable lead-in followed by the same documented fault window. The flowcool channels are visibly deviated from the lead-in, so the product scenario reports `SUPPORTED`. |
| `M02_DC_01_nominal_sample.csv` | 1,000 (header + 1,000) | A nominal window from the same public score file. The configured flowcool channels are present and below the 3.5 robust-z threshold, so the safe path abstains. |

The demo slice is deliberately prepared with a nominal lead-in. A window
centered only on the fault can make the in-file robust baseline absorb the
excursion. The committed slices are demonstration inputs, not new benchmark
truth.

The dataset documentation states that sensor values are Z-normalized and that
units are withheld, so all units remain `None` in the configuration.

The full score file (`01_M02_DC_score.csv`) and the converted processed files
live in `benchmarks/datasets/phm2018/raw/` and
`benchmarks/datasets/phm2018/processed/` and are excluded from Git via
`.gitignore`.
