# PL Capital — Round 2 Technical Assessment | AI Portfolio Analytics Agent

This repository is my take-home assessment submission for the PL Capital AI Engineer role. It is an applicant's implementation, not an official PL Capital product.

## Assignment and implementation

The [original assignment](docs/assignment-original/README.md) asks for four components over the supplied portfolio dataset:

| Component | Implementation |
| --- | --- |
| SQL Query Tool | Groq generates SQLite SELECT queries; AST validation, bindings and a read-only connection enforce the execution boundary. |
| Exposure Calculator | Decimal arithmetic groups recorded stock weights by sector, excludes bonds, and returns whole-portfolio and equity-normalized percentages. |
| Portfolio Agent | A shared Groq-backed agent selects tools, resolves entities, handles follow-ups and records operational evidence. |
| Ground Truth Evaluator | Runs the ten supplied questions through the real agent, then checks results against independent references. |

I added a Textual terminal interface and optional local FalkorDBLite relationship context. SQLite remains the numerical source of truth. The production planner never loads evaluation answers or reference SQL.

## Quick start

Prerequisites: Git, Python 3.12–3.14, [uv](https://docs.astral.sh/uv/getting-started/installation/), access to this private repository and a Groq API key. `.python-version` selects Python 3.13; uv can provision it.

macOS / Linux:

```sh
git clone https://github.com/rachitkothadia/PL-Capital-Round-2.git
cd PL-Capital-Round-2
cp .env.example .env
chmod 600 .env
# Edit .env privately and set GROQ_API_KEY.
uv sync --locked
uv run pl-capital doctor
uv run pl-capital
```

Windows PowerShell:

```powershell
git clone https://github.com/rachitkothadia/PL-Capital-Round-2.git
Set-Location PL-Capital-Round-2
Copy-Item .env.example .env
notepad .env
uv sync --locked
uv run pl-capital doctor
uv run pl-capital
```

After setup, launch from the repository with **`uv run pl-capital`**. The first run imports the supplied schema and nine CSVs into the user cache. No Docker or hosted database is required. Set `GROQ_API_KEY` in the environment or ignored `.env`; environment values take precedence. Default model: `openai/gpt-oss-120b`, hosted by **Groq**. `openai/gpt-oss-20b` is also supported. No OpenAI API integration is used.

## Using the terminal

Try “Show sector exposures for Balanced Portfolio” or “For each portfolio, compare recorded AUM with the market value of its listed holdings.” Answers appear first, followed by a short explanation and provenance. Execution details start closed; expand them to inspect actual SQL, bindings, calculations, dates and checks. Raw diagnostics require explicit expansion or `/debug`. These are recorded evidence, not private model reasoning.

| Key / command | Action |
| --- | --- |
| Enter | Submit |
| Ctrl+J / Shift+Enter | Newline; Ctrl+J works when the terminal cannot distinguish Shift+Enter |
| Tab / Shift+Tab | Move focus |
| PageUp / PageDown | Scroll conversation |
| Ctrl+P | Command palette; Escape dismisses menus |
| `/theme`, F2 | Theme chooser; `/theme dark` and `/theme light` apply immediately |
| `/trace`, Ctrl+T | Expand/collapse execution details |
| `/copy`, F6 | Copy latest exact accepted SQL |
| `/export`, F7 | Export latest answer as JSON |
| `/help`, F1 | Help |
| `/new`, Ctrl+L; `/clear`; `/sessions` | Reset, clear or list this run's sessions |
| `/model [model ID]`; `/graph`; `/eval` | Model, graph status or live official evaluation |
| `/quit`, `:q`, Ctrl+Q | Exit |

The composer starts at three lines and grows to seven. The sidebar appears at 120 columns and the context panel at 160. Sessions remain in memory until exit. Dark/light preference persists in the user configuration directory (`PL_CAPITAL_CONFIG_DIR` can override it); corrupt preferences fall back to dark.

**Copy SQL** and **Export answer** are separate controls. Copy uses Textual plus an available native clipboard backend (`pbcopy`, PowerShell, `wl-copy` or `xclip`). Without OS confirmation it displays the SQL and offers Save SQL, rather than claiming success. Copy is disabled when no accepted SQL exists. Exports use unique filenames under the user cache's `exports/` directory, include the question/result/SQL/bindings/assumptions/dates, and redact credentials. POSIX files use owner-only modes; Windows uses the parent directory's ACL. Use a private cache directory. Display uses up to ten significant digits and eight rows; JSON preserves full returned values within execution limits.

Noninteractive examples:

```sh
uv run pl-capital ask "List active portfolios" --trace
uv run pl-capital ask "Show sector exposures for international equity" --json
uv run pl-capital doctor --json
uv run pl-capital eval --live --report reports/official.json
uv run pl-capital challenges --references
uv run pl-capital challenges --live --ids 1,5,12 --report reports/advanced.json
```

## Architecture, safety and assumptions

The TUI, CLI and evaluators call the same `PortfolioAgent`. SQLite metadata and optional graph context inform a strict typed Groq plan. SQL passes a single-statement/schema/function/binding allowlist, then executes through URI `mode=ro`, `query_only`, an authorizer, disabled extension loading where supported, and time/step/row/size bounds. One SQL correction is permitted. The exposure path uses deterministic Decimal calculations. Provider failure returns an error, never a canned answer. Only bounded question/schema/entity context goes to Groq.

This is a historical 2023 snapshot, with 13 portfolios, 30 securities, 95 holdings and incomplete risk/performance coverage. No live prices are fetched. These measures are distinct:

- `total_aum`: the portfolio's recorded AUM, not the sum of listed holdings.
- Holding market value: `quantity × current_price`.
- Whole-portfolio recorded stock-sector contribution: `SUM(sector stock current_weight) × 100`.
- Equity-normalized exposure: `SUM(sector stock current_weight) / SUM(all stock current_weight) × 100`.

Bonds are excluded from equity exposure. Missing allocations are disclosed, never invented; one fund's recorded weights sum to 0.98. Market-value percentages use the requested denominator, which can differ from recorded weights. NAV change is not automatically investment return; transaction cash movement is not verified realized P&L. Bond face values and payment schedules are absent. [Methodology](docs/methodology.md).

## Optional GraphRAG

```sh
uv run --extra graph pl-capital graph status --json
uv run --extra graph pl-capital
```

FalkorDBLite requires supported macOS/Linux; macOS also needs `libomp`. Native Windows retains SQLite. `GRAPH_BACKEND=off` disables graph use. `auto` attempts it lazily for relevant relationship questions and reports fallback on failure. Simple counts and unrelated prose skip startup. Fixed parameterized Cypher retrieves recognized entities and foreign-key joins; it never performs financial arithmetic. Graph usage is claimed only when useful evidence exists.

Actual native retrieval worked on this Mac: 13 portfolios, 30 securities, 10 sectors and 95 HOLDS edges. A local sample measured approximately 376 ms cold traversal including startup and 6 ms warm traversal. These are observations, not performance guarantees. Native query budgets and bounded context do not impose a hard deadline on process startup. [Graph details](docs/graph.md).

## Testing and evaluation

```sh
uv run pytest -q
uv run ruff check .
uv run python scripts/check_secrets.py
uv run --extra graph pytest tests/test_graph.py tests/test_graph_relevance.py -q -rs
uv build
```

The refinement baseline passed **160 offline tests** and the live official evaluator scored **10/10**. Final refinement verification: **264 offline tests passed** and the official evaluator scored **10/10 on Groq 20B**. The post-fix advanced run yielded **4 strict passes, 6 failures and 10 inconclusive cases** after saved-answer comparison fixes. A final 120B attempt was quota-limited (4/10); this is retained separately. Full model-specific evidence is in the [refinement report](docs/refinement-report.md). The [twenty challenge questions](docs/advanced-test-questions.md) retain the supplied wording. All twenty SQL references agree with independent Python calculations; that is reference validation, not AI accuracy. Strict challenge scoring distinguishes pass, fail, unsupported, inconclusive and not run. Mocked tests are explicitly offline.

Tests cover all four assignment components, malicious SQL, bad data, missing/ambiguous entities, zero denominators, provider/graph outages, independent challenge calculations, result ranking/duplicates, themes, resizing, keyboard navigation, clipboard feedback and export safety. CI runs the core on macOS/Linux/Windows and Python 3.12/3.13, plus Linux 3.14 and a native graph job.

## Trade-offs and repository layout

Groq output can vary despite temperature zero; strict advanced queries can still omit requested fields, choose incorrect ordering or require manual result review. Provider quotas affect live evaluation; incomplete runs never count as passing. Native clipboard behaviour depends on the host; Linux/Windows clipboard integration needs local smoke testing. Graph dependency/platform failures retain SQLite analytics. Session persistence, live pricing, trading and personal recommendations are outside scope.

`src/pl_capital/` contains the agent, query boundary, calculator, evaluators and TUI. `tests/` contains regressions and the challenge catalog. `data/` preserves the nine CSVs; `docs/assignment-original/` preserves the assignment. The wheel includes data, schema, official references, the advanced catalog and styles, and runs outside the checkout. Build artifacts are local; nothing is published to a package registry.

The interface is independently implemented, with OpenCode interaction patterns as inspiration; no source, assets or affiliation are claimed. [Third-party notices](THIRD_PARTY_NOTICES.md), [capability audit](docs/capability-audit.md), [architecture](docs/architecture.md).
