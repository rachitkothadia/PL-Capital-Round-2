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
        r"\b(?:for|of)\s+(?!all\b|each\b|every\b|stocks?\b|equities\b)(?:[A-Z][A-Z0-9.-]{1,9})\b",
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


def verify_advanced_metrics(path, question: str, result: dict) -> list[str]:
    """Return names of performed checks; mismatches raise actionable QueryError."""
    text = " ".join(question.casefold().split())[:4000]
    winners, threshold = _winner_question(text), _streak_threshold(text)
    if not winners and threshold is None:
        return []
    with readonly(path) as conn:
        if _named_scope(conn, question):
            return []
        if winners:
            _verify_winners(conn, result)
        if threshold is not None:
            _verify_streaks(conn, threshold, result)
    return (["stock_sector_winners"] if winners else []) + (
        ["observed_close_decline_streaks"] if threshold is not None else []
    )
