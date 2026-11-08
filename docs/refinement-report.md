# Round 2 refinement verification

This is the second development pass on the existing assessment submission. Published history and the four original components are preserved. Verification date: 8 November 2026, macOS Apple silicon, Python 3.13.11. Machine-readable reports remain local under ignored `reports/refinement/`.

Final local verification: **264 tests passed**, **10/10 official questions on Groq 20B**, and **4/20 strict advanced passes** with failures/inconclusive cases disclosed below.

## Before and after

- Baseline: 160 offline tests and 10/10 live official questions on Groq `openai/gpt-oss-120b` (`official-before.json`).
- Reproduction at 80×24, 120×35 and 160×45 found the answer headline above the visible viewport, raw JSON dominating expanded traces, fixed composer height and hardcoded backgrounds preventing visible theme changes.
- Graph profiling found a simple misspelled count unnecessarily started the native server and claimed graph use despite no matching entities. Unrelated prose could also be labeled as useful retrieval.
- The revised TUI anchors each new answer at its top. Tables/headlines precede explanations, provenance and collapsed execution details. Raw diagnostics are separately closed and opt-in. Error and empty results remain explicit.
- The shared presentation layer explains real SELECT expressions, joins, filters with bound values, grouping, order, windows and limits. Calculator details show actual recorded stock/bond sums and sector arithmetic. It does not present private model reasoning.

## Implemented refinements

Both SQL and calculator answers carry their question, accepted executed SQL/bindings, dates, currency and assumptions. A proposed or rejected statement never becomes copyable SQL. Scalar counts display a direct answer such as `13 portfolios`; small numeric differences remain visible. Tables show up to eight rows and ten significant digits; exports retain returned values. Ratios/fractions remain unitless, percentage-point gaps use pp, and monetary fields alone receive a currency prefix.

Registered dark/light themes use Textual variables throughout widgets and Rich code blocks. `/theme`, the F2 chooser and palette actions apply immediately, and an atomic user preference file survives restart. The composer grows from three to seven lines. Conversation scrolling and keyboard controls work at all requested widths; sidebars appear only at 120/160 columns.

Separate Copy SQL and Export answer actions share tested mouse/keyboard handlers. Native clipboard backends accept SQL only through stdin and fixed argument arrays. Terminal-only requests are explicitly unconfirmed. Failure reveals manual SQL and Save SQL. JSON/SQL exports use generated exclusive filenames under the cache, redact secrets, reject symlink export directories and preserve existing files on collision. Windows permissions inherit the parent ACL; POSIX mode assertions are conditional.

Graph retrieval starts lazily, skips simple counts/unrelated prose, filters stopwords, bounds unambiguous typo repairs and returned context, and claims usage only for useful entity/join evidence. SQLite fallback records its reason. Actual native graph operation was verified: 13 portfolios, 30 securities, 10 sectors, 95 HOLDS relationships. Sample cold traversal was 376 ms including startup; warm corrected-sector lookup was 6 ms. Query budgets are separate from startup; no hard total startup deadline is claimed.

SQL changes permit the structural boolean operators AND/OR/EXISTS while preserving nested unsafe-function checks and the SQLite authorizer. Narrow named-sector metric verification no longer imposes that metric's four-column/two-decimal policy on unrelated advanced analytics. Multi-fund SQL context labels no longer require a single portfolio match. Planner guidance covers windows, actual observation boundaries, synchronized dates, stock-only denominators, negative VaR and transaction cash movement. No production code imports challenge references or official answer numbers.

The README now presents the work as an applicant's technical assessment, explains all four components first, and documents setup on macOS/Linux/Windows, real controls, financial assumptions, packaging and limitations. The supplied twenty question bodies are retained exactly and pinned by a content hash; local prompt files are not needed by CI or the wheel.

## Local and UI verification

- Final full offline suite: **264 passed** in 83.23 seconds; no live calls occur in these tests.
- UI-focused suite: **28 passed**, covering actual dark/light computed styles and code backgrounds, contrast checks, focus, switching with answers/details displayed, restart, corrupt preferences, resize, responsive panels, composer/newline, mouse/keyboard actions, export and failure feedback.
- Requested dimensions: **80×24, 100×30, 120×35, 160×45**, both themes. Saved live-answer replays produced eight visual previews; these replays made no provider calls. Dark and light 80-column previews were visually inspected.
- Additional real Groq UI run, **20B model**, through Textual Pilot at 80×24: count returned **13 portfolios**, Balanced Portfolio exposure returned **4 stock holdings**, details started closed, JSON exports matched actual results, both themes changed computed backgrounds, and light persisted on a 100×30 restart (`live-ui-after.json`). This run is separate from replay tests.
- Actual macOS clipboard smoke: **pbcopy succeeded**, content was read back and matched exact SQL, then the previous clipboard was restored (`clipboard-smoke.json`). Mocked Linux/Windows backend and failure-path tests do not prove those OS clipboards work on physical hosts.
- Native FalkorDBLite suites: **24 passed** with the optional extra. Fallback and graph-irrelevance cases also pass without that dependency.
- Ruff and tracked-source credential scanning passed. Wheel/sdist build succeeded. A fresh wheel environment outside the checkout independently verified **20/20 challenge references**, demonstrating bundled schema/data/catalog availability.
- Interactive CLI/TUI launch and clean keyboard exit were exercised in a PTY. Desktop Terminal automation was unavailable; no GUI-launch success is claimed. Colour output requires a colour-capable terminal and respects `NO_COLOR`.

## Official evaluation

The official ten-question fixture is unchanged. Each evaluation resets context and uses the real shared agent, then independently checks SQL/calculator results, complete rows, duplicates, requested order and precision.

The first post-refinement 120B run completed at **4/10**. All six failures were typed **Groq rate-limit errors**, not scored numerical answers (`official-after.json`). Safe provider diagnostics identified the 120B daily token allowance: 200,000 limit, 196,696 used, a 3,377-token request temporarily exceeding remaining allowance. Tokens refill gradually; a small diagnostic request succeeding did not prove a full planning request would fit. An attempted paced 120B rerun was stopped after the daily-limit diagnosis and is not represented as a completed evaluation.

The first separately labeled, paced **20B** official run scored **9/10**. Its sole failure rounded sector-average prices to cents despite no requested rounding (`official-after-20b-before-precision-fix.json`). A failing regression reproduced that loss, and the agent now rejects rounded AVG expressions for unrounded-average requests before execution, using its existing one-correction path. Explicit rounding requests remain supported. The default planner guidance now also asks for full AVG precision. The complete post-fix **20B** run scored **10/10 (100%)**, including unrounded sector-average prices and both independent exposure-denominator checks (`official-after-20b.json`). Questions were paced 40 seconds apart to respect the model token window; scheduling changed neither the agent implementation nor the reference/comparison logic. Model switching is a supported configuration choice, not an automatic substitution inside production error handling. The original 120B result is retained.

## Advanced challenges

All **20 SQL references agree with independent Python calculations**. Reference checks include changed datasets: tied sector ranks, reduced stock universes, missing calendar dates, tied decline runs, nonmatching latest risk/performance dates and zero stock-value denominators. References are isolated from production planning.

A full initial live 120B run and a full post-fix live 120B run each called the ordinary agent for all twenty questions. The final comparator accepts documented aliases, reordered columns, equivalent portfolio IDs/names and unordered equal-score overlap ties; complete rows, duplicate counts, requested ranking and strict numerical checks remain required. Tests prove wrong values remain failures. The initial report's original scorer recorded 0 pass/5 fail/15 inconclusive; rescoring those same saved answers with the final comparator yielded **3 pass/5 fail/12 inconclusive**, without new model calls.

The post-fix run originally scored **2 pass/4 fail/14 inconclusive**. Rescoring its saved answers with the final comparator yielded **4 pass / 6 fail / 0 unsupported / 10 inconclusive / 0 not run** (`challenges-after-rescored.json`). This is a **20% strict verified pass rate over all twenty**, not a claim that every inconclusive result is wrong. Three inconclusive cases were quota failures; others need clarification or manual review of unfamiliar result shapes. No tolerance was widened to inflate the score.

| Questions | Final status | Evidence |
| --- | --- | --- |
| 10, 13, 16, 17 | pass | Unused sectors, intraday range, signed/magnitude VaR changes and cash movement matched independent references. |
| 4 | fail | Recorded-weight discrepancy sign differed from the declared signed reference convention. |
| 6 | fail | Missing normalization percentages/denominators and absolute discrepancy. |
| 7 | fail | Portfolio IDs accepted; strict numerical precision still differed. |
| 12 | fail | Decline-run values/boundaries differed from observation-based reference. |
| 14 | fail | Selected common date missing from output. |
| 15 | fail | First/last NAV audit inputs missing from the required challenge shape. |
| 1, 2 | inconclusive | Agent requested clarification rather than returning the compound result. |
| 3, 5, 20 | inconclusive | Groq quota failure; no result scored. |
| 8, 9, 11, 18, 19 | inconclusive | Result shape/extra or ambiguous semantic fields require manual review; no automatic pass claimed. |

Investigation of the initial run produced the boolean-validator fix, narrower metric checks, multi-portfolio context fix and general prompt improvements before the second full live run. Remaining advanced failures are disclosed rather than hidden by fixtures, answer routing, relaxed checks or repeated attempts until a pass.

## Git, CI and capabilities

All pushes use the confirmed private repository's default `main`, with no force-push, rebase or published-history editing. Each implementation milestone received focused tests and a staged-source secret scan, then remote SHA verification. Full source and build archives were also inspected for accidental credentials.

| Commit | Verified milestone |
| --- | --- |
| `92305c2` | Safe boolean conditions in analytical SQL; 13 new SQL regressions. |
| `f49515f` | Relevant, bounded lazy graph retrieval. |
| `4659a48` | Recorded evidence presentation, accepted-SQL contract, safe clipboard/export services. |
| `affda16` | Answer-first TUI, actual themes, composer and functional actions. |
| `b3f4c1e` | Twenty independent challenges, CLI/reference mode and bundled catalog. |
| `d6d4ad3` | Cross-platform graph fallback provenance check. |
| `1912ffa` | Equivalent pair identity and conservative semantic aliases in challenge comparison. |
| `cac2377` | Unrequested average-rounding check, its regressions and UI action geometry wait. |
| `49ffca7` | Correct currency, ratio and percentage-point display units. |
| `a23b6a8` | Bounded wait for the actual settled composer height on slow UI runners. |

CI exposed two Windows-only test assumptions about attempting a native backend that Windows intentionally skips. Both assertions were corrected to test actual fallback/provenance; quantitative behavior was unchanged. A later Windows UI test exposed deferred layout geometry after details expansion; the test now waits for that layout before locating/clicking the real Save SQL button. Two checkpoint processes overlapped and combined this test change with the precision change in `cac2377`; that published commit is preserved, and subsequent checkpoints are serialized. Separate setup-uv HTTP 504 failures were infrastructure errors, not hidden test failures. The composer test also needed a bounded condition wait for its 3→5→7→3 layout sequence on a slower Windows runner; the assertions remain unchanged. The focused UI suites passed **19 checks** after that test adjustment. The [workflow run history](https://github.com/rachitkothadia/PL-Capital-Round-2/actions/workflows/ci.yml) retains each failure and retry; final head/run status accompanies the delivery rather than replacing those records.

Tools genuinely used include local Git/authenticated GitHub CLI, Python/uv, pytest/Textual Pilot, Ruff, package builds and fresh environment installs, native pbcopy/pbpaste, Graphify navigation/AST refresh, Tokenade, official documentation and scoped UI/graph/evaluator subagents. Relevant installed testing, debugging and verification guidance informed the workflow. Context7 was unavailable to the root; reviewed official docs were the fallback, with child-agent access used where available. No unrelated connectors received repository data; no unreviewed external installer/scanner bundle was executed. See the [capability audit](capability-audit.md).

## Remaining limits

Advanced compound analytics remain materially less reliable than the official set. Strict scoring can mark plausible answers inconclusive; human review is needed before using them. 120B daily quota exhaustion blocked a clean final default-model rerun. Native graph support and clipboard transports vary by platform; only macOS clipboard and macOS/Linux native graph operation have direct smoke evidence. GUI Terminal launching could not be verified. Sessions are in memory, and all prices/data remain historical.
