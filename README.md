# PL Capital — Round 2 Technical Assessment

A local portfolio analytics submission with an answer-first terminal interface, auditable financial calculations and an embedded relationship graph. This is an applicant assessment submission, not an official PL Capital product.

The four mandatory components remain separate and tested:

| Component | Responsibility |
| --- | --- |
| SQL Query Tool | Validate and execute one bounded, read-only SQLite query with bound parameters. |
| Exposure Calculator | Use Decimal arithmetic for recorded stock-sector weights; distinguish whole-portfolio contribution from equity-normalized exposure. |
| Portfolio Agent | Ask Gemini for a typed plan, retrieve grounded context and dispatch to validated local tools. The model supplies no financial arithmetic. |
| Ground Truth Evaluator | Run the original ten questions through the real agent and compare against independent references. |

A fifth tool, **Scenario Analysis**, applies deterministic hypothetical stock-sector and bond price shocks. **FalkorDBLite GraphRAG** retrieves entities and schema relationships; SQLite remains the authoritative numeric source.

## Quick start

Use Python 3.12–3.14 and [uv](https://docs.astral.sh/uv/). From the checkout:

```sh
cp .env.example .env
# Edit .env locally and set GEMINI_API_KEY; never commit it.
uv sync --locked
uv run pl-capital doctor --graph
uv run pl-capital
```

In PowerShell, use `Copy-Item .env.example .env`. Environment values override `.env`. Gemini is the only model provider, following the explicit provider migration requested after the original assessment. The default is `gemini-3.1-flash-lite`; use `/model` or `--model` for a documented alternative your Google project can access. A configured key does not establish live quota or model permission. There is no automatic provider fallback.

On macOS, the embedded engine may require OpenMP:

```sh
brew install libomp
uv sync --locked
uv run pl-capital graph build --json
```

The graph dependency is installed by default on macOS/Linux. `uv sync --locked --extra graph` remains compatible. The Mac repair was verified using this project's uv Python 3.13.11, FalkorDBLite 0.11.0 and the existing libomp 22.1.8. **No Docker or hosted graph is required.** The wrapper manages a local Redis/FalkorDB subprocess and persistent cache files.

Native Windows installs omit the unsupported graph dependency; the TUI, SQLite tools and scenario calculator remain available. WSL2 can run the Linux setup. Consult [graph setup and diagnostics](docs/graph.md) for platform, native-library and licensing details; CI results and limitations are recorded in the repair report.

## Using the terminal

Answers appear before explanations. Technical evidence is collapsed until expanded. SQL answers show the actual accepted query, bindings, source tables, operations and validation. Scenario answers show shocks, formulas, representative holding arithmetic, reconciled totals and assumptions. Diagnostic JSON is opt-in.

| Action | Control |
| --- | --- |
| Send / insert newline | Enter / Ctrl+J |
| Command palette / help | Ctrl+P / `/help` |
| Expand calculation details | Ctrl+T |
| Navigate table cells | Arrow keys; focus the grid first |
| Scroll grid / jump to ends | PageUp/PageDown, Ctrl+Home/Ctrl+End |
| Open full result / selected record | **Full Table** button / Enter in grid |
| Copy accepted SQL or scenario calculation | F6 or corresponding button |
| Export all bounded results | F7 or **Export** |
| Toggle theme | `/theme dark`, `/theme light` |
| Inspect native graph | `/graph` |
| Exit | Ctrl+Q |

Tables have fixed identifier columns, nonwrapping cells, horizontal scrolling and full record views. All returned columns and bounded rows remain available; export retains original values, order and nulls. Money, NAV per unit, ratios, percentages and percentage-point differences have distinct labels. Renderer code never invents a missing SQL calculation. Themes persist in the local user configuration.

Copy SQL uses only accepted executed SQL. Python scenarios offer **Copy Calculation**, with no misleading SQL action. Native clipboard feedback is confirmed separately from unconfirmed terminal requests. Exports use exclusive generated filenames and restrictive permissions beneath the user cache; failed writes do not overwrite existing files.

## Example questions

```sh
uv run pl-capital ask "How many portfolios are there?"
uv run pl-capital ask "Show the sector exposure breakdown for Balanced Portfolio"
uv run pl-capital ask "For each portfolio with performance and risk records, show its latest common date, NAV, Sharpe ratio, beta and 95% VaR."
uv run pl-capital ask "Apply a hypothetical Technology price fall of 22%, Energy rise of 11% and Financials fall of 7% across all portfolios; other stocks and bonds are unchanged."
```

The direct scenario command works **without a model or API key**:

```sh
uv run pl-capital scenario --shock Technology=-22% --shock Energy=11% --shock Financials=-7% --json
uv run pl-capital scenario --shock Technology=-10% --portfolio "Growth Equity Fund" --trace
```

CLI shocks accept percentages or fractions: `-22%` and `-0.22` mean the same price change. The Python request accepts fractions only. Unmentioned stocks and bonds default to zero change. Use `--other-equity` and `--bonds` to change those defaults. Invalid sectors, ambiguous funds, nonfinite numbers, prices below zero after a shock, missing valuation inputs and mixed currencies produce explicit outcomes.

For the verified main scenario, the 95 supplied holdings across 13 portfolios have pre-shock market value **USD 20,987,636.50**, post-shock value **USD 18,927,162.27**, and P&L **−2,060,474.23 (−9.81756202038%)**. These values were also produced through the real agent and independently checked. They are a hypothetical revaluation of the supplied snapshot, not a forecast or recommendation.

The denominator is the available holdings' market value, `SUM(quantity × current_price)`. Reported AUM and recorded weights represent different supplied measures and do not reconcile to it. Equity returns exclude bonds; post-shock equity-sector exposures normalize stocks only. Bond-only equity returns are unavailable, not zero. A portfolio with no sector losses displays **None (no sector losses)**. No fees, trades, FX, income or rebalancing are simulated. [Scenario formulas and limits](docs/scenario.md).

## Graph health and recovery

```sh
uv run pl-capital graph status --json
uv run pl-capital graph build --json
uv run pl-capital graph rebuild --json
uv run pl-capital doctor --graph --json
```

Health proves actual Cypher retrieval, not just a successful import. The supplied graph has **238 nodes and 398 relationships**, including 13 Portfolios, 95 Holdings, 30 Securities and 10 Sectors, plus schema and snapshot nodes. Useful paths include `Portfolio → Holding → Security → Sector`. Retrieval records the Cypher, parameters, matched entities, joins, fingerprint, elapsed time and whether evidence actually reached the planner.

Build is idempotent. A versioned fingerprint includes actual SQLite rows, so in-place changes cannot silently reuse stale context. Rebuild affects the application's derived graph namespace; recovery preserves damaged files and unrelated user graph keys. SQLite and source CSVs remain intact. Graph build/rebuild return a failure exit code when native readiness cannot be established. `GRAPH_BACKEND=off` explicitly disables the graph; package, loader and query failures show an honest SQLite fallback.

## Validation

```sh
uv run pytest -q
uv run ruff check .
uv run python scripts/check_secrets.py
uv run pl-capital challenges --references --report reports/references.json
uv run pl-capital eval --live --report reports/official.json
uv run pl-capital challenges --live --report reports/advanced.json
uv build
```

Live commands send the question and bounded schema/relationship context to Google. Numeric execution and independent reference calculations stay local. Live evaluation requires the configured key and consumes the project's API allowance; transient failures and quota limits are reported separately from incorrect financial answers.

The original official evaluation was **10/10 before and 10/10 after** the initial Round 3 integration. The twenty advanced references are independently validated by SQL and Python; this reference result is separate from live agent accuracy. See the [repair release report](docs/round3-release-report.md) for final counts, fresh live results, API limitations and verified commit/push evidence. The [advanced question catalog](docs/advanced-test-questions.md) and [semantic scoring policy](docs/challenges.md) explain required fields, units and genuinely inconclusive layouts. Missing fields, wrong signs, incorrect row sets and unsupported aliases never become automatic passes.

Tests cover independent scenario oracles and edge cases, SQL safety and resource limits, historical LAG calculations, complete output projections, native graph read/write/persistence/refresh/recovery, fault injection, clipboard/export safety, themes and keyboard/mouse navigation at 80/110/160 columns. CI exercises core functionality on macOS/Linux/Windows and native graph readiness on macOS/Linux. Actual platform outcomes are reported rather than inferred from the matrix definition.

## Architecture and safeguards

`agent.py` orchestrates `gemini_client.py`, `sql_tool.py`, `exposure.py` and `scenario.py`. `verification.py` checks requested audit projections; `metric_validation.py` independently verifies recognized sector-winner and observed-decline metrics against raw SQLite records. `graph.py`/`retrieval.py` provide bounded relationship context. `presentation.py` supplies shared CLI/TUI explanations; `tui/` handles interaction; `clipboard.py`/`exporting.py` implement explicit user actions. Evaluation references are isolated from production routing and are never used to supply answers.

Canonical execution outcomes are `success`, `empty_result`, `missing_data`, `unsupported_analysis`, `needs_clarification`, `out_of_domain` and `tool_error`. Empty filter results differ from unavailable observations. Unsupported financial calculations differ from unrelated questions. If no calculation was accepted, one concise reason and next step replace the calculation heading. Personal recommendations, trading, secret/file access and policy overrides are outside scope.

SQL is treated as untrusted input: AST statement/schema/function/binding allowlists, a read-only connection, SQLite authorizer, disabled extensions, progress deadlines, row/output budgets and one bounded correction attempt protect execution. Cypher uses fixed query templates and bound values. Source loading is constrained, fingerprinted, locked and atomic. Keys, cache databases, reports and generated screenshots remain outside version control. Diagnostics and exports redact credentials and terminal control characters.

The dataset contains 13 portfolios, 30 securities, 10 sectors, 95 holdings and nine supplied tables. Performance/risk histories cover only four portfolios; the observed time series are historical. No current-price observation date is supplied. Missing observations are not filled with zero. NAV change is not automatically investment return; observed transaction cash movement is not tax-lot realized P&L. See [methodology](docs/methodology.md).

The wheel bundles schema, CSVs, reference catalogs and styles, and exposes the `pl-capital` entry point outside the checkout. Graph binaries come from the separately installed dependency; native graph support is platform-dependent. [Third-party notices](THIRD_PARTY_NOTICES.md) distinguish the BSD wrapper from the engine's SSPL license. OpenCode inspired interaction patterns; no source or assets were copied.

Final advanced verification: a complete paced Flash Lite run produced 13 passes, three failures and four unfamiliar-alias results. Independently tested semantic rescoring of those same answers gives **17/20, with three failures**. Complex sector comparisons and decline-streak SQL remain model-dependent despite strict rejection of incomplete or incorrect answers. Gemini 3 Flash Preview handled those cases, but Google enforced a verified **20 requests per day per project/model** free-tier limit during its full run. Select that model with `/model` or `--model gemini-3-flash-preview` when quota is available. No universal or 20/20 live accuracy is claimed.
