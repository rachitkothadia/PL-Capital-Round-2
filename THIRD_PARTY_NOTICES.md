# Third-party acknowledgements

The interface is independently implemented; [OpenCode](https://github.com/anomalyco/opencode) inspired interaction patterns only. No OpenCode source, logo or assets are copied; no affiliation is claimed.


[FalkorDBLite](https://github.com/FalkorDB/falkordblite) wrapper uses BSD-3-Clause; the separately supplied [FalkorDB engine](https://github.com/FalkorDB/FalkorDB/blob/master/LICENSE.txt) uses SSPL v1. The core wheel declares a platform-marked default dependency on macOS/Linux and does not bundle native engine binaries. The graph extra remains available for compatibility; native Windows excludes the dependency. Do not assume the graph engine shares the wrapper license.

Development workflow research reviewed [Superpowers](https://github.com/obra/superpowers) (MIT), [Sentry skills](https://github.com/getsentry/skills) (Apache-2.0), and official [OpenAI skills guidance](https://developers.openai.com/codex/skills). Relevant instruction workflows were applied; external installer/scanner scripts were not executed and no new blanket plugin bundle was installed.


Gemini integration uses the native Google Generative Language API through the existing [HTTPX](https://github.com/encode/httpx) dependency (BSD-3-Clause), now declared directly. No Google SDK, external agent bundle or installer script is added. [Google API reference](https://ai.google.dev/api/generate-content) and [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output) informed the adapter.

Current runtime dependencies: Textual, Rich, sqlglot, Pydantic, platformdirs and filelock (MIT); python-dotenv and HTTPX (BSD-3-Clause). Gemini uses the native Google API, without a provider SDK.
