# Verified release report

All four required components are implemented locally: Groq-generated read-only SQL, Decimal stock-sector exposure, shared typed PortfolioAgent, and independent live evaluator. The Textual workspace includes responsive panes, a multiline composer, real model switching, bounded sessions, command palette, expandable operational traces, SQL copy/export, exposure cards and background live evaluation.

## Actual verification

- `uv run pytest -q`: 160 passed on macOS arm64 with optional native graph installed; no skips.
- `uv run ruff check .`: passed.
- `uv run --extra graph pl-capital eval --live ...`: 10/10, actual model `openai/gpt-oss-120b`. Eight SQL questions and two exposure questions were executed through the real agent. The timestamp is `2026-11-07T17:39:31.391377+00:00`. This release run followed the dependency and SQLite portability fixes.
- Native graph suite: 8 passed on this Mac; Linux native graph CI also passed. Traversal/entity counts, idempotence, injection resistance, outage fallback and closed-client fallback were verified.
- Real headless TUI acceptance: two actual Groq calls with graph explicitly off. A paraphrased count returned 13; Balanced Portfolio exposure returned 0.36 stock weight, 0.64 bond weight and four bond exclusions. Enter submission and rendered answer cards completed successfully.
- Dependency advisory audit: 42 public locked packages, zero known vulnerabilities, zero skips. Initial 13 filelock advisories were preserved and remediated with filelock 4.2.9; raw application source was not uploaded.
- Wheel/source archive audit: required nine CSVs/schema/reference/styles present and byte-verified; no .env, local master, reports or private working files; actual key and token-pattern matches zero. An isolated wheel installation outside the checkout returned 13 portfolios/95 holdings and graceful missing-key errors.
- Tracked-source scanner passed; a separate Git-history audit scanned 92 blob versions with zero credential matches. Subsequent commits contain tests/documentation only and are scanned before staging.

## Evaluation results

| Question | Route | Result |
|---|---|---|
| Q1 | sql_query | PASS |
| Q2 | sql_query | PASS |
| Q3 | sql_query | PASS |
| Q4 | sql_query | PASS |
| Q5 | sql_query | PASS |
| Q6 | sql_query | PASS |
| Q7 | sql_query | PASS |
| Q8 | sql_query | PASS |
| Q9 | exposure_calculator | PASS |
| Q10 | exposure_calculator | PASS |

Q1 returned 13; Q2 returned 10 active names; Q3 returned eight Technology securities; Q4 returned stored high-risk AUM 85,000,000. Q5/Q6 matched full ordered references. Q7 matched eight portfolios with sector value, all-holding denominator and two-decimal percentage. Q8 matched Total Stock Market Index Fund (six stock sectors, 12 total holdings, ratio 0.5). Q9 Technology was 100%; Q10 was Automotive 15%, Consumer Staples 11%, Energy 38%, Technology 36%.

## Failures investigated and corrected

The first live run scored 9/10: Q7 omitted its denominator/output column and requested ordering. A later single-question run exposed fraction units and zero-filled absent-sector portfolios. General audit projection checks and an independent runtime market-value verifier now reject inconsistent generated plans and permit one bounded Groq correction. The verifier supports arbitrary named sectors and contains no fixture IDs, answer lookup or replacement answers. Review then narrowed its scope to avoid overriding named-fund filters and equivalent SQL. The unchanged evaluator retained strict shape/order checks throughout.

Independent security review reproduced and fixed unclosed SQLite handles before Windows atomic rename, malformed metadata manifests, excessive result materialization and Decimal overflow. Real CI found macOS SQLite builds without enable_load_extension; feature detection now preserves the authorizer on those builds. Windows test assumptions about POSIX permission bits and unsupported native graph installation were corrected. The compact-window SQL-copy regression was reproduced locally, fixed with explicit target visibility and actual click assertions, and verified in wide/compact terminal tests. All eight CI jobs then passed.

## Graph operation and limits

FalkorDBLite 0.11.0 was actually installed and queried without Docker on macOS arm64. The graph contains 13 Portfolio, 30 Security, 10 Sector and 95 HOLDS relationships, plus real schema/foreign-key metadata. Read-only relationship queries feed bounded planning context; SQLite owns all financial numbers. Native Windows uses SQLite. Optional graph failure is visible and preserves quantitative tools. This is relationship retrieval, not vector search.

Historical price rows span 2023-09-25 through 2023-10-09. Security current_price values are supplied snapshot fields, not live quotes. Weight coverage and risk/performance gaps are disclosed. LLM interpretation remains variable. Clipboard support depends on the terminal; local export remains available. POSIX private file modes do not constitute Windows ACL enforcement; Windows inherits parent-directory permissions. Sessions are bounded/in-memory.

## Capabilities used

Native Git/gh, private GitHub integration discovery, web/official documentation, Context7 in child agents, Graphify, Tokenade, uv, Python/SQLite, pytest, Ruff, Textual Pilot, native SVG rendering and reviewed PyPA pip-audit were used. Three specialized subagents covered research/graph, UI/CLI and independent evaluator/security review. Superpowers workflows and Sentry review/secret-serialization guidance were used; no blanket skill/plugin bundle or unreviewed external installer was executed. Full evidence and primary links are in capability-audit.md and THIRD_PARTY_NOTICES.md.

## Git evidence

Confirmed default branch: `main`; repository private. Every implementation checkpoint below was committed under the configured author, pushed normally, and verified against remote HEAD. No force-push, empty commit, history rewrite or fabricated author/date was used. Evaluator was checkpointed before CLI integration to keep commands usable; CLI and its core TUI were one cohesive checkpoint, followed by trace enhancements. All 16 planned areas are covered, with additional substantive security/CI fixes.

```text
1e81f89 chore: set up reproducible Python project and Git hygiene
891313d feat(data): import supplied SQLite schema and CSV data
7ff055e test(data): validate database integrity and fixture assumptions
02a14db feat(sql): enforce read-only query validation and execution limits
efa7793 test(sql): cover text-to-SQL safety and common analytical queries
8338e87 feat(exposure): implement deterministic equity-sector calculations
ae7a84d test(exposure): cover bond exclusions, normalization and edge cases
bca3e6a feat(graph): add optional embedded FalkorDBLite graph adapter
017d63f feat(retrieval): ingest graph metadata and implement verified retrieval/fallback
956fe8e feat(ai): connect Groq structured planning and intent routing
a66629f feat(agent): integrate SQL, exposure, graph context and trace
5ad001a fix: close SQLite handles and bound manifests, results and weight precision
9f0904a feat(eval): add independent ground-truth evaluator and reporting
811055a fix(agent): verify auditable market-value plans before accepting results
8330d6e feat(cli): deliver portable commands and interactive terminal workspace
f8d43ae feat(tui): add expandable execution traces, tool views and shortcuts
cf8d271 fix(agent): preserve filtered metrics and equivalent SQL audit forms
48803c7 ci: verify Python builds and safety on macOS Windows and Linux
534cb85 fix(deps): upgrade filelock past known security advisories
4604751 fix(data): support SQLite builds without extension loading
11de527 test: respect Windows permissions and isolate native graph failure branches
f214fcc test(tui): scroll copy controls into view across terminal sizes
```

CI: [all eight jobs passed](https://github.com/rachitkothadia/PL-Capital-Round-2/actions/runs/42397569079), covering macOS/Windows/Linux core on Python 3.12/3.13, Linux Python 3.14, and native Linux graph integration.

The final documentation commit cannot include its own hash; the final response supplies that hash. Local `.work/checkpoints.log` records each verified push. CI status and final remote match are checked after the final push.

## Launch and artifacts

From the configured checkout: `uv run pl-capital`. For evaluation: `uv run pl-capital eval --live --report reports/evaluation.json`. The product is a local terminal application; no public terminal server, website or package registry deployment was created.

Local ignored evidence: reports/live-release.json (latest live run), reports/dependency-audit.json, reports/package-audit.json, reports/tui-acceptance.json and reports/tui-overview.png. The overview image re-renders the saved actual live acceptance answers in color; it is not a fabricated model result. Final wheel/source archives are in dist/.

Specification note: the requested PL_Capital_Codex_Master_Prompt_Enhanced.md and Section 16 were absent. The complete available PL_Capital_Codex_Master_Prompt.md (0–15), plus the explicit capability/research/security instructions in the request, governed execution. MAIN-TASK-Markdown.txt was absent; the supplied assignment README and requirements were preserved verbatim under assignment-original/.
