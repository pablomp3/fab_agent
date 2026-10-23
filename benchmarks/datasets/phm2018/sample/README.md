# PHM 2018 Ion Mill representative sample slice

This small CSV slice is committed to the repository so the shape of the real
PHM 2018 ion-mill data is visible without checking in the 585 MB score file.

| File | Rows | What it shows |
|---|---|---|
| `M02_DC_01_sample.csv` | 1,001 (header + 1,000) | A 1,000-row window centered on the first zero-TTF fault event in run `01_M02_DC_01` (`Flowcool leak`, time = 56612312). The flowcool signals are visibly deviated from nominal. |

The dataset documentation states that sensor values are Z-normalized and that
units are withheld, so all units remain `None` in the configuration.

The full score file (`01_M02_DC_score.csv`) and the converted processed files
live in `benchmarks/datasets/phm2018/raw/` and
`benchmarks/datasets/phm2018/processed/` and are excluded from Git via
`.gitignore`.
