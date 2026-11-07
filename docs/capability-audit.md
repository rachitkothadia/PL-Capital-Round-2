# Capability and adoption audit

Implementation host: macOS / Apple silicon; Python 3.13 via uv. Core target: Python 3.12–3.14, Windows/macOS/Linux.

Native tools inspected: shell, patching, Git, authenticated GitHub CLI, 360 advertised tool definitions, web search, local browser/computer tools, and three available subagent slots. GitHub connector returned 404 for this private repository; authenticated `gh` confirmed private visibility, admin permission and default branch `main`. Git operations use `gh`/Git; no account permissions changed.

Configured MCP names were inspected without printing server credentials. Context7 is configured but its tools are unavailable in this session; official documentation is the fallback. Other available service connectors (MongoDB, Hostinger, website/component design) are unrelated to a local Python terminal assessment and receive no source data. VS Code/Cursor command-line extensions are absent. No unnecessary plugin installed.

Installed Graphify and Tokenade are retained. Graphify initial extraction lacked tree-sitter-sql; installed the declared SQL extra (tree-sitter-sql 0.3.11) into Graphify's own environment. Graphify is navigation only, separate from the product's FalkorDBLite GraphRAG.

Local Superpowers workflows reviewed: test-driven development, systematic debugging and verification before completion. Research subagent reviews primary SDK docs and upstream skill licenses. Code/security reviewers will have bounded file ownership; only the root agent commits and pushes.

Only `PL_Capital_Codex_Master_Prompt.md` exists locally (sections 0–15). The requested Enhanced filename and section 16 are absent. The complete available specification plus the user's explicit discovery, security, research and implementation requirements govern the work. `MAIN-TASK-Markdown.txt` is absent; the supplied README is preserved verbatim under assignment-original.

External source code and scripts are not executed to install agent workflows. No assessment data or credentials are sent to unrelated services. Groq receives only bounded question/schema/entity context required for the requested agent. Secrets remain in ignored local configuration.
