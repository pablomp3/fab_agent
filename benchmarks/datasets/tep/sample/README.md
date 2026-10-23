# TEP representative sample slices

These small CSV slices are committed to the repository so the shape and
behavior of the real Tennessee Eastman Process data are visible without
checking in the full raw archives.

| File | Rows | What it shows |
|---|---|---|
| `IDV6_sample.csv` | 31 (header + 30) | Sudden loss of A feed (stream 1). The configured feed-system candidate (`XMEAS(1)`, `XMV(3)`) is **SUPPORTED**; `XMEAS(7)` Reactor Pressure is the downstream symptom. |
| `IDV3_sample.csv` | 31 (header + 30) | Step in D feed temperature. This disturbance is **not** modeled by the feed-system relationship in `config/sensor_relations/tep_reactor.yaml`, so the configured candidate correctly abstains. |

Columns are the three monitored variables used by the W5 evaluation:
`XMEAS(1)` A feed flow, `XMV(3)` A feed valve, and `XMEAS(7)` Reactor Pressure.

The full IDV archives (`idv1.zip`–`idv15.zip`) and the converted processed CSVs
live in `benchmarks/datasets/tep/raw/` and `benchmarks/datasets/tep/processed/`
and are excluded from Git via `.gitignore`.
