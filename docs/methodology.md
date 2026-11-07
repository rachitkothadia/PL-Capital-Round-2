# Dataset and calculation methodology

The supplied schema and all nine CSVs are preserved. A trusted initializer loads typed rows with SQLite constraints, foreign keys and integrity checks. Import is locked, fingerprinted, atomic and idempotent; a changed input requires explicit `init-db --rebuild`. A failed rebuild preserves the previous database.

Independent snapshot audit: 13 portfolios, 30 securities (25 Stock, 5 Bond), 10 sectors, 95 holdings, 24 transactions, 13 benchmarks, 330 historical prices, 44 performance and 44 risk rows. Both time-series portfolio tables cover only four portfolios. Total Stock Market Index Fund recorded weights total 0.98. The other recorded portfolio totals are 1.00. Some sectors have no securities.

`total_aum` is stored portfolio AUM; `cost_basis` is the stored holding field; current prices are historical snapshot values. Market value is `quantity * current_price`. No live quote provider is connected.

Equity exposure excludes all Bond holdings. Whole-portfolio contribution is sector SUM(stock current_weight) × 100. Equity-normalized exposure divides that sector sum by total stock weight, then multiplies by 100. The normalized view is explicitly labeled and does not fill missing portfolio weights. No-equity portfolios return a distinct informative result.

Ground truth Q7 uses market values and total holding market value, including bond values in the denominator. Q8 counts distinct stock sectors but counts all holdings in its separate holding denominator. Evaluation references are separate from production planning and calculations.
