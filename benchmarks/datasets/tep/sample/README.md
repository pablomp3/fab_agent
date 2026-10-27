# TEP representative sample slices

These small CSV slices are committed so the shape and behavior of the real
Tennessee Eastman Process data are visible without checking in the full raw
archives.

| File | Rows | What it shows |
|---|---|---|
| `IDV6_sample.csv` | 31 (header + 30) | Sudden loss of A feed (stream 1). The product v2 check uses `XMEAS(1)` and `XMEAS(7)` as a feed-flow / pressure pattern and reports **Fault Confirmed**. The published W5 comparison uses `XMEAS(1)` and `XMV(3)` as the cause, with `XMEAS(7)` as the symptom. |
| `IDV3_sample.csv` | 31 (header + 30) | Step in D feed temperature. This disturbance is **not** modeled by the feed-system relationship, so the configured check cannot confirm it. The correct result is **Needs Review** (“ask an engineer”), not **Regular Behavior** / “Normal Run”. |

Columns are the three monitored variables used by the W5 evaluation:
`XMEAS(1)` A feed flow, `XMV(3)` A feed valve, and `XMEAS(7)` Reactor Pressure.

The full IDV archives (`idv1.zip`–`idv15.zip`) and the converted processed CSVs
live in `benchmarks/datasets/tep/raw/` and `benchmarks/datasets/tep/processed/`
and are excluded from Git via `.gitignore`.

## Ground-truth note

- IDV 6: in the published W5 model the cause is the A feed / A feed valve;
  reactor pressure is a symptom. A model that names `XMEAS(7)` as the physical
  cause is wrong. The product v2 check uses a conservative pattern and does not
  claim which channel is the physical cause.
- IDV 3: an unmodeled disturbance. It is an **abstention** case, not a normal
  reactor. Do not put “Regular Behavior” on it.
- Do not use IDV 13 or 16–20 for attribution: no ground truth.
