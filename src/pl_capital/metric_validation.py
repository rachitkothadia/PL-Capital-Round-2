"""Independent checks for narrowly recognized metrics; never replacement answers."""

import re
from collections import defaultdict
from decimal import Decimal, DecimalException

from pl_capital.database import readonly
from pl_capital.errors import QueryError

MAX_SOURCE_ROWS = 20_000
PERCENT_TOLERANCE = Decimal("0.000001")  # Computed metrics preserve full precision.
NUMBER_WORDS = dict(
    zip("one two three four five six seven eight nine ten".split(), range(1, 11), strict=True)
)
WINNER_RULE = (
    "Verify all portfolios whose largest stock-sector winners differ. Aggregate current_weight "
    "and quantity*current_price separately by portfolio and stock sector; divide each by its own "
    "total across stocks, rank each metric independently (sector name ascending breaks ties), "
    "and use top_gap_pp=value_top_pct-recorded_top_pct, preserving its sign."
)
STREAK_RULE = (
    "Verify all qualifying stock symbols using adjacent observed closing-price records ordered "
    "by price_date. A strict decrease adds one transition; equality or an increase resets the run. "
    "The start is the observation immediately before the first decrease, the end is the last "
    "decreasing observation; select the longest run and earliest start when tied. Do not require "
    "calendar-day continuity. Apply the requested minimum decline count."
)
AUM_RULE = (
    "Verify every portfolio against raw total_aum and the sum of quantity*current_price across all "
    "listed holdings. aum_minus_holdings is reported AUM minus holdings market value; ratio is "
    "holdings market value/AUM and coverage percentage is 100*ratio (NULL when AUM is zero). "
    "Rank absolute dollar mismatches descending, with portfolio name ascending on ties; retain all portfolios."
)
SHARE_RULE = (
    "For every stock holding, compute its market value as quantity*current_price. equity_market_value "
    "must be the TOTAL stock market value of its portfolio, not the individual holding value; "
    "equity_weight_total is the sum of current_weight over stocks in that same portfolio. "
    "market_value_pct=100*holding_value/equity_market_value; recorded_equity_pct=100*current_weight/"
    "equity_weight_total; discrepancy_pp=market_value_pct-recorded_equity_pct and abs_discrepancy_pp "
    "is its absolute value. Return the requested largest absolute discrepancies, sorting ties by "
    "portfolio name then symbol. Exclude undefined discrepancies when either stock denominator "
    "is zero rather than filling them with zero. Preserve full numeric precision."
)


def _number(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("non-finite")
        return result
    except (DecimalException, ValueError, TypeError) as exc:
        raise QueryError(
            "Metric verification requires finite numeric source and result values."
        ) from exc


def _read(conn, sql):
    rows = conn.execute(sql).fetchmany(MAX_SOURCE_ROWS + 1)
    if len(rows) > MAX_SOURCE_ROWS:
        raise QueryError("Metric verification source exceeds the bounded local observation budget.")
    return rows


def _records(result, required, aliases=None):
    columns = [
        re.sub(r"[^a-z0-9]+", "_", str(c).casefold()).strip("_") for c in result.get("columns", [])
    ]
    aliases = aliases or {}
    columns = [aliases.get(c, c) for c in columns]
    if len(set(columns)) != len(columns) or not set(required) <= set(columns):
        raise QueryError(
            "Metric verification requires unambiguous output columns: " + ", ".join(required) + "."
        )
    if result.get("truncated") or len(result.get("rows", [])) > MAX_SOURCE_ROWS:
        raise QueryError("Metric verification requires the complete qualifying result population.")
    records = []
    for row in result.get("rows", []):
        if len(row) != len(columns):
            raise QueryError("Metric verification encountered an inconsistent result row shape.")
        records.append(dict(zip(columns, row, strict=True)))
    return records


def _named_scope(conn, question):
    """Conservatively leave named/filter-specific analysis on the general SQL path."""
    text = question.casefold()
    if re.search(
        r"\b(?:for|of)\s+(?!all\b|each\b|every\b|stocks?\b|equities\b|AUM\b|NAV\b|SQL\b)(?:[A-Z][A-Z0-9.-]{1,9})\b",
        question,
    ):
        return True
    if re.search(r"\b[A-Z][A-Z0-9.-]{1,9}\s+stocks?\b", question):
        return True
    for row in _read(
        conn, "SELECT portfolio_name FROM portfolios UNION SELECT sector_name FROM sectors"
    ):
        if re.search(r"(?<!\w)" + re.escape(row[0].casefold()) + r"(?!\w)", text):
            return True
    for symbol, company in _read(conn, "SELECT symbol,company_name FROM securities"):
        # Short uppercase symbols can be ordinary English words when lowercased.
        haystack = question if len(symbol) <= 2 else text
        needle = symbol if len(symbol) <= 2 else symbol.casefold()
        if re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack):
            return True
        # Common company suffixes are not required to identify a named security.
        company = re.sub(
            r"\s+(?:inc\.?|corp\.?|corporation|company|ltd\.?)$", "", company, flags=re.I
        )
        if len(company) >= 3 and re.search(
            r"(?<!\w)" + re.escape(company.casefold()) + r"(?!\w)", text
        ):
            return True
    return False


def _winner_question(text):
    return (
        bool(
            re.search(
                r"largest\b.+\bsector\b.+\btwice\b|winning sectors? (?:differ|differs)\b|winners? (?:differ|differs)\b",
                text,
            )
        )
        and bool(re.search(r"\b(?:stocks?|equity|equities)\b", text))
        and bool(re.search(r"recorded|current_weight", text))
        and bool(re.search(r"market.?value|quantity.{0,30}(?:price|current_price)", text))
        and not re.search(
            r"\b(?:active|inactive|top\s+\d+|bottom\s+\d+|excluding|except|since|before|after)\b",
            text,
        )
    )


def _verify_winners(conn, result):
    weights, values = (
        defaultdict(lambda: defaultdict(Decimal)),
        defaultdict(lambda: defaultdict(Decimal)),
    )
    for portfolio, sector, weight, quantity, price in _read(
        conn,
        """
        SELECT p.portfolio_name,sec.sector_name,h.current_weight,h.quantity,s.current_price
        FROM holdings h JOIN portfolios p USING(portfolio_id)
        JOIN securities s USING(security_id) LEFT JOIN sectors sec USING(sector_id)
        WHERE s.asset_type='Stock'
    """,
    ):
        if sector is None:
            raise QueryError(
                "Stock-sector winner verification requires a known sector for each stock. "
                + WINNER_RULE
            )
        weight, quantity, price = _number(weight), _number(quantity), _number(price)
        if min(weight, quantity, price) < 0:
            raise QueryError(
                "Stock-sector winner verification requires nonnegative weights, quantities and prices."
            )
        weights[portfolio][sector] += weight
        values[portfolio][sector] += quantity * price
    expected = {}
    for portfolio in weights:
        weight_total, value_total = (
            sum(weights[portfolio].values()),
            sum(values[portfolio].values()),
        )
        if weight_total <= 0 or value_total <= 0:
            continue
        recorded_sector = min(weights[portfolio], key=lambda s: (-weights[portfolio][s], s))
        value_sector = min(values[portfolio], key=lambda s: (-values[portfolio][s], s))
        if recorded_sector != value_sector:
            recorded_pct = 100 * weights[portfolio][recorded_sector] / weight_total
            value_pct = 100 * values[portfolio][value_sector] / value_total
            expected[portfolio] = (
                recorded_sector,
                recorded_pct,
                value_sector,
                value_pct,
                value_pct - recorded_pct,
            )
    fields = (
        "portfolio_name",
        "recorded_top_sector",
        "recorded_top_pct",
        "value_top_sector",
        "value_top_pct",
        "top_gap_pp",
    )
    rows = _records(result, fields)
    names = [r["portfolio_name"] for r in rows]
    if len(set(names)) != len(names) or set(names) != set(expected):
        raise QueryError(
            "Stock-sector winner population is incomplete, duplicated or contains nonqualifying portfolios. "
            + WINNER_RULE
        )
    for row in rows:
        wanted = expected[row["portfolio_name"]]
        if row["recorded_top_sector"] != wanted[0] or row["value_top_sector"] != wanted[2]:
            raise QueryError("Stock-sector winner selection is incorrect. " + WINNER_RULE)
        for field, target in zip(
            ("recorded_top_pct", "value_top_pct", "top_gap_pp"),
            (wanted[1], wanted[3], wanted[4]),
            strict=True,
        ):
            if abs(_number(row[field]) - target) > PERCENT_TOLERANCE:
                raise QueryError(
                    "Stock-sector winning percentage or signed top_gap_pp is incorrect. "
                    + WINNER_RULE
                )


def _streak_threshold(text):
    if not re.search(r"\bstocks?\b|\bequit(?:y|ies)\b", text) or not re.search(
        r"clos(?:e|es|ing)", text
    ):
        return None
    # Filters and calendar windows require their own explicitly resolved contract.
    if re.search(
        r"\b(?:only|excluding|except|sector|portfolio|fund|between|since|after|before|until|active|inactive|top|bottom)\b|\b\d{4}-\d{2}-\d{2}\b",
        text,
    ):
        return None
    match = re.search(
        r"\bat least\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+consecutive\s+(?:(?:observed|close-to-close|closing-to-closing|closing[- ]price|price|close|closing)\s+){0,3}(?:declines?|decreases?|falls?|drops?)\b",
        text,
    )
    if not match:
        return None
    token = match[1]
    count = int(token) if token.isdigit() else NUMBER_WORDS[token]
    return count if 1 <= count <= MAX_SOURCE_ROWS else None


def _verify_streaks(conn, threshold, result):
    observed = defaultdict(list)
    for symbol, date, close in _read(
        conn,
        """
        SELECT s.symbol,h.price_date,h.close_price FROM historical_prices h
        JOIN securities s USING(security_id) WHERE s.asset_type='Stock'
        ORDER BY s.symbol,h.price_date
    """,
    ):
        observed[symbol].append((date, _number(close)))
    expected = {}
    for symbol, prices in observed.items():
        length, start, best = 0, None, None
        for previous, current in zip(prices, prices[1:], strict=False):
            if current[1] < previous[1]:
                if length == 0:
                    start = previous[0]
                length += 1
                candidate = (length, start, current[0])
                if best is None or length > best[0] or (length == best[0] and start < best[1]):
                    best = candidate
            else:
                length, start = 0, None
        if best and best[0] >= threshold:
            expected[symbol] = best
    aliases = {
        "stock_symbol": "symbol",
        "security_symbol": "symbol",
        "max_decline_streak": "longest_decline_streak",
        "max_streak": "longest_decline_streak",
        "longest_streak": "longest_decline_streak",
        "streak_length": "longest_decline_streak",
        "longest_streak_length": "longest_decline_streak",
        "decline_streak": "longest_decline_streak",
        "streak_start": "start_date",
        "streak_start_date": "start_date",
        "start_price_date": "start_date",
        "interval_start": "start_date",
        "streak_end": "end_date",
        "streak_end_date": "end_date",
        "end_price_date": "end_date",
        "interval_end": "end_date",
    }
    rows = _records(result, ("symbol", "longest_decline_streak", "start_date", "end_date"), aliases)
    symbols = [r["symbol"] for r in rows]
    if len(set(symbols)) != len(symbols) or set(symbols) != set(expected):
        raise QueryError(
            "Observed decline-streak stock population is incomplete, duplicated or nonqualifying. "
            + STREAK_RULE
        )
    for row in rows:
        wanted = expected[row["symbol"]]
        if (_number(row["longest_decline_streak"]), row["start_date"], row["end_date"]) != wanted:
            raise QueryError(
                "Observed decline-streak length or boundary dates are incorrect. " + STREAK_RULE
            )


def _top_count(text, noun):
    count_pattern = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    match = re.search(r"\b" + count_pattern + r"\s+largest\s+(?:absolute\s+)?" + noun, text)
    if not match:
        match = re.search(r"\btop\s+" + count_pattern + r"\s+(?:absolute\s+)?" + noun, text)
    if not match:
        return None
    value = int(match[1]) if match[1].isdigit() else NUMBER_WORDS[match[1]]
    return value if 1 <= value <= MAX_SOURCE_ROWS else None


def _unfiltered(text):
    return not re.search(
        r"\b(?:active|inactive|excluding|except|only|since|before|after|between|where)\b|\b\d{4}-\d{2}-\d{2}\b",
        text,
    )


def _aum_question(text):
    return bool(
        _unfiltered(text)
        and re.search(r"\b(?:each|every|all)\s+(?:portfolio|portfolios|fund|funds)\b", text)
        and re.search(r"\baum\b|total_aum|assets under management", text)
        and "holding" in text
        and re.search(r"ratio|percent|coverage", text)
        and re.search(r"difference|mismatch|gap", text)
    )


def _share_count(text):
    if not (
        _unfiltered(text)
        and "holding" in text
        and "share" in text
        and "current_weight" in text
        and "normalized" in text
        and re.search(r"stock market value|equity market value", text)
        and re.search(r"discrepanc", text)
    ):
        return None
    return _top_count(text, r"(?:percentage[- ]point\s+)?discrepanc(?:y|ies)")


def _check_number(actual, expected, rule):
    if (expected is None and actual is not None) or (expected is not None and actual is None):
        raise QueryError("Metric denominator or unavailable value is incorrect. " + rule)
    if expected is not None and abs(_number(actual) - expected) > PERCENT_TOLERANCE:
        raise QueryError("Computed metric value or denominator is incorrect. " + rule)


def _verify_aum(conn, question, result):
    aum = {
        name: _number(value)
        for name, value in _read(conn, "SELECT portfolio_name,total_aum FROM portfolios")
    }
    totals = defaultdict(Decimal)
    for name, quantity, price in _read(
        conn,
        """
        SELECT p.portfolio_name,h.quantity,s.current_price FROM holdings h
        JOIN portfolios p USING(portfolio_id) JOIN securities s USING(security_id)
    """,
    ):
        totals[name] += _number(quantity) * _number(price)
    if any(value < 0 for value in aum.values()):
        raise QueryError("AUM comparison requires nonnegative reported AUM. " + AUM_RULE)
    order = sorted(aum, key=lambda name: (-abs(aum[name] - totals[name]), name))
    ranks = {name: i + 1 for i, name in enumerate(order)}
    aliases = {
        "aum": "reported_aum",
        "total_aum": "reported_aum",
        "holdings_value": "holdings_market_value",
        "total_holdings_value": "holdings_market_value",
        "ratio": "holdings_to_aum_ratio",
        "holdings_aum_ratio": "holdings_to_aum_ratio",
        "aum_percentage_represented": "coverage_pct",
        "holdings_pct_of_aum": "coverage_pct",
        "holdings_to_aum_pct": "coverage_pct",
        "coverage_percentage": "coverage_pct",
        "difference": "aum_minus_holdings",
        "dollar_difference": "aum_minus_holdings",
        "gap": "aum_minus_holdings",
        "rank": "mismatch_rank",
        "gap_rank": "mismatch_rank",
    }
    rows = _records(
        result,
        (
            "portfolio_name",
            "reported_aum",
            "holdings_market_value",
            "holdings_to_aum_ratio",
            "coverage_pct",
        ),
        aliases,
    )
    names = [row["portfolio_name"] for row in rows]
    if len(set(names)) != len(names) or set(names) != set(aum):
        raise QueryError("AUM comparison must include every portfolio exactly once. " + AUM_RULE)
    if rows and "mismatch_rank" in rows[0] and names != order:
        raise QueryError(
            "AUM mismatch rows must follow descending absolute mismatch rank. " + AUM_RULE
        )
    for row in rows:
        name = row["portfolio_name"]
        ratio = totals[name] / aum[name] if aum[name] else None
        for field, expected in (
            ("reported_aum", aum[name]),
            ("holdings_market_value", totals[name]),
            ("holdings_to_aum_ratio", ratio),
            ("coverage_pct", 100 * ratio if ratio is not None else None),
        ):
            _check_number(row[field], expected, AUM_RULE)
        if not {"aum_minus_holdings", "holdings_minus_aum"}.intersection(row):
            raise QueryError(
                "AUM comparison requires an explicitly signed dollar difference. " + AUM_RULE
            )
        for field, sign in (("aum_minus_holdings", 1), ("holdings_minus_aum", -1)):
            if field in row:
                _check_number(row[field], sign * (aum[name] - totals[name]), AUM_RULE)
        if "mismatch_rank" in row:
            _check_number(row["mismatch_rank"], Decimal(ranks[name]), AUM_RULE)
        for field, actual in row.items():
            if not field.startswith("is_top_"):
                continue
            token = field.removeprefix("is_top_")
            count = int(token) if token.isdigit() else NUMBER_WORDS.get(token)
            if count is None:
                count = _top_count(question, r"mismatches?")
            if count is not None and (
                actual not in (0, 1, False, True) or bool(actual) != (ranks[name] <= count)
            ):
                raise QueryError("Largest-mismatch flag is incorrect. " + AUM_RULE)


def _verify_shares(conn, count, result):
    holdings, values, weights = [], defaultdict(Decimal), defaultdict(Decimal)
    for name, symbol, company, weight, quantity, price in _read(
        conn,
        """
        SELECT p.portfolio_name,s.symbol,s.company_name,h.current_weight,h.quantity,s.current_price
        FROM holdings h JOIN portfolios p USING(portfolio_id) JOIN securities s USING(security_id)
        WHERE s.asset_type='Stock'
    """,
    ):
        weight, value = _number(weight), _number(quantity) * _number(price)
        if weight < 0 or value < 0:
            raise QueryError(
                "Stock-share comparison requires nonnegative weights and market values. "
                + SHARE_RULE
            )
        values[name] += value
        weights[name] += weight
        holdings.append((name, symbol, company, weight, value))
    expected = []
    for name, symbol, company, weight, value in holdings:
        if values[name] <= 0 or weights[name] <= 0:
            continue  # No defined discrepancy exists for a zero stock denominator.
        market_pct, recorded_pct = 100 * value / values[name], 100 * weight / weights[name]
        gap = market_pct - recorded_pct
        expected.append(
            dict(
                portfolio_name=name,
                symbol=symbol,
                company_name=company,
                equity_market_value=values[name],
                equity_weight_total=weights[name],
                market_value_pct=market_pct,
                recorded_equity_pct=recorded_pct,
                discrepancy_pp=gap,
                abs_discrepancy_pp=abs(gap),
                holding_market_value=value,
                current_weight=weight,
            )
        )
    expected.sort(
        key=lambda row: (-row["abs_discrepancy_pp"], row["portfolio_name"], row["symbol"])
    )
    expected = expected[:count]
    aliases = {
        "stock_symbol": "symbol",
        "security_name": "company_name",
        "holding_value": "holding_market_value",
        "market_value": "holding_market_value",
        "recorded_weight": "current_weight",
        "equity_weight": "current_weight",
    }
    fields = (
        "portfolio_name",
        "symbol",
        "company_name",
        "equity_market_value",
        "equity_weight_total",
        "market_value_pct",
        "recorded_equity_pct",
        "discrepancy_pp",
        "abs_discrepancy_pp",
    )
    rows = _records(result, fields, aliases)
    identities = [(row["portfolio_name"], row["symbol"]) for row in rows]
    if identities != [(row["portfolio_name"], row["symbol"]) for row in expected]:
        raise QueryError(
            "Stock-share top-N population or deterministic ranking is incorrect. " + SHARE_RULE
        )
    for actual, wanted in zip(rows, expected, strict=True):
        if actual["company_name"] != wanted["company_name"]:
            raise QueryError(
                "Stock-share security name does not match the source holding. " + SHARE_RULE
            )
        for field in (*fields[3:], "holding_market_value", "current_weight"):
            if field in actual:
                _check_number(actual[field], wanted[field], SHARE_RULE)


def verify_advanced_metrics(path, question: str, result: dict) -> list[str]:
    """Return names of performed checks; mismatches raise actionable QueryError."""
    text = " ".join(question.casefold().split())[:4000]
    winners, threshold = _winner_question(text), _streak_threshold(text)
    aum, share_count = _aum_question(text), _share_count(text)
    if not winners and threshold is None and not aum and share_count is None:
        return []
    with readonly(path) as conn:
        if _named_scope(conn, question):
            return []
        if winners:
            _verify_winners(conn, result)
        if threshold is not None:
            _verify_streaks(conn, threshold, result)
        if aum:
            _verify_aum(conn, text, result)
        if share_count is not None:
            _verify_shares(conn, share_count, result)
    return (
        (["stock_sector_winners"] if winners else [])
        + (["observed_close_decline_streaks"] if threshold is not None else [])
        + (["aum_holdings_comparison"] if aum else [])
        + (["equity_holding_share_discrepancies"] if share_count is not None else [])
    )
