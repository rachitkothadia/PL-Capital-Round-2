# PL Capital — Round 2 Technical Assessment | AI Portfolio Analytics Agent

A Gemini-only terminal assessment submission with a secure SQL Query Tool, deterministic Decimal Exposure Calculator, Portfolio Agent and independent Ground Truth Evaluator. SQLite is authoritative. This is an applicant submission, not an official PL Capital product.

## Setup and launch

Install Python 3.12–3.14 and uv. Copy `.env.example` to `.env` (`cp` on macOS/Linux, `Copy-Item` in PowerShell), enter your private `GEMINI_API_KEY`, then run:

```sh
uv sync --locked
uv run pl-capital
```

Default: `gemini-3.1-flash-lite`; Pro and Flash Lite are selectable with `--model`. Environment values override `.env`. Keys and local databases/reports are ignored. No automatic provider fallback exists.

## Interface and evidence

Answers precede concise explanations and collapsed execution details. Expand actual SQL, bindings, recorded calculation inputs, dates and checks; raw diagnostics are opt-in. `/theme dark` and `/theme light` persist. Enter sends, Ctrl+J inserts a newline, Ctrl+P opens commands, Ctrl+T toggles details, F6 copies accepted SQL, F7 exports JSON, PageUp/PageDown scroll, Ctrl+Q exits. Copy feedback distinguishes native confirmation from manual fallback. Exports use exclusive generated filenames beneath the private user cache.

## Evaluation

```sh
uv run pytest -q
uv run ruff check .
uv run pl-capital eval --live --report reports/official.json
uv run pl-capital challenges --references
uv run pl-capital challenges --live --report reports/advanced.json
uv build
```

The twenty additional questions and independent references live in `tests/challenges/advanced_questions.json` and `docs/advanced-test-questions.md`. Reference validation is separate from live model accuracy. Provider failures do not count as passing answers. Original assignment material remains in `docs/assignment-original/`.

## Safety and assumptions

The model returns a strict typed Plan. All financial values come from validated read-only SQLite or deterministic local calculations. Single-statement/schema/function/binding allowlists, an authorizer and execution/output budgets guard SQL. Prices are historical 2023 snapshot values. AUM, recorded weights and quantity × price value are distinct. Stock-sector contributions exclude bonds; both whole-portfolio recorded contributions and equity-normalized percentages are labeled. Missing data is not zero.

Optional FalkorDBLite on supported macOS/Linux supplies bounded relationship context, with honest SQLite fallback; no Docker is required. Windows retains SQLite. Native clipboard support varies by platform. Sessions are bounded and in memory. The wheel bundles schema, CSVs, references and styles. No live pricing, trading or personal recommendations are provided.

See `THIRD_PARTY_NOTICES.md` for dependency attribution. Interface interaction patterns are inspired by OpenCode; no source/assets are copied.
