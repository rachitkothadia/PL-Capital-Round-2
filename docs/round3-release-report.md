# Round 3 repair release report

Verified locally on macOS Apple silicon; report date: 9 November 2026 (Asia/Kolkata).

## Delivered changes

- Replaced wrapping SQL grids with Textual DataTables: frozen identifiers, horizontal navigation, Full Table and full record views, all bounded rows/columns and exact exports. NAV per unit and risk ratios are not labeled as dollars. No absent calculation is invented by the renderer.
- Added typed deterministic Decimal scenario analysis, natural-language Gemini routing, direct no-key CLI, portfolio ranking, stock-only returns, sector exposures, negative sector contributions, holding-level audit, Copy Calculation and complete JSON exports.
- Added seven canonical execution statuses, actionable next steps, one refusal explanation, real data-coverage checks and honest failure views. Strengthened output contracts for sector counts, selected common dates, transaction IDs, NAV observations and compound denominators.
- Added independent raw-SQLite runtime checks for sector winners, consecutive observed declines, AUM comparisons and holding-share discrepancies. Incorrect or incomplete model results trigger bounded correction and are rejected if still wrong; reference answers never supply production results.
- Improved advanced scoring with documented semantic aliases, explicit fraction conversions, independently verified optional descriptions and lossless High/Low tall-layout comparison. Required fields, full populations, duplicates, signs, ordering and tolerances remain enforced.
- Updated README, scenario/graph/scoring documentation and native-platform CI. Gemini remains the sole provider, honoring the later provider-migration instruction over the repair document's older provider references.

## Actual verification

- Full local suite: **480**. Commands: `uv run pytest -q`; final metric/output checks and comparator mutation tests were additionally run after the last narrow changes. Full logs remain in ignored `reports/round3/`.
- Ruff, tracked credential scan and whitespace checks passed. Original CSVs, schema, official ground-truth dataset and advanced question catalog are unchanged relative to baseline `15850ce`.
- Official real-agent evaluation: **10/10 before repairs**, **10/10 after integration**, and **10/10 with Gemini 3 Flash Preview** (59.07 seconds). Reports: `official-before.json`, `official-after.json`, `official-strong.json`.
- All twenty advanced SQL/Python references independently validate. Scenario calculator: 39 dedicated tests; scenario/exposure/data/financial subset: 51 passes. Native graph suite: 33 passes, no native skips on this Mac. UI suite: 40 passes, plus subsequent focused checks.
- Historical LAG case independently verified: Conservative Income Fund, 2023-09-27, NAV 108.45→108.62, Sharpe 1.58→1.56, beta 0.36→0.37, with NAV percentage change based on prior NAV.
- Captured 54 SVGs across 80/110/160 columns, both themes, actual 13-row scenario and 40-row/15-column historical results. Representative PNGs were visually inspected. Keyboard, mouse, resizing, full tables/records, scenario sectors, F6/F7, persisted themes and error views are tested. Disposable real TUI startup and Ctrl+Q exit both succeeded; the user's previously open session was preserved.
- Native macOS clipboard: Copy SQL and Copy Calculation both confirmed through `pbcopy` plus exact `pbpaste` read-back. Original clipboard text restored. Exports preserve complete values, nulls, order and provenance with private generated filenames.
- Wheel and sdist built; 146 archive entries scanned for credential/path leaks. The wheel executed the full 13-portfolio main scenario outside the checkout without a key. Native Windows graph support is explicitly unavailable; Windows SQLite/TUI support is covered by CI.

## Main scenario: actual live and independent results

Technology −22%, Energy +11%, Financials −7%; all other stocks and bonds unchanged. The real agent selected `scenario_analysis`, with the exact stated fractional shocks. Independently checked all 13 portfolios and 95 holding records, stock denominators, rank order and normalized exposures.

| Measure | USD / percent |
| --- | ---: |
| Pre-shock available holdings | 20,987,636.50 |
| Post-shock available holdings | 18,927,162.27 |
| P&L | −2,060,474.23 |
| Portfolio return | −9.81756202038% |

Tech Innovation Fund loses 22%; Growth Equity Fund loses approximately 18.62636%. Bond-only equity returns are null. No sector losses is explicitly labeled. AUM is never the return denominator. This revalues historical supplied prices; it does not model trades, FX, fees, income or rebalancing, and is not a forecast.

## Native FalkorDBLite repair

The reproduced failure was `ModuleNotFoundError: No module named 'redislite'`: ordinary uv synchronization omitted the former optional graph dependency. FalkorDBLite 0.11.0 is now a platform-marked default dependency in the same uv environment. Python 3.13.11 and the already installed libomp 22.1.8 work on this Mac; no Docker or new Homebrew installation was required.

Actual health: **backend=falkordblite, native_ready=true, graph_used=true; 238 nodes, 398 relationships**. Counts include 13 Portfolio, 95 Holding, 30 Security, 10 Sector, 9 Table and 80 Column nodes plus the snapshot marker. Actual Cypher retrieved Growth Equity Fund→Holding→AAPL/MSFT/NVDA→Technology. Native writes/reads, reopen persistence, idempotence, source-row refresh, namespace rebuild, incomplete/corrupt cache recovery and preservation of unrelated graph keys are tested. Useful evidence reaches the real planner context; SQLite supplies financial values.

Fingerprint: `8415e61292b30e923d8ad2946b4d0fb378bebe51ba8ca9129107af0a14c4eb75`.

`graph status`, `graph build`, `graph rebuild`, `doctor --graph` and `/graph` expose real health. Missing package, loader and query failures retain explicit SQLite fallback. Build/rebuild fail their command exit status if native readiness fails. Windows avoids unsupported native startup. CI explicitly proves native readiness on Linux and macOS.

## Advanced live results and precise remaining limits

The final complete paced Flash Lite run attempted all twenty questions: **13 pass, 3 fail, 4 inconclusive**. Documented, mutation-tested aliases rescore those exact saved answers to **17 pass, 3 fail, 0 inconclusive**; this is an offline semantic rescore, not another model run. Files: `advanced-paced.json`, `advanced-paced-rescored.json`.

Remaining Flash Lite failures:

1. Sector winner comparison omitted portfolio identity. The runtime rejected the answer; the output guard now explicitly requests that identity before execution.
2. Mixed recorded-weight/equity allocation omitted the requested auditable sector-weight intermediate despite correction.
3. Consecutive-decline SQL referenced an unknown/ambiguous column after bounded correction. No incorrect result was presented as success.

The stronger model successfully returned these individual analyses. Its complete advanced batch recorded **7 pass, 0 fail, 13 inconclusive**: eleven HTTP 429 blocks, one incomplete model plan and one unrecognized alias. These distinct causes are preserved; they are not thirteen proven wrong answers or thirteen pure quota failures.

A minimal provider diagnostic confirmed `RESOURCE_EXHAUSTED`, quota `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, value **20**, for Gemini 3 Flash. Google reported a retry delay of approximately 61,807 seconds at that observation. Flash Lite's diagnostic returned HTTP 200. The key is valid; rotating keys within the same project does not remove a project/model daily quota. Provider exceptions now distinguish HTTP 429 from service failures and include safe retry timing.

A fully passing new strong-model twenty-question batch is therefore **blocked by that external daily quota**. Default Flash Lite remains available, but its three advanced planning failures mean this release does **not** claim universal correctness or 20/20 fresh live accuracy. API limits, model access and generative SQL variability remain real limitations.

## Tools and workflow actually used

Local uv/Python, pytest, Ruff, Textual Pilot/screenshots, native clipboard tools, Git/GitHub CLI and Actions; Graphify code navigation and Tokenade compact inspection; scoped scenario, graph and UI subagents; installed debugging, test-first and verification workflows. Official Google, Textual and FalkorDB documentation informed changes. Context7 documentation tools were unavailable in this session. No unreviewed installer scripts or blanket plugin bundles were executed. No hosted graph or unrelated external service received repository contents.

Graphify AST navigation was refreshed. Its optional documentation-semantic refresh was interrupted by a host-agent usage limit; that development index is separate from the operational FalkorDB relationship graph verified above.

## Git and release evidence

Baseline default branch: `main`; private repository and target remote verified. Each milestone used an ordinary commit and push followed by local/remote SHA comparison. No force-push, history rewriting or credential publication.

Implementation commits before this report:

```text
aa6d8e3 Add deterministic portfolio shock analysis
ee0c427 Fix native graph installation and snapshot synchronization
4ff3b5e Route scenarios and enforce auditable financial outputs
1afba2a Make terminal result tables scroll and expand
cf191a9 Validate advanced financial metrics and semantic results
dae9957 Verify native graph readiness across supported platforms
66f351e Distinguish Gemini rate limits from service failures
fef07d5 Independently verify AUM and holding-share comparisons
3f7f942 Validate alternate risk layouts without weakening scoring
```

The final report/documentation commit and its remote SHA are verified separately in the completion reply, avoiding a circular self-referencing commit hash. The final CI outcome is also checked there. Generated local reports, screenshots, cache databases and credentials remain ignored. A Graphify-generated untracked `.gitattributes` is preserved rather than silently discarded.
