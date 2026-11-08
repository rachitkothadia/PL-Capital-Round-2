# Gemini-only verification

The active and default model is Gemini 3.1 Flash Lite, verified with the newly supplied private key. The prior provider adapter, SDK dependency, model choices and local credentials were removed. Historical reports were moved to ignored local archives; published Git history is preserved.

Fresh real-agent official evaluation: **10/10 (100%)**. Fresh twenty-question advanced evaluation: **2 pass, 3 fail, 15 inconclusive**, with **20/20 independent reference checks**. Inconclusive cases are not counted as passing. Machine-readable reports are retained locally in `reports/gemini-only/`.

The local regression suite passed **268 tests**, with **7 optional native graph integration tests skipped** after the core environment was synchronized. SQL validation, deterministic exposure, evaluator and terminal regressions remain covered. Gemini credentials stay in ignored local configuration and are never embedded in launch scripts or source.

The new account rejected retired 2.5 models for new users. Available 3.1 Flash Lite and 3 Flash Preview generated successfully; the stable Flash Lite model was selected for the complete evaluation. No prior-provider answer was substituted. Advanced compound-query reliability remains limited; no perfect challenge accuracy is claimed.
