# PHM 2018 Ion Mill representative sample slices

These small CSV slices are committed so the shape and behavior of the real PHM
2018 ion-mill data are visible without checking in the 585 MB score file. Each
file keeps only `time` and the seven configured signals.

| File | Rows | What it shows |
|---|---|---|
| `M02_DC_01_sample.csv` | 1,000 (100 normal lead-in + 900 fault-window rows) | The fault-centred benchmark slice. The v2 tool model uses the separate nominal file as its normal reference, so the fault is visible and the result agrees with the demo slice. |
| `M02_DC_01_demo_sample.csv` | 1,000 (900 nominal rows + 100 fault-window rows) | The product demo slice. It starts with the clean nominal window and ends in the same fault window. |
| `M02_DC_01_nominal_sample.csv` | 900 | The clean normal control. It is the `nominal_file` baseline for `ion_mill_phm18.yaml`; against itself every configured channel is nominal. |

All three slices come from the same run and preserve `time`. The nominal file
was selected as a 900-row window whose own robust-z maximum stays below the
3.5 alert level for every configured channel. The fault slices were selected
from the same operating point immediately after that window.

## Result

The coolant check passes on the fault slices, but large anomalies in the other
declared channels remain unexplained. Under the v2 coverage rule the product
reports **Needs Review**, not **Fault Confirmed**. That is deliberate: a
confirmation is only shown when the configured check explains the large moves.
The nominal control reports **Regular Behavior**.
