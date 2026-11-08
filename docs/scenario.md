# Optional hypothetical market shock analysis

This is an extra financial analytics capability alongside the assessment's four mandatory tools. The language model interprets a question and supplies typed parameters; the local calculator performs every financial calculation from SQLite. The calculator works without Gemini or any network connection. Natural-language interpretation still requires the configured Gemini service and is not claimed to be deterministic.

## Direct, repeatable API

```python
from pathlib import Path

from pl_capital.scenario import ScenarioRequest, calculate_scenario

request = ScenarioRequest(
    sector_shocks={"Technology": "-0.22", "Energy": "0.11", "Financials": "-0.07"},
    unmentioned_equity_shock="0",
    bond_shock="0",
    portfolio_filter=None,
    scenario_label="Hypothetical multi-sector market shock",
)
result = calculate_scenario(Path("/path/to/initialized/snapshot.sqlite3"), request)
```

The API accepts fractional shocks, so `-0.22` means −22%. It rejects `-22` and `"22%"`. Natural-language or command-line interfaces must convert percentage inputs exactly once before constructing the request. Decimal strings avoid introducing binary floating-point arithmetic in caller inputs. Pydantic rejects unknown request fields, expressions, nonfinite numbers, booleans, shocks below −100% or above +1000%, and shocks with more than 18 decimal places. A −100% shock is valid and gives zero post-shock value. The upper bound is a supported-input limit, not a statement that a gain is plausible.

Unmentioned equities default to unchanged; bonds default to unchanged. Either default can be specified explicitly. Each stock receives exactly one sector/default shock. Every bond receives the bond shock regardless of any recorded sector. Sector names resolve case-insensitively to the supplied sector catalog; unknown sectors and duplicate canonical sectors require correction. `portfolio_filter=None` selects all portfolios, including bond-only and empty portfolios. A nonempty list selects names or numeric IDs as strings through the established portfolio resolver; ambiguous or unknown names require clarification. Repeated selections do not duplicate portfolios.

## Source values and formulas

The source tables are `holdings`, `securities`, `sectors`, and `portfolios`. The service uses `holdings.quantity`, `securities.current_price`, the supplied `Stock`/`Bond` classification, and the supplied stock-sector mapping. It reads through the same independently read-only SQLite connection as the other financial tools. No user SQL, expressions, code execution, live prices, or model-generated financial numbers are involved.

For each holding:

```text
before = quantity × current_price
after = before × (1 + shock)
pnl = after − before
```

For each portfolio, sum all holding values, then calculate `portfolio_return_pct = 100 × portfolio_pnl / pre_portfolio_value`. For the equity-only return, sum only `Stock` holdings and divide equity P&L by pre-shock equity value. A zero denominator returns JSON `null` for display as N/A; bond-only funds therefore have no equity-only return.

For each stock sector, sum post-shock stock values and stock P&L. Equity-normalized exposure is `100 × post_sector_equity_value / post_equity_value`; whole-portfolio exposure is `100 × post_sector_equity_value / post_portfolio_value`. Each denominator is explicit. Equity-normalized sector exposures sum to 100% whenever post-shock equity value is positive. If all stock values fall to zero, those percentages are N/A. Bond losses never count as stock-sector losses. The worst sector is the sector with the most negative stock P&L; it is `null` when no sector loses money. Ties use sector name.

Reported `portfolios.total_aum`, recorded `holdings.current_weight`, and available `quantity × current_price` holdings value are different source measures. The supplied dataset does not reconcile their differences. AUM must not be substituted for the value of the holdings actually shocked; doing so would divide the calculated P&L by a different base. The calculator does not fill missing holdings or weights to force an AUM reconciliation.

Prices represent the historical supplied snapshot. `securities.current_price` has no observation-date column, so the result explicitly reports its as-of date as unknown. Supplied holding purchase dates are exposed separately and are not represented as price timestamps. Nothing updates these values to today's market.

## Precision and invalid data

Money calculations use `Decimal(str(sqlite_numeric_value))`, exact addition/multiplication, a fixed 128-significant-digit context, and an inexact-operation trap. SQLite `REAL` values have already undergone binary storage; converting their shortest round-trip representation to Decimal cannot recover precision absent from the database. Values are limited to 30 significant digits, 18 fractional decimal places, and an adjusted exponent no greater than 24, keeping supported monetary arithmetic within the exact context. Percentage ratios can repeat and use 128 significant digits with half-even rounding. Display code may round further; stored result strings preserve the calculator's precision.

Missing, negative, nonfinite, or unsupported-magnitude prices and quantities cause an explicit `DataError` for the selected analysis. Missing stock-sector mappings, unknown asset classifications, duplicate portfolio/security holdings, orphan securities, malformed currencies, and multiple selected currencies also fail explicitly. No FX rate is assumed. A syntactically valid currency is a supplied uppercase three-letter code; this format check is not an external ISO-currency lookup. Zero prices and quantities are retained and produce visible warnings instead of being silently excluded. Missing data is never replaced by zero.

## Output and verification

The JSON-safe result contains:

- `columns` and `rows`: complete summary, sorted from largest percentage loss to largest gain. Equal returns sort by portfolio name/ID; zero-value undefined returns appear last.
- `portfolios`: summary plus exact monetary values, equity metrics, sector breakdowns with both denominators, and an audit for every holding showing quantity, price, applied shock, before/after value, and P&L.
- `totals`, `currency`, `sector_shocks`, `source_tables`, `source_dates`, `formulas`, `assumptions`, and visible `warnings`.

Decimal values are strings, undefined ratios are `null`, and IDs/counts remain integers. No source database path or credentials are exported. Presentation should show “none (no sector losses)” for a null worst sector and N/A for undefined ratios, with audit details available on demand.

The independently checked Technology −22%, Energy +11%, Financials −7% example preserves all 13 supplied portfolios and 95 holdings. It produces USD 20,987,636.50 before, USD 18,927,162.27 after, and USD −2,060,474.23 P&L. A representative supplied holding is 2,500 AAPL units at 185.50: `463,750 × 0.78 = 361,725`, giving `−102,025` P&L. These are verification examples; production results are computed from the selected database, with no embedded answers.

`uv run pytest -q tests/test_scenario.py` checks actual-database results against independent Python and SQL calculations, plus reconciliation, exposure denominators, every portfolio, all-equity/mixed/bond-only/empty funds, same-sector aggregation, zero and invalid data, malformed shocks, missing entities, read-only behavior, and identity/quantity-scaling/uniform-shock properties.

Every result is a **hypothetical scenario, not a forecast or recommendation**. Fees, income, FX moves, trades, and rebalancing are not simulated.
