# Third-party acknowledgements

The interface is independently implemented; [OpenCode](https://github.com/anomalyco/opencode) inspired interaction patterns only. No OpenCode source, logo or assets are copied; no affiliation is claimed.

Runtime dependencies remain separate upstream packages under their own licenses: Textual, Rich, sqlglot, Pydantic, platformdirs and filelock (MIT); python-dotenv (BSD-3-Clause); Groq Python SDK (Apache-2.0). Consult installed distribution metadata/upstream license files for exact notices. No third-party source is vendored into this implementation.

Optional [FalkorDBLite](https://github.com/FalkorDB/falkordblite) wrapper uses BSD-3-Clause; the separately supplied [FalkorDB engine](https://github.com/FalkorDB/FalkorDB/blob/master/LICENSE.txt) uses SSPL v1. The core wheel declares an optional dependency and does not bundle native engine binaries. Do not assume the graph engine shares the wrapper license.

Development workflow research reviewed [Superpowers](https://github.com/obra/superpowers) (MIT), [Sentry skills](https://github.com/getsentry/skills) (Apache-2.0), and official [OpenAI skills guidance](https://developers.openai.com/codex/skills). Relevant instruction workflows were applied; external installer/scanner scripts were not executed and no new blanket plugin bundle was installed.

GitHub workflow actions are pinned to reviewed upstream release commits. actions/checkout and astral-sh/setup-uv are MIT-licensed; workflow permission is limited to repository contents read, checkout credential persistence and dependency caches are disabled, and no Groq secret is configured in CI.
