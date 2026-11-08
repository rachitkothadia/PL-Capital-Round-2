# PL Capital: twenty additional challenge questions

These are the exact additional question bodies from the supplied refinement material. They are separate from the **ten official ground-truth questions**. References use the supplied September–October 2023 snapshot, never live prices.

## Run and interpret results

From the configured checkout: `uv run pl-capital challenges --references` checks references without Groq. `uv run pl-capital challenges --live --report reports/advanced.json` calls the actual agent at most once per question (its existing bounded SQL correction may add one planning call). Select a bounded subset with `--ids 1,5,12`.

Reference verification executed all twenty trusted read-only SQL queries and compared each with separately implemented Python grouping, sets, Decimal arithmetic and observation-order scans: **20/20 reference checks passed**. This is **not a live Groq accuracy score**. Live status is reported by the evaluation command, not stored as an answer in this catalog.

The scorer accepts documented semantic column aliases and reordered columns, and validates any recognized optional audit fields. Requested numerical measures, full row sets, duplicate counts and requested ranking must match. Numeric tolerance is absolute 1e-6 / relative 1e-10; it does not intentionally hide meaningful small differences. Explicitly labeled percent/fraction conversions are normalized. Qualitative explanations are recorded for human review rather than graded by another model.

- `pass`: independently verified tabular result.
- `fail`: known wrong values, missing measures, incomplete result, query error or incorrect required ranking.
- `unsupported`: the agent explicitly cannot perform the legitimate compound analysis or selects a tool incapable of its output.
- `inconclusive`: provider/configuration unavailable, clarification pending, invalid reference or unfamiliar/ambiguous result shape requiring manual review.
- `not_run`: outside the selected IDs or bounded run. Unsupported, inconclusive and unrun cases never count as passing.

Only the challenge evaluator loads reference SQL. The production agent receives each question through its ordinary planning interface; it receives no reference SQL, case ID or expected answer. Reports retain actual SQL, results and independent references for audit. Result equality does not prove a SQL query correct on every future dataset.

## 1. recorded versus valuation-derived sector rankings

For each portfolio with stock holdings, identify its largest equity sector twice: first by the sum of `current_weight`, and second by `SUM(quantity * current_price)`. Show portfolios where the winning sector differs, including both percentages and the gap in percentage points. Define denominators and ties explicitly.

**Why tricky:** The two sector rankings use different stock-only denominators; mixed assets, ties and changed winners must not be conflated.
**Tables:** portfolios, holdings, securities, sectors.
**Output shape:** One row per changed winning portfolio: both winning sectors, their own normalized percentages, value-top minus recorded-top percentage-point gap, and both stock denominators.
**Required numerical/identity fields:** portfolio_name, recorded_top_sector, recorded_top_pct, value_top_sector, value_top_pct, top_gap_pp.
**Verified reference rows:** 1. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Stocks only; recorded percentages divide by stock recorded-weight sum and valuation percentages by stock holding market value.
- Choose the alphabetically first sector on an exact within-method tie; compare those deterministic winners.
- top_gap_pp = value_top_pct - recorded_top_pct; omit unchanged winners and undefined/nonpositive denominators.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH e AS (SELECT p.portfolio_id,p.portfolio_name,sec.sector_name,SUM(h.current_weight) AS sector_weight,SUM(h.quantity*s.current_price) AS sector_value FROM portfolios p JOIN holdings h USING(portfolio_id) JOIN securities s USING(security_id) JOIN sectors sec USING(sector_id) WHERE s.asset_type='Stock' GROUP BY p.portfolio_id,p.portfolio_name,sec.sector_name), t AS (SELECT portfolio_id,SUM(sector_weight) AS equity_weight_total,SUM(sector_value) AS equity_market_value FROM e GROUP BY portfolio_id), r AS (SELECT e.*,t.equity_weight_total,t.equity_market_value,ROW_NUMBER() OVER(PARTITION BY e.portfolio_id ORDER BY e.sector_weight DESC,e.sector_name) AS wr,ROW_NUMBER() OVER(PARTITION BY e.portfolio_id ORDER BY e.sector_value DESC,e.sector_name) AS vr FROM e JOIN t USING(portfolio_id) WHERE t.equity_weight_total>0 AND t.equity_market_value>0) SELECT w.portfolio_name,w.sector_name AS recorded_top_sector,100.0*w.sector_weight/w.equity_weight_total AS recorded_top_pct,v.sector_name AS value_top_sector,100.0*v.sector_value/v.equity_market_value AS value_top_pct,100.0*v.sector_value/v.equity_market_value-100.0*w.sector_weight/w.equity_weight_total AS top_gap_pp,w.equity_weight_total,w.equity_market_value FROM r w JOIN r v ON w.portfolio_id=v.portfolio_id AND v.vr=1 WHERE w.wr=1 AND w.sector_name<>v.sector_name ORDER BY w.portfolio_name
```

## 2. mixed-asset sector reconciliation

For the Conservative Income Fund and Balanced Portfolio, show bond weight, stock weight, and each stock-sector allocation both as a percentage of total recorded portfolio weight and as a percentage of the equity-only weight. Also show whether recorded weights sum to exactly 100%.

**Why tricky:** Two funds and three recorded-weight sums must reconcile without including bond sectors in the equity breakdown.
**Tables:** portfolios, holdings, securities, sectors.
**Output shape:** One row per fund/stock sector with bond/equity/total weight sums, sector weight, both percentages and a 100%-coverage flag.
**Required numerical/identity fields:** portfolio_name, sector_name, bond_weight, equity_weight, recorded_total, portfolio_pct, equity_pct.
**Verified reference rows:** 6. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Weights and totals are stored fractions; whole-recorded-portfolio percentage divides by recorded_total, not AUM.
- The two specified funds each have recorded_total=1, so this also equals the master tool's whole-portfolio contribution.
- The equality flag permits 1e-10 binary-summation noise; it does not fill or normalize missing recorded weights.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH t AS (SELECT p.portfolio_id,p.portfolio_name,SUM(CASE WHEN s.asset_type='Bond' THEN h.current_weight ELSE 0 END) AS bond_weight,SUM(CASE WHEN s.asset_type='Stock' THEN h.current_weight ELSE 0 END) AS equity_weight,SUM(h.current_weight) AS recorded_total FROM portfolios p JOIN holdings h USING(portfolio_id) JOIN securities s USING(security_id) WHERE p.portfolio_name IN ('Conservative Income Fund','Balanced Portfolio') GROUP BY p.portfolio_id,p.portfolio_name), e AS (SELECT h.portfolio_id,sec.sector_name,SUM(h.current_weight) AS sector_weight FROM holdings h JOIN securities s USING(security_id) JOIN sectors sec USING(sector_id) WHERE s.asset_type='Stock' GROUP BY h.portfolio_id,sec.sector_name) SELECT t.portfolio_name,e.sector_name,t.bond_weight,t.equity_weight,t.recorded_total,e.sector_weight,100.0*e.sector_weight/NULLIF(t.recorded_total,0) AS portfolio_pct,100.0*e.sector_weight/NULLIF(t.equity_weight,0) AS equity_pct,CASE WHEN ABS(t.recorded_total-1.0)<1e-10 THEN 1 ELSE 0 END AS weights_sum_to_100 FROM t JOIN e USING(portfolio_id) ORDER BY t.portfolio_name,e.sector_name
```

## 3. concentration stress test

Rank all portfolios with equities by their market-value-based sector Herfindahl concentration index (sum of squared normalized sector fractions). Show the effective number of sectors, `1 / HHI`, top sector, stock-market-value denominator, and how you handle zero-equity portfolios.

**Why tricky:** HHI uses sector fractions, not percentages, AUM or per-security concentration; 1/HHI is undefined without positive equity value.
**Tables:** portfolios, holdings, securities, sectors.
**Output shape:** One positive-equity portfolio row, descending HHI, with HHI, effective sector count, top sector and total stock market value.
**Required numerical/identity fields:** portfolio_name, hhi, effective_sector_count, top_sector, equity_market_value.
**Verified reference rows:** 11. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Exclude zero-equity/nonpositive-equity-value funds from the ranking and explicitly document their undefined HHI rather than report zero.
- Sector fractions sum to one over stock market value; alphabetical top-sector tie break; HHI ties sort by portfolio name.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH e AS (SELECT h.portfolio_id,sec.sector_name,SUM(h.quantity*s.current_price) AS sector_value FROM holdings h JOIN securities s USING(security_id) JOIN sectors sec USING(sector_id) WHERE s.asset_type='Stock' GROUP BY h.portfolio_id,sec.sector_name), t AS (SELECT portfolio_id,SUM(sector_value) AS equity_market_value FROM e GROUP BY portfolio_id), r AS (SELECT e.*,t.equity_market_value,ROW_NUMBER() OVER(PARTITION BY e.portfolio_id ORDER BY e.sector_value DESC,e.sector_name) AS rn FROM e JOIN t USING(portfolio_id) WHERE t.equity_market_value>0), c AS (SELECT portfolio_id,SUM((sector_value/equity_market_value)*(sector_value/equity_market_value)) AS hhi,MAX(CASE WHEN rn=1 THEN sector_name END) AS top_sector,MAX(equity_market_value) AS equity_market_value FROM r GROUP BY portfolio_id) SELECT p.portfolio_name,c.hhi,1.0/c.hhi AS effective_sector_count,c.top_sector,c.equity_market_value FROM c JOIN portfolios p USING(portfolio_id) ORDER BY c.hhi DESC,p.portfolio_name
```

## 4. cross-portfolio weight anomalies

Find every portfolio whose `SUM(current_weight)` differs from 1.0 by more than 0.5 percentage points. Show the recorded sum, the discrepancy in percentage points, and whether it holds any bonds. Do not silently rescale the original recorded weights.

**Why tricky:** 0.5 percentage points means a fraction threshold of 0.005, strictly greater, and recorded weights must remain unscaled.
**Tables:** portfolios, holdings, securities.
**Output shape:** One anomalous portfolio row with recorded fraction sum, signed (sum-1)*100 discrepancy and bond-presence flag.
**Required numerical/identity fields:** portfolio_name, recorded_weight_sum, discrepancy_pp, has_bonds.
**Verified reference rows:** 1. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- The threshold is strict >0.005 on fractional recorded weight; round the comparison difference to 12 places to avoid binary boundary noise.
- Discrepancy is signed recorded-minus-target percentage points; do not silently replace it with an unsigned gap.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
SELECT p.portfolio_name,SUM(h.current_weight) AS recorded_weight_sum,100.0*(SUM(h.current_weight)-1.0) AS discrepancy_pp,MAX(CASE WHEN s.asset_type='Bond' THEN 1 ELSE 0 END) AS has_bonds FROM portfolios p JOIN holdings h USING(portfolio_id) JOIN securities s USING(security_id) GROUP BY p.portfolio_id,p.portfolio_name HAVING ABS(ROUND(SUM(h.current_weight)-1.0,12))>0.005 ORDER BY ABS(SUM(h.current_weight)-1.0) DESC,p.portfolio_name
```

## 5. AUM versus holdings mismatch

For every portfolio, compare recorded `total_aum` with `SUM(quantity * current_price)`. Show the dollar difference, ratio, percentage of AUM represented by listed holdings, and the five largest mismatches. Clearly distinguish AUM from holdings market value.

**Why tricky:** Every portfolio must remain visible while the largest five mismatches are identified; the listed holdings need not explain stored AUM.
**Tables:** portfolios, holdings, securities.
**Output shape:** All 13 portfolio rows ordered by absolute AUM-minus-listed-value difference; first five are the largest. Reference additionally supplies mismatch_rank and is_top_five flags.
**Required numerical/identity fields:** portfolio_name, total_aum, holdings_market_value, difference, holdings_to_aum_ratio, aum_coverage_pct.
**Verified reference rows:** 13. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- difference = total_aum - holdings_market_value; ratio = holdings_market_value / total_aum; coverage_pct = ratio*100.
- Return all portfolios; order by absolute mismatch descending/name ascending, making the first five unambiguous. Rank/flag columns are optional if this full ordering is retained.
- Missing holding valuations/AUM or zero AUM remain unavailable, not fabricated cash or zero coverage.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH v AS (SELECT p.portfolio_id,p.portfolio_name,p.total_aum,SUM(h.quantity*s.current_price) AS holdings_market_value FROM portfolios p LEFT JOIN holdings h USING(portfolio_id) LEFT JOIN securities s USING(security_id) GROUP BY p.portfolio_id,p.portfolio_name,p.total_aum), r AS (SELECT *,total_aum-holdings_market_value AS difference,ROW_NUMBER() OVER(ORDER BY ABS(total_aum-holdings_market_value) DESC,portfolio_name) AS mismatch_rank FROM v) SELECT portfolio_name,total_aum,holdings_market_value,difference,holdings_market_value/NULLIF(total_aum,0) AS holdings_to_aum_ratio,100.0*holdings_market_value/NULLIF(total_aum,0) AS aum_coverage_pct,mismatch_rank,CASE WHEN mismatch_rank<=5 THEN 1 ELSE 0 END AS is_top_five FROM r ORDER BY mismatch_rank
```

## 6. security-level weight mismatch

Within each portfolio, calculate each equity holding's share of stock market value, compare it with `current_weight` normalized over all equity weights, and return the ten largest absolute percentage-point discrepancies, including the security and portfolio names.

**Why tricky:** Each holding has two portfolio-specific stock-only denominators; comparison must use absolute percentage-point differences and preserve signed discrepancy separately if shown.
**Tables:** portfolios, holdings, securities.
**Output shape:** Top ten portfolio/security holdings with names, both normalized percentages, absolute gap and both stock denominators; raw weight/value and signed gap are optional audit columns.
**Required numerical/identity fields:** portfolio_name, symbol, company_name, equity_weight_total, equity_market_value, recorded_equity_pct, market_value_pct, abs_discrepancy_pp.
**Verified reference rows:** 10. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Exclude bonds before summing either denominator; recorded equity percent is current_weight/sum(stock weights)*100.
- Signed discrepancy, when included, is market-value percent minus recorded-equity percent; sort absolute gap descending then portfolio/symbol.
- Undefined/nonpositive denominators are not treated as zero discrepancies.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH e AS (SELECT p.portfolio_id,p.portfolio_name,s.symbol,s.company_name,h.current_weight,h.quantity*s.current_price AS holding_market_value FROM holdings h JOIN portfolios p USING(portfolio_id) JOIN securities s USING(security_id) WHERE s.asset_type='Stock'), t AS (SELECT portfolio_id,SUM(current_weight) AS equity_weight_total,SUM(holding_market_value) AS equity_market_value FROM e GROUP BY portfolio_id), r AS (SELECT e.*,t.equity_weight_total,t.equity_market_value,100.0*e.current_weight/t.equity_weight_total AS recorded_equity_pct,100.0*e.holding_market_value/t.equity_market_value AS market_value_pct FROM e JOIN t USING(portfolio_id) WHERE t.equity_weight_total>0 AND t.equity_market_value>0) SELECT portfolio_name,symbol,company_name,equity_weight_total,equity_market_value,current_weight,holding_market_value,recorded_equity_pct,market_value_pct,market_value_pct-recorded_equity_pct AS discrepancy_pp,ABS(market_value_pct-recorded_equity_pct) AS abs_discrepancy_pp FROM r ORDER BY abs_discrepancy_pp DESC,portfolio_name,symbol LIMIT 10
```

## 7. portfolio overlap graph

Identify pairs of distinct portfolios sharing at least three stock securities. Calculate intersection count, union count, and Jaccard similarity of their equity security sets; sort by similarity and use portfolio IDs to avoid duplicated pairs.

**Why tricky:** Holdings self-joins can double count common symbols and reverse the same pair; union is nA+nB-intersection.
**Tables:** portfolios, holdings, securities.
**Output shape:** One unordered ID-ascending portfolio pair, at least three common stocks, intersection/union counts and fractional Jaccard similarity descending.
**Required numerical/identity fields:** portfolio_a, portfolio_b, intersection_count, union_count, jaccard_similarity.
**Verified reference rows:** 20. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Security IDs define sets; portfolio_a_id < portfolio_b_id; no bond securities or duplicate pairs.
- Jaccard is intersection/union in [0,1], not percent; ties sort by the two IDs.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH e AS (SELECT DISTINCT h.portfolio_id,h.security_id FROM holdings h JOIN securities s USING(security_id) WHERE s.asset_type='Stock'), n AS (SELECT portfolio_id,COUNT(*) AS size FROM e GROUP BY portfolio_id), pairs AS (SELECT a.portfolio_id AS aid,b.portfolio_id AS bid,COUNT(*) AS intersection_count FROM e a JOIN e b ON a.security_id=b.security_id AND a.portfolio_id<b.portfolio_id GROUP BY a.portfolio_id,b.portfolio_id HAVING COUNT(*)>=3) SELECT pairs.aid AS portfolio_a_id,pairs.bid AS portfolio_b_id,pa.portfolio_name AS portfolio_a,pb.portfolio_name AS portfolio_b,pairs.intersection_count,na.size+nb.size-pairs.intersection_count AS union_count,1.0*pairs.intersection_count/(na.size+nb.size-pairs.intersection_count) AS jaccard_similarity FROM pairs JOIN n na ON na.portfolio_id=pairs.aid JOIN n nb ON nb.portfolio_id=pairs.bid JOIN portfolios pa ON pa.portfolio_id=pairs.aid JOIN portfolios pb ON pb.portfolio_id=pairs.bid ORDER BY jaccard_similarity DESC,pairs.aid,pairs.bid
```

## 8. high versus low risk shared stocks

Find stock symbols that appear in at least one High-risk portfolio and one Low-risk portfolio, and report the number of distinct portfolios in each group plus total quantity and market value in each risk group. Avoid duplicate counts from joins.

**Why tricky:** Joining high and low holdings directly multiplies rows; aggregate distinct portfolio counts and each group's quantities independently.
**Tables:** portfolios, holdings, securities.
**Output shape:** One stock symbol with positive distinct High and Low counts, and separate quantity/value totals for each group.
**Required numerical/identity fields:** symbol, high_portfolio_count, low_portfolio_count, high_quantity, low_quantity, high_market_value, low_market_value.
**Verified reference rows:** 0. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Risk means exact portfolios.target_risk_level values High/Low; Moderate holdings do not enter either group's measures.
- Each portfolio/security holding contributes once; market value is snapshot quantity*current_price.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
SELECT s.symbol,s.company_name,COUNT(DISTINCT CASE WHEN p.target_risk_level='High' THEN p.portfolio_id END) AS high_portfolio_count,COUNT(DISTINCT CASE WHEN p.target_risk_level='Low' THEN p.portfolio_id END) AS low_portfolio_count,SUM(CASE WHEN p.target_risk_level='High' THEN h.quantity ELSE 0 END) AS high_quantity,SUM(CASE WHEN p.target_risk_level='Low' THEN h.quantity ELSE 0 END) AS low_quantity,SUM(CASE WHEN p.target_risk_level='High' THEN h.quantity*s.current_price ELSE 0 END) AS high_market_value,SUM(CASE WHEN p.target_risk_level='Low' THEN h.quantity*s.current_price ELSE 0 END) AS low_market_value FROM holdings h JOIN portfolios p USING(portfolio_id) JOIN securities s USING(security_id) WHERE s.asset_type='Stock' AND p.target_risk_level IN ('High','Low') GROUP BY s.security_id,s.symbol,s.company_name HAVING COUNT(DISTINCT CASE WHEN p.target_risk_level='High' THEN p.portfolio_id END)>0 AND COUNT(DISTINCT CASE WHEN p.target_risk_level='Low' THEN p.portfolio_id END)>0 ORDER BY s.symbol
```

## 9. top equities across all funds

Find the top five stock securities by aggregate current holdings market value across all portfolios. For each, show its sector, distinct portfolio count, total shares, aggregate value, and fraction of the sum of ALL stock holdings' market value.

**Why tricky:** The denominator is all equity holdings, not the selected top five, security market cap, portfolio AUM or recorded weights.
**Tables:** holdings, securities, sectors.
**Output shape:** Five stock rows ranked by aggregate held market value with sector, portfolio count, shares, value, all-equity denominator and fractional share.
**Required numerical/identity fields:** symbol, sector_name, portfolio_count, total_quantity, market_value, equity_value_fraction.
**Verified reference rows:** 5. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Use all stock holding rows across all portfolios; security IDs define aggregation; alphabetical symbol tie break.
- equity_value_fraction is a fraction; explicitly labeled percentages can be converted by the comparator without changing the denominator.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH e AS (SELECT s.security_id,s.symbol,sec.sector_name,h.portfolio_id,h.quantity,h.quantity*s.current_price AS value FROM holdings h JOIN securities s USING(security_id) LEFT JOIN sectors sec USING(sector_id) WHERE s.asset_type='Stock'), t AS (SELECT SUM(value) AS total_equity_market_value FROM e), a AS (SELECT security_id,symbol,sector_name,COUNT(DISTINCT portfolio_id) AS portfolio_count,SUM(quantity) AS total_quantity,SUM(value) AS market_value FROM e GROUP BY security_id,symbol,sector_name) SELECT a.symbol,a.sector_name,a.portfolio_count,a.total_quantity,a.market_value,t.total_equity_market_value,a.market_value/NULLIF(t.total_equity_market_value,0) AS equity_value_fraction FROM a CROSS JOIN t ORDER BY a.market_value DESC,a.symbol LIMIT 5
```

## 10. sectors with no mapped securities

List sector definitions that currently have no security assigned, then verify whether any holding could nevertheless belong to those sectors. Explain the difference between an empty sector definition and a zero-weight sector exposure.

**Why tricky:** An unused dimension row differs from a held security whose recorded weight happens to be zero; left joins must retain absent mappings.
**Tables:** sectors, securities, holdings.
**Output shape:** Unused sector definitions with zero mapped-security count and zero holdings count; names/IDs and both counts independently checked.
**Required numerical/identity fields:** sector_name, security_count, holding_count.
**Verified reference rows:** 3. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Mapping uses securities.sector_id, independent of any current_weight value.
- Foreign keys mean an unused sector cannot receive a holding indirectly; zero-weight held securities are still mappings.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
SELECT sec.sector_id,sec.sector_name,COUNT(DISTINCT s.security_id) AS security_count,COUNT(h.holding_id) AS holding_count FROM sectors sec LEFT JOIN securities s USING(sector_id) LEFT JOIN holdings h USING(security_id) GROUP BY sec.sector_id,sec.sector_name HAVING COUNT(DISTINCT s.security_id)=0 ORDER BY sec.sector_name
```

## 11. windowed return extremes

Using historical closing prices, compute each stock's return from its first to its last observed close and identify the best and worst five. Show first and last dates and prices, return percentages, and whether `current_price` equals the last historical close. Do not call these 2026 returns.

**Why tricky:** First/last observations require date ordering; current_price is a separate field; ties and best/worst overlap need explicit treatment.
**Tables:** securities, historical_prices.
**Output shape:** Two labeled groups of five (best/worst), group rank, symbol, observation dates/closes, percent return, current price and equality flag.
**Required numerical/identity fields:** extreme, symbol, first_date, last_date, first_close, last_close, return_pct, last_close_matches_current.
**Verified reference rows:** 10. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Return=(last_close/first_close-1)*100 over the available historical window; require two observations and positive first close.
- Return ties break by symbol; take exactly five in each group, preserving an overlap as two group-labeled rows if the universe is small.
- Compare current_price and last close within 1e-9 arithmetic noise; no annualization or 2026 claim.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH o AS (SELECT s.security_id,s.symbol,s.current_price,hp.price_date,hp.close_price,ROW_NUMBER() OVER(PARTITION BY s.security_id ORDER BY hp.price_date) AS a,ROW_NUMBER() OVER(PARTITION BY s.security_id ORDER BY hp.price_date DESC) AS z,COUNT(*) OVER(PARTITION BY s.security_id) AS n FROM securities s JOIN historical_prices hp USING(security_id) WHERE s.asset_type='Stock'), b AS (SELECT security_id,symbol,current_price,MAX(CASE WHEN a=1 THEN price_date END) AS first_date,MAX(CASE WHEN z=1 THEN price_date END) AS last_date,MAX(CASE WHEN a=1 THEN close_price END) AS first_close,MAX(CASE WHEN z=1 THEN close_price END) AS last_close,MAX(n) AS observations FROM o GROUP BY security_id,symbol,current_price), v AS (SELECT *,100.0*(last_close/first_close-1.0) AS return_pct FROM b WHERE first_close>0 AND observations>=2), r AS (SELECT *,ROW_NUMBER() OVER(ORDER BY return_pct DESC,symbol) AS best_rank,ROW_NUMBER() OVER(ORDER BY return_pct,symbol) AS worst_rank FROM v), x AS (SELECT 'best' AS extreme,best_rank AS rank_in_group,symbol,first_date,last_date,first_close,last_close,return_pct,current_price,CASE WHEN ABS(current_price-last_close)<=1e-9 THEN 1 ELSE 0 END AS last_close_matches_current FROM r WHERE best_rank<=5 UNION ALL SELECT 'worst',worst_rank,symbol,first_date,last_date,first_close,last_close,return_pct,current_price,CASE WHEN ABS(current_price-last_close)<=1e-9 THEN 1 ELSE 0 END FROM r WHERE worst_rank<=5) SELECT * FROM x ORDER BY CASE extreme WHEN 'best' THEN 0 ELSE 1 END,rank_in_group
```

## 12. four-close losing streaks

Identify stock symbols that have at least three consecutive observed close-to-close declines (four price observations in order), and show their longest detected decline streak and date interval. Use trading observation order, not assumed calendar-day continuity.

**Why tricky:** A three-decline streak spans four closes, and its start is the observation preceding the first decline; weekends do not break observed-order streaks.
**Tables:** securities, historical_prices.
**Output shape:** One qualifying stock with longest decline count, start/end observation dates and observation_count=declines+1.
**Required numerical/identity fields:** symbol, longest_decline_streak, start_date, end_date.
**Verified reference rows:** 4. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- A decline is strict close<previous observed close; equality or increase breaks the run.
- Use LAG over observation date, not calendar-day gaps; for equal longest runs choose earliest start then earliest end.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH o AS (SELECT s.security_id,s.symbol,hp.price_date,hp.close_price,LAG(hp.close_price) OVER(PARTITION BY s.security_id ORDER BY hp.price_date) AS prev_close,LAG(hp.price_date) OVER(PARTITION BY s.security_id ORDER BY hp.price_date) AS prev_date FROM securities s JOIN historical_prices hp USING(security_id) WHERE s.asset_type='Stock'), f AS (SELECT *,CASE WHEN close_price<prev_close THEN 1 ELSE 0 END AS declined FROM o), i AS (SELECT *,SUM(CASE WHEN declined=0 THEN 1 ELSE 0 END) OVER(PARTITION BY security_id ORDER BY price_date ROWS UNBOUNDED PRECEDING) AS island FROM f), runs AS (SELECT security_id,symbol,island,COUNT(*) AS longest_decline_streak,MIN(prev_date) AS start_date,MAX(price_date) AS end_date FROM i WHERE declined=1 GROUP BY security_id,symbol,island), r AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY security_id ORDER BY longest_decline_streak DESC,start_date,end_date) AS rn FROM runs) SELECT symbol,longest_decline_streak,start_date,end_date,longest_decline_streak+1 AS observation_count FROM r WHERE rn=1 AND longest_decline_streak>=3 ORDER BY longest_decline_streak DESC,symbol
```

## 13. intraday range anomalies

Across the provided price history, find the ten highest `(high_price - low_price) / open_price * 100` observations for stocks, showing symbol, date, open/high/low prices, and percentage. Handle zero or missing open prices safely.

**Why tricky:** Rank observations rather than securities; exclude missing/zero open prices instead of inventing a denominator.
**Tables:** securities, historical_prices.
**Output shape:** Ten stock/date rows with open, high, low and intraday_range_pct descending.
**Required numerical/identity fields:** symbol, price_date, open_price, high_price, low_price, intraday_range_pct.
**Verified reference rows:** 10. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Require positive open and non-null high/low; percent=(high-low)/open*100.
- Ties break by symbol then observation date; no assumption of a continuous calendar series.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
SELECT s.symbol,hp.price_date,hp.open_price,hp.high_price,hp.low_price,100.0*(hp.high_price-hp.low_price)/hp.open_price AS intraday_range_pct FROM historical_prices hp JOIN securities s USING(security_id) WHERE s.asset_type='Stock' AND hp.open_price>0 AND hp.high_price IS NOT NULL AND hp.low_price IS NOT NULL ORDER BY intraday_range_pct DESC,s.symbol,hp.price_date LIMIT 10
```

## 14. latest synchronized performance and risk

For each portfolio with BOTH `portfolio_performance` and `risk_metrics`, join the records by the same portfolio AND same date, select its latest common date, and report one-month return, volatility, Sharpe ratio, 95% VaR, 95% CVaR, beta, and maximum drawdown. Do not multiply rows in a many-to-many join.

**Why tricky:** The latest individual dates can differ; joining only the portfolio ID multiplies time series and silently pairs unrelated observations.
**Tables:** portfolios, portfolio_performance, risk_metrics.
**Output shape:** One row per portfolio with a common observation date: latest common_date and seven stored performance/risk metrics.
**Required numerical/identity fields:** portfolio_name, common_date, return_1m, volatility, sharpe_ratio, var_95, cvar_95, beta, max_drawdown.
**Verified reference rows:** 4. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Require portfolio_id equality AND performance_date=calculation_date before finding the latest common date.
- Return/volatility/drawdown/VaR/CVaR preserve stored numeric units; only explicitly labeled *_pct conversions are normalized by scoring.
- Portfolios with no common date are unavailable and omitted, not filled with zero.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH c AS (SELECT pp.portfolio_id,pp.performance_date AS common_date,pp.total_return_1m AS return_1m,pp.volatility,pp.sharpe_ratio,rm.var_95,rm.cvar_95,rm.beta,pp.max_drawdown,ROW_NUMBER() OVER(PARTITION BY pp.portfolio_id ORDER BY pp.performance_date DESC) AS rn FROM portfolio_performance pp JOIN risk_metrics rm ON pp.portfolio_id=rm.portfolio_id AND pp.performance_date=rm.calculation_date) SELECT p.portfolio_name,c.common_date,c.return_1m,c.volatility,c.sharpe_ratio,c.var_95,c.cvar_95,c.beta,c.max_drawdown FROM c JOIN portfolios p USING(portfolio_id) WHERE c.rn=1 ORDER BY p.portfolio_name
```

## 15. NAV improvement across observed window

Of the portfolios with performance history, rank them by the change in NAV from their first to last available observation, showing absolute and percentage changes, both dates, and the number of observations. Distinguish NAV change from total investment return.

**Why tricky:** First/last NAV must be date-selected rather than MIN/MAX NAV; cash flows/distributions are absent, so NAV movement is not verified total return.
**Tables:** portfolios, portfolio_performance.
**Output shape:** Portfolio rows ranked by NAV percentage change with first/last dates/NAV, signed absolute change, percent change and observation count.
**Required numerical/identity fields:** portfolio_name, first_date, last_date, first_nav, last_nav, nav_change, nav_change_pct, observation_count.
**Verified reference rows:** 4. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Rank by (last_nav/first_nav-1)*100 descending then name; nav_change=last_nav-first_nav.
- Require observed history and positive first NAV; this is an observed NAV change, not total investment return or an annualized measure.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH o AS (SELECT portfolio_id,performance_date,nav,ROW_NUMBER() OVER(PARTITION BY portfolio_id ORDER BY performance_date) AS a,ROW_NUMBER() OVER(PARTITION BY portfolio_id ORDER BY performance_date DESC) AS z,COUNT(*) OVER(PARTITION BY portfolio_id) AS observation_count FROM portfolio_performance), b AS (SELECT portfolio_id,MAX(CASE WHEN a=1 THEN performance_date END) AS first_date,MAX(CASE WHEN z=1 THEN performance_date END) AS last_date,MAX(CASE WHEN a=1 THEN nav END) AS first_nav,MAX(CASE WHEN z=1 THEN nav END) AS last_nav,MAX(observation_count) AS observation_count FROM o GROUP BY portfolio_id) SELECT p.portfolio_name,b.first_date,b.last_date,b.first_nav,b.last_nav,b.last_nav-b.first_nav AS nav_change,100.0*(b.last_nav/b.first_nav-1.0) AS nav_change_pct,b.observation_count FROM b JOIN portfolios p USING(portfolio_id) WHERE b.first_nav>0 ORDER BY nav_change_pct DESC,p.portfolio_name
```

## 16. risk direction trap

For portfolios with risk data, compare 95% VaR on the first and last observation. Report the signed change and change in absolute magnitude, explaining clearly whether the historical risk estimate became more or less negative rather than calling a negative number's increase an unqualified improvement.

**Why tricky:** For negative VaR values, signed increase and absolute-risk magnitude move in opposite directions; improvement cannot be inferred without a convention.
**Tables:** portfolios, risk_metrics.
**Output shape:** First/last VaR/date, last-minus-first signed change, abs(last)-abs(first) magnitude change, and separate signed/magnitude direction labels.
**Required numerical/identity fields:** portfolio_name, first_date, last_date, first_var_95, last_var_95, signed_change, magnitude_change.
**Verified reference rows:** 4. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Negative stored VaR: positive signed change means less negative; negative signed change means more negative.
- Magnitude change=abs(last)-abs(first): positive is increased magnitude, negative is decreased magnitude; never call signed increase alone an improvement.
- All supplied VaR observations use the negative convention; preserve stored units and historical dates.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH o AS (SELECT portfolio_id,calculation_date,var_95,ROW_NUMBER() OVER(PARTITION BY portfolio_id ORDER BY calculation_date) AS a,ROW_NUMBER() OVER(PARTITION BY portfolio_id ORDER BY calculation_date DESC) AS z FROM risk_metrics), b AS (SELECT portfolio_id,MAX(CASE WHEN a=1 THEN calculation_date END) AS first_date,MAX(CASE WHEN z=1 THEN calculation_date END) AS last_date,MAX(CASE WHEN a=1 THEN var_95 END) AS first_var_95,MAX(CASE WHEN z=1 THEN var_95 END) AS last_var_95 FROM o GROUP BY portfolio_id) SELECT p.portfolio_name,b.first_date,b.last_date,b.first_var_95,b.last_var_95,b.last_var_95-b.first_var_95 AS signed_change,ABS(b.last_var_95)-ABS(b.first_var_95) AS magnitude_change,CASE WHEN b.last_var_95>b.first_var_95 THEN 'less negative' WHEN b.last_var_95<b.first_var_95 THEN 'more negative' ELSE 'unchanged' END AS signed_direction,CASE WHEN ABS(b.last_var_95)>ABS(b.first_var_95) THEN 'increased' WHEN ABS(b.last_var_95)<ABS(b.first_var_95) THEN 'decreased' ELSE 'unchanged' END AS magnitude_direction FROM b JOIN portfolios p USING(portfolio_id) ORDER BY p.portfolio_name
```

## 17. transaction cash movement

For each portfolio with transactions, calculate gross buys, gross sells, total transaction fees, and net cash movement (`SELL proceeds - BUY cost - all fees`). Show transaction counts and label the result as *observed transaction cash movement*, not realized investment P&L.

**Why tricky:** Fees apply to all transaction types; cash movement is not tax-lot or investment P&L.
**Tables:** portfolios, transactions.
**Output shape:** One portfolio row with buy/sell notional, all fees, signed net cash movement, total count and optional buy/sell counts.
**Required numerical/identity fields:** portfolio_name, buy_notional, sell_notional, total_fees, net_cash_movement, transaction_count.
**Verified reference rows:** 13. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Notional=quantity*transaction price; movement=sell_notional-buy_notional-all_fees over all supplied observed transactions.
- Include stocks and bonds; portfolio transaction counts do not come from holdings joins; no realized P&L claim.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
SELECT p.portfolio_name,SUM(CASE WHEN t.transaction_type='BUY' THEN t.quantity*t.price ELSE 0 END) AS buy_notional,SUM(CASE WHEN t.transaction_type='SELL' THEN t.quantity*t.price ELSE 0 END) AS sell_notional,SUM(t.fees) AS total_fees,SUM(CASE WHEN t.transaction_type='SELL' THEN t.quantity*t.price ELSE -t.quantity*t.price END)-SUM(t.fees) AS net_cash_movement,COUNT(*) AS transaction_count,SUM(CASE WHEN t.transaction_type='BUY' THEN 1 ELSE 0 END) AS buy_count,SUM(CASE WHEN t.transaction_type='SELL' THEN 1 ELSE 0 END) AS sell_count FROM transactions t JOIN portfolios p USING(portfolio_id) GROUP BY p.portfolio_id,p.portfolio_name ORDER BY p.portfolio_name
```

## 18. sells versus current holdings

List every SELL transaction with its security and portfolio, gross proceeds, fees, net proceeds, and current recorded holding quantity if present. Explain why the supplied data alone cannot reconstruct tax-lot realized gains reliably.

**Why tricky:** An inner holdings join can drop sells without a current holding; holdings cost basis cannot establish the sold tax lot.
**Tables:** transactions, portfolios, securities, holdings.
**Output shape:** Every SELL transaction, with transaction/security/portfolio identity, gross proceeds, fees, net proceeds and nullable current holding quantity.
**Required numerical/identity fields:** transaction_id, portfolio_name, symbol, gross_proceeds, fees, net_proceeds, current_holding_quantity.
**Verified reference rows:** 4. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Gross=transaction quantity*transaction price; net=gross-fee; left join holdings on portfolio AND security.
- Absent current holdings remain null, not invented zero; no reliable realized gain without sold-lot acquisition basis/lot matching history.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
SELECT t.transaction_id,p.portfolio_name,s.symbol,t.transaction_date,t.quantity,t.price,t.quantity*t.price AS gross_proceeds,t.fees,t.quantity*t.price-t.fees AS net_proceeds,h.quantity AS current_holding_quantity FROM transactions t JOIN portfolios p USING(portfolio_id) JOIN securities s USING(security_id) LEFT JOIN holdings h ON h.portfolio_id=t.portfolio_id AND h.security_id=t.security_id WHERE t.transaction_type='SELL' ORDER BY t.transaction_date,t.transaction_id
```

## 19. bond maturity and coupon comparison

Among portfolios with bond holdings, show each bond's recorded maturity date and coupon rate, quantity, observed holding market value, and share of that portfolio's bond market value. Do not calculate yield to maturity or annual coupon cash amounts without assumptions about face value/payment conventions.

**Why tricky:** The denominator is each portfolio's bonds only; quoted current price and coupon rate do not establish face value, YTM or payment schedules.
**Tables:** portfolios, holdings, securities.
**Output shape:** One portfolio/bond row with maturity/coupon/quantity, holding value, total bond value and bond_share_pct.
**Required numerical/identity fields:** portfolio_name, symbol, maturity_date, coupon_rate, quantity, bond_market_value, bond_share_pct.
**Verified reference rows:** 18. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Filter Bond before denominator aggregation; market value=recorded quantity*current_price.
- Coupon rate preserves its stored fractional units unless explicitly labeled as percent; no assumed face value, annual coupon amount or yield-to-maturity.
- A zero bond-value denominator produces unavailable share, never fabricated zero.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
WITH b AS (SELECT p.portfolio_id,p.portfolio_name,s.symbol,s.maturity_date,s.coupon_rate,h.quantity,h.quantity*s.current_price AS bond_market_value FROM holdings h JOIN portfolios p USING(portfolio_id) JOIN securities s USING(security_id) WHERE s.asset_type='Bond'), t AS (SELECT portfolio_id,SUM(bond_market_value) AS total_bond_market_value FROM b GROUP BY portfolio_id) SELECT b.portfolio_name,b.symbol,b.maturity_date,b.coupon_rate,b.quantity,b.bond_market_value,t.total_bond_market_value,100.0*b.bond_market_value/NULLIF(t.total_bond_market_value,0) AS bond_share_pct FROM b JOIN t USING(portfolio_id) ORDER BY b.portfolio_name,b.symbol
```

## 20. three-way portfolio diagnostic

Among portfolios with holdings, find those that (a) hold both stocks and bonds, (b) have more than two distinct equity sectors, and (c) have recorded total holding weights that differ from 100% by at least 0.5 percentage points. Return a fully justified empty result if none qualifies; do not loosen the conditions just to produce rows.

**Why tricky:** All three conditions must hold simultaneously; 0.5 percentage points is a fractional gap of 0.005, and the correct result may be empty.
**Tables:** portfolios, holdings, securities.
**Output shape:** Zero or more qualifying portfolio names; optional diagnostic stock/bond counts, stock-sector count, recorded total and signed gap. Empty is a genuine answer, not unsupported.
**Required numerical/identity fields:** portfolio_name.
**Verified reference rows:** 0. Agent status is initially `not_run`; consult the actual live report.

Assumptions:

- Both positive stock and bond holding counts, COUNT(DISTINCT stock sector_id)>2 and abs(recorded_total-1)>=0.005 are jointly required.
- No holdings means no candidate. Threshold comparison rounds fractional difference to 12 places only for binary boundary noise.
- A zero-row answer remains valid; record actual SQL/conditions for audit rather than loosening any threshold.

Reference SQL (also stored in the [machine-readable catalog](../tests/challenges/advanced_questions.json)):

```sql
SELECT p.portfolio_name,SUM(CASE WHEN s.asset_type='Stock' THEN 1 ELSE 0 END) AS stock_holding_count,SUM(CASE WHEN s.asset_type='Bond' THEN 1 ELSE 0 END) AS bond_holding_count,COUNT(DISTINCT CASE WHEN s.asset_type='Stock' THEN s.sector_id END) AS equity_sector_count,SUM(h.current_weight) AS recorded_weight_sum,100.0*(SUM(h.current_weight)-1.0) AS discrepancy_pp FROM portfolios p JOIN holdings h USING(portfolio_id) JOIN securities s USING(security_id) GROUP BY p.portfolio_id,p.portfolio_name HAVING SUM(CASE WHEN s.asset_type='Stock' THEN 1 ELSE 0 END)>0 AND SUM(CASE WHEN s.asset_type='Bond' THEN 1 ELSE 0 END)>0 AND COUNT(DISTINCT CASE WHEN s.asset_type='Stock' THEN s.sector_id END)>2 AND ABS(ROUND(SUM(h.current_weight)-1.0,12))>=0.005 ORDER BY p.portfolio_name
```

## Separate robustness checks

`tests/test_robustness_refinement.py` uses explicitly mocked planning to exercise nonexistent/ambiguous/misspelled names, future personal advice, missing performance, instruction injection, Groq outage/missing key, graph fallback, empty results and zero denominator. These are safety/integration mechanics, not live AI accuracy.

Q1 uses different stock-only denominators and an alphabetical winning-sector tie break. Q5 retains all thirteen portfolios while identifying the top five. Q11 preserves separately labeled best/worst membership even if sets overlap. Q12 starts its interval before the first decline and counts observations, not calendar days. Q14 aligns both ID and date. Q16 separates signed and absolute-magnitude changes of negative VaR. Q20 keeps all three predicates and its verified empty result.
