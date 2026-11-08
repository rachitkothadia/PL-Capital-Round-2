# Gemini provider integration and verification

Gemini was added at the repository owner's explicit request after the original Groq assessment implementation. Both providers use the existing typed Plan, SQLite query boundary, Decimal exposure calculator, terminal interface and independent evaluators. Original data and official references are unchanged.

## Configuration

The current `.env.example` selects `LLM_PROVIDER=gemini` and `GEMINI_MODEL=gemini-2.5-pro`; configure `GEMINI_API_KEY` privately. Flash and Flash Lite are supported alternatives. `--model` selects the matching provider and key. Groq remains available through its original two model IDs and `GROQ_API_KEY`. Existing installations without `LLM_PROVIDER` retain Groq for compatibility. There is no automatic provider fallback.

The native Gemini API uses a fixed Google host, key header, strict JSON schema, bounded input/output, nonstreaming plan acceptance, at most three transport attempts, and safe errors. Thought parts are excluded. The model cannot bypass the existing read-only SQL protections or supply financial arithmetic in place of local tools. A cross-provider model switch closes the previous client and selects the other key without changing dataset/cache paths. Missing destination credentials preserve the current provider.

## Actual results — 8 November 2026

The supplied key was stored only in ignored owner-only local configuration. Google's model-list endpoint returned HTTP 200, confirming authentication and listing Gemini 2.5 Pro/Flash. Actual generation requests to both Pro and Flash returned HTTP 403 with an outstanding-balance billing error. Switching models did not resolve that project/account restriction.

All ten official questions and all twenty advanced questions were attempted through the real Gemini-backed agent:

| Check | Actual result |
| --- | --- |
| Official questions | 10 attempted; all 10 blocked by provider billing; no valid answer to score |
| Advanced questions | 20 attempted; 20 inconclusive due to provider billing; none counted as passing |
| Advanced references | 20/20 independent SQL/Python reference checks passed |
| Gemini live analytical accuracy | Unmeasured; no successful generation was available |

The official JSON report mechanically records 0/10 accepted answers; this is service unavailability, not a measured 0% analytical accuracy. No model-generated SQL reached execution during the blocked attempts. No Groq answer was substituted. Raw machine-readable reports remain local under ignored `reports/gemini/` (`official.json`, `advanced.json`, `flash-probe.json`, `doctor.json`). They contain safe errors and no API key.

**285 offline tests passed** in the final local regression run. Offline verification covers native request/schema/header contracts, Pydantic plan validation, token accounting, streamed-response handling, input/output bounds, bounded transient/network retries, long retry-delay handling, nonretryable billing/auth errors, credential redaction, separate-key selection and provider switching. These mocked provider tests are not live Gemini accuracy evidence. The full existing suite retests all four mandatory assessment components and the terminal.

A successful Gemini generation/schema compatibility check and valid live answer accuracy remain blocked until Google restores generation access. Resolve the billing status at [Google AI Studio billing](https://aistudio.google.com/billing), then rerun:

```sh
uv run pl-capital eval --live --model gemini-2.5-pro --report reports/gemini-official.json
uv run pl-capital challenges --live --model gemini-2.5-pro --report reports/gemini-advanced.json
```

`doctor` checks configuration/dependencies without making a generation request; its readiness flag does not prove that billing, model access or quotas permit live generation.
