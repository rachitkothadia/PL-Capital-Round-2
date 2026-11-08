# Capability and adoption audit

Implementation host: macOS / Apple silicon; Python 3.13 via uv. Core target: Python 3.12–3.14, Windows/macOS/Linux.

Native tools inspected: shell, patching, Git, authenticated GitHub CLI, 360 advertised tool definitions, web search, local browser/computer tools, and three available subagent slots. GitHub connector returned 404 for this private repository; authenticated `gh` confirmed private visibility, admin permission and default branch `main`. Git operations use `gh`/Git; no account permissions changed.

Configured MCP names were inspected without printing server credentials. Context7 is configured but its tools are unavailable in this session; official documentation is the fallback. Other available service connectors (MongoDB, Hostinger, website/component design) are unrelated to a local Python terminal assessment and receive no source data. VS Code/Cursor command-line extensions are absent. No unnecessary plugin installed.

Installed Graphify and Tokenade are retained. Graphify initial extraction lacked tree-sitter-sql; installed the declared SQL extra (tree-sitter-sql 0.3.11) into Graphify's own environment. Graphify is navigation only, separate from the product's FalkorDBLite GraphRAG.

Local Superpowers workflows reviewed: test-driven development, systematic debugging and verification before completion. Research subagent reviews primary SDK docs and upstream skill licenses. Code/security reviewers will have bounded file ownership; only the root agent commits and pushes.

Only `PL_Capital_Codex_Master_Prompt.md` exists locally (sections 0–15). The requested Enhanced filename and section 16 are absent. The complete available specification plus the user's explicit discovery, security, research and implementation requirements govern the work. `MAIN-TASK-Markdown.txt` is absent; the supplied README is preserved verbatim under assignment-original.

External source code and scripts are not executed to install agent workflows. No assessment data or credentials are sent to unrelated services. Groq receives only bounded question/schema/entity context required for the requested agent. Secrets remain in ignored local configuration.

## Capabilities genuinely used

- Local inventory found 810 installed skill files and 34 cached plugin manifests across four bundled/cache roots. Only relevant instructions were loaded; unneeded extensions were not installed. The exposed catalogue advertised 360 tools at initial discovery. VS Code/Cursor extension directories and command-line launchers were absent.
- Context7 remained unavailable to the root but became available in child agents. The UI agent genuinely resolved and queried Textual (`/websites/textual_textualize_io`) and uv (`/astral-sh/uv`); the evaluator agent resolved and queried sqlglot (`/tobymao/sqlglot`). Official web documentation covered Groq, FalkorDBLite, SQLite/Python, packaging and OpenAI extension guidance.
- Research/graph, UI/CLI, and evaluator/security subagents had disjoint file ownership. Root coordinated every commit/push. Security review identified and reproduced open SQLite handles at rename, invalid manifests, late output caps and Decimal overflow; all received failing regressions and fixes. A later review caught overbroad metric verification and equivalent-SQL rejection; those were corrected too.
- Superpowers test-first/debugging/verification instructions were used locally. Sentry's Apache-2.0 commit, code-review, secret-serialization and skill-scanner instructions were reviewed without installing/executing its scripts. Native staged-source scanning, adversarial tests and dependency advisory checks cover the relevant needs.
- No OpenCode source/assets copied. Textual/Rich/sqlglot/Pydantic/filelock/platformdirs are MIT; Groq SDK Apache-2.0; python-dotenv BSD-3-Clause. Optional FalkorDBLite wrapper BSD-3-Clause and native engine SSPLv1 are separately acknowledged. Public primary references and license links appear in THIRD_PARTY_NOTICES.md, README and graph documentation.

Primary resources reviewed: [OpenAI skills](https://developers.openai.com/codex/skills), [plugins](https://developers.openai.com/codex/plugins), [Superpowers](https://github.com/obra/superpowers), [Sentry skills](https://github.com/getsentry/skills), [Groq structured outputs](https://console.groq.com/docs/structured-outputs), [Textual testing](https://textual.textualize.io/guide/testing/), [FalkorDBLite](https://github.com/FalkorDB/falkordblite), [Python SQLite](https://docs.python.org/3.13/library/sqlite3.html), [sqlglot AST](https://github.com/tobymao/sqlglot/blob/main/posts/ast_primer.md), and [uv packaging](https://docs.astral.sh/uv/guides/package/).

## Dependency advisory remediation

The independent packaging/security audit used reviewed PyPA pip-audit 2.10.1 against public locked package names/versions only. It found 13 known filelock advisories in the initially resolved 3.32.7. The runtime floor was moved to the patched 4.x release line and locked to 4.2.9 after reviewing upstream API compatibility, MIT license, Python support and changelog. Fresh audit: 42 public packages, zero known vulnerabilities, zero skips. Initial findings and remediation remain in the local audit report. No assessment source was uploaded to the advisory service.

Real CI exposed macOS SQLite builds compiled without enable_load_extension, plus two Windows-only test assumptions (POSIX mode bits and an unreachable dependency-failure branch). A capability check and explicit security regression preserve the authorizer boundary; Windows tests now check relevant native behavior without claiming POSIX ACL semantics. No unsupported graph integration was labeled passed on Windows.

## Second-pass refinement
The existing project was preserved. The refinement and twenty-question documents were read in full; the requested Enhanced master filename remains unavailable, so the available original master and newer refinement instructions were used. Baseline tests, a PTY launch, saved real-answer UI replays and native graph timing reproduced the reported issues before fixes.

The root used native shell/Git/uv/pytest/Ruff, installed Textual APIs, fresh wheel installation, pbcopy/pbpaste, Graphify/Tokenade and official primary documentation. Existing scoped UI, graph/research and evaluator subagents contributed disjoint files; root integrated and retested their output and alone coordinated Git. No new blanket plugin or community script bundle was installed. The root's Context7 tools remained unavailable; child access and official documentation were used where available. The GitHub connector's private-repository limitation was handled with authenticated GitHub CLI.

Actual second-pass evidence includes theme style/contrast tests at four terminal sizes, a real macOS clipboard round trip with restoration, two live 20B questions through Textual Pilot, native graph operation, independent SQL/Python checks for twenty questions, two complete advanced live runs, and an official evaluator rerun. A default 120B rerun hit its daily token allowance; reports preserve provider failures rather than relabeling them correct. [Groq rate-limit documentation](https://console.groq.com/docs/rate-limits) informed diagnosis; private provider headers/bodies/keys were not published. Full results, commit IDs and limitations are in the [refinement report](refinement-report.md).
