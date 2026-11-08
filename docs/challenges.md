# Advanced challenge scoring

The twenty advanced questions are separate from the official ten-question assessment. Their SQL references must agree with independently implemented Python calculations before an agent answer is scored. Scoring does not change the questions, relax required measures, rerun a model, or repair an agent's missing output.

## Semantic columns and units

Columns may be reordered or use a documented alias only when that alias maps uniquely within the question's reference schema. Unknown columns, competing aliases for the same measure, malformed shapes, and unsupported alternate layouts remain inconclusive. Numeric tolerance is unchanged: absolute `1e-6` or relative `1e-10`. Complete row sets, duplicate counts, required ranking, nulls, and every requested measure remain checked. Missing required columns fail, even when other returned values are correct.

New recognized aliases include:

- `top_market_sector` / `top_market_pct`: value-based winning sector / its percentage; `gap_pct`: the required signed percentage-point gap.
- `total_stock_value`: total equity market value; `discrepancy_pct`: the signed recorded-weight discrepancy in percentage points.
- `ratio` / `percentage_of_aum`: holdings-to-AUM ratio / its percentage; `abs_percentage_point_diff`: absolute percentage-point discrepancy.
- `fraction`: the fraction of all supplied equity market value represented by a security.
- `matches_current`, `max_len`, `percentage`, and `obs_count`: the close/current-price match flag, longest decline count, intraday range percentage, and observation count, respectively, within the applicable question schemas.
- `first_var`, `last_var`, `abs_magnitude_change`, and `total_transaction_fees`: first/last stored VaR, signed change in absolute VaR magnitude, and total transaction fees.
- `bond_share` / `bond_share_fraction`: a fractional share of the portfolio's bond market value, converted to the reference's percentage by multiplying by 100 exactly once.

No conversion is inferred from the magnitude of a value. In particular, a negative signed discrepancy cannot be replaced by an absolute discrepancy; a ratio cannot be substituted for a percentage without an explicit alias-unit rule. Existing fractional Jaccard/equity-share/AUM-ratio percentage aliases retain their documented conversion. Other source risk/performance numbers retain the supplied stored units.

## Optional descriptive fields are checked

References retain their original `columns`/`rows` shapes. A separate `optional_columns` mapping supplies row-aligned `company_name` for security-symbol rows and `sector_description` for sector-name rows where the base reference omits those fields. These are derived from the supplied SQLite catalogs. Independent Python reference calculations reconstruct the descriptive values from raw source records; `verify_references` compares both the financial values and these optional fields.

When an agent returns either description, the comparator checks it alongside every financial field. An incorrect company or description fails; descriptions are never silently discarded and cannot satisfy an omitted calculation. Extra metadata without an independently grounded reference remains inconclusive. Saved answers must be rescored against freshly generated references to use this enrichment; an old saved reference cannot establish a new field's correctness.

## Recorded offline rescore

The saved `reports/gemini-only/advanced.json` answers, timestamped 2026-11-08 10:58:22 UTC, originally recorded 2 pass, 3 fail, and 15 inconclusive. An offline rescore against the current independently verified references produces **8 pass, 10 fail, and 2 inconclusive**. This is a comparator rescore of existing answers, **not a new live evaluation or improvement in model output**.

Passing saved answers are 1, 3, 7, 9, 13, 17, 19, and 20. Failures include the wrong discrepancy sign, only five of thirteen AUM rows, omitted denominators/required fields, and incorrect decline-streak boundaries. The alternate sector/bond union layout in question 2 and risk-group layout in question 8 remain inconclusive. No unsupported layout was declared correct.

Focused verification: `uv run pytest -q tests/test_round3_challenges.py tests/test_challenges.py` passes 42 tests. `verify_references` reports 20/20 SQL-versus-Python references, including descriptive enrichment. Mutation tests reject incorrect financial values, missing fields, duplicate rows, reversed ranking, double-converted bond shares, wrong descriptions, and deliberately corrupted SQL metadata enrichment.

## Separate Round 3 live-answer rescore

The newly saved `reports/round3/advanced-live.json` recorded 9 pass, 4 fail, and 7 inconclusive. After inspecting its unknown column meanings and validating explicit units, an **offline rescore of those same answers** yields **11 pass, 8 fail, and 1 inconclusive**, saved separately as `reports/round3/advanced-rescored.json`. The report preserves the source timestamp, original counts, and each question's original status/reason. No model call occurred during rescoring; these counts must not be represented as a second live run.

Additional supported aliases are `weight_winner`/`weight_winner_pct`, `market_winner`/`market_winner_pct`, `gap_pct_points`, `name_a`/`name_b`, `fraction_of_total`, `price_match`, and `interval_start`/`interval_end`. They retain the existing units and sign conventions. For the holding-discrepancy question, `calculated_weight` means the fractional valuation-derived equity share and `normalized_recorded_weight` means the fractional recorded equity share; each converts to its percentage reference by multiplying by 100 once. Incorrect units still fail; no percentage is inferred from magnitude.

The extra accepted aliases turn questions 7 and 9 into checked passes. They expose rather than excuse other problems: question 1's gap is 2.0 instead of the required approximately 9.20027 percentage points; questions 5/6/11/15/16/19 omit rows or required fields; question 12 returns zero rows where four are required. Question 2's separate stock/bond layout remains inconclusive. The saved baseline rescore above remains a separate historical result.

Latest verification: 48 focused challenge tests pass, and the challenge/evaluator/scenario regression command passes 107 tests. New mutation cases reject incorrect gap signs, missing rows, wrong units, and omitted equity denominators. Independent SQL/Python references remain 20/20.

## Complete High/Low tall representation

Question 8 also accepts a complete tall result with `symbol`, `target_risk_level`, `distinct_portfolios`, `total_quantity`, and `total_market_value`. Its evaluation-only adapter pivots exactly one High and one Low row per symbol into the original six risk-group measures before applying the same independently verified comparison. It does not sum duplicate group rows, invent an absent group, omit a security, or infer a different denominator. Missing/duplicate groups, unknown risk levels, wrong values/units, and incomplete populations fail. Unknown or duplicate columns remain inconclusive rather than being discarded. Optional `company_name` must agree between both groups and match the source-backed company name.

An empty tall result can pass only with all five columns present and an independently verified empty population. Tests additionally create a genuine nonempty High/Low overlap from the source holdings, compare independently aggregated tall SQL with the wide SQL/Python reference, and reject negative mutations. This avoids treating empty results as evidence that nonempty conversion works. `is_current_match` is also accepted as a price-match flag alias, with a flipped-flag mutation required to fail.

The separate saved `reports/round3/advanced-final.json` records 12 pass, 2 fail, and 6 inconclusive before this rescore. The offline `reports/round3/advanced-final-rescored.json` records **13 pass, 3 fail, and 4 inconclusive**, with 20/20 independent references. Question 8's complete empty tall output becomes a pass. Question 5's newly recognized AUM-coverage alias exposes a wrong signed difference, so that answer fails. Existing provider-unavailable cases 3, 4, 7, and 11 remain inconclusive; case 12's execution failure remains a failure. No model calls, recovered provider results, or corrected production answers are implied. Source report hash/timestamp and original statuses are preserved.

Verification after this addition: 59 focused challenge tests; 118 challenge/evaluator/scenario regression tests, all passed. Ruff passes. Earlier saved-run counts above are historical, separate rescoring records.


## Final paced verification (9 November 2026)
The complete paced Flash Lite live run attempted all twenty questions: 13 passed, three failed, and four had unfamiliar aliases. An offline rescore of those exact answers, with independently tested identifier/NAV/price-match aliases and unchanged financial tolerances, produces **17 pass, 3 fail, 0 inconclusive**. No model answer was replaced during rescoring. Remaining failures are winner output identity, a missing sector-weight intermediate, and invalid decline-streak SQL. Stronger Gemini 3 Flash Preview successfully answered those individual questions, but its full live run was blocked by the project's 20-request daily free-tier quota. See the release report for separate batch results; no combined 20/20 live claim is made.
