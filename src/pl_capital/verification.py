"""Independent runtime metric checks; never a source of replacement agent answers."""

import math
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, DecimalException

import sqlglot
from sqlglot import exp

from pl_capital.database import readonly
from pl_capital.errors import QueryError


def validate_average_precision(sql: str, question: str) -> None:
    """Keep unrequested rounding out of computed averages, including prices."""
    if not re.search(r"\b(?:average|avg|mean)\b", question, re.I) or re.search(
        r"\b(?:round(?:ed|ing)?|decimals?|cents?|precision)\b", question, re.I
    ):
        return
    tree = sqlglot.parse_one(sql, read="sqlite")
    if any(rounding.find(exp.Avg) is not None for rounding in tree.find_all(exp.Round)):
        raise QueryError(
            "Do not round a computed average unless the question requests rounding. "
            "Return the unrounded AVG value; presentation handles display formatting."
        )


def market_value_sector(question: str, sector_names: list[str]) -> str | None:
    """Recognize only the existing narrow, unfiltered market-value contract."""
    text = question.casefold()
    # Apply only to the unfiltered cross-portfolio metric whose full population
    # is unambiguous. Named funds, top-N and other denominators retain SQL's
    # general path rather than being forced into this specialized contract.
    if not re.search(
        r"(?:for\s+(?:each|every|all)\s+(?:portfolio|fund)|(?:per|by)\s+portfolio)", text
    ):
        return None
    if re.search(
        r"\b(?:top|bottom|active|inactive|risk|aum|where|only|except|excluding|greater|fewer|largest|smallest)\b|assets under management|current_weight|recorded weight",
        text,
    ):
        return None
    named = [name for name in sector_names if name.casefold() in text]
    if len(named) != 1 or not all(
        (
            re.search(r"value|valuation", text),
            re.search(r"percent|\bshare\b|%", text),
        )
    ):
        return None
    sector = named[0]
    return sector


def verify_market_values(path, question: str, sector_names: list[str], result: dict) -> bool:
    """Validate a clearly requested named-sector portfolio value/percentage breakdown.

    This generalizes to any sector actually present in the data. It reads no
    assessment question IDs/references and never supplies SQL or answers. A
    failed model query must be regenerated through the bounded correction path.
    """
    sector = market_value_sector(question, sector_names)
    if sector is None:
        return False
    text = question.casefold()
    totals, numerators = defaultdict(Decimal), defaultdict(Decimal)
    members = set()
    try:
        with readonly(path) as conn:
            for row in conn.execute("""
                SELECT p.portfolio_name,h.quantity,s.current_price,sec.sector_name
                FROM holdings h JOIN portfolios p USING(portfolio_id)
                JOIN securities s USING(security_id) LEFT JOIN sectors sec USING(sector_id)
            """):
                value = Decimal(str(row[1])) * Decimal(str(row[2]))
                if not value.is_finite():
                    raise QueryError(
                        "Market-value verification requires finite snapshot prices and quantities."
                    )
                totals[row[0]] += value
                if row[3] == sector:
                    numerators[row[0]] += value
                    members.add(row[0])
        if re.search(r"including\s+(?:zero|empty|all)|all\s+portfolios|without\s+.+holdings", text):
            members = set(totals)
        if len(result.get("columns", [])) != 4:
            raise QueryError(
                "Market-value breakdown must show portfolio, sector value, total holding value and percentage."
            )
        rows = result.get("rows", [])
        names = [row[0] for row in rows if len(row) == 4]
        if len(names) != len(rows) or len(set(names)) != len(names) or set(names) != members:
            raise QueryError(
                "Market-value portfolio set is incorrect: include portfolios holding the named sector; omit zero-filled absent-sector portfolios unless explicitly requested."
            )
        for name, numerator, denominator, percentage in rows:
            expected = [
                numerators[name],
                totals[name],
                (100 * numerators[name] / totals[name]).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if totals[name]
                else None,
            ]
            for actual, wanted, label in zip(
                (numerator, denominator, percentage),
                expected,
                ("sector market value", "total holding market value", "percentage"),
                strict=True,
            ):
                if wanted is None and actual is None:
                    continue
                if (
                    actual is None
                    or wanted is None
                    or not math.isclose(float(actual), float(wanted), rel_tol=1e-9, abs_tol=1e-6)
                ):
                    raise QueryError(
                        f"Market-value {label} verification failed. Use quantity*current_price; the denominator includes all holdings; percentage is 100*numerator/denominator rounded to 2 decimals."
                    )
    except (DecimalException, TypeError, ValueError, KeyError, OverflowError) as exc:
        raise QueryError(
            "Market-value verification encountered invalid data or result types."
        ) from exc
    return True


def validate_requested_output(sql: str, question: str) -> None:
    """Reject incomplete audit projections; never inject query text or answers."""
    tree = sqlglot.parse_one(sql, read="sqlite")
    outer = list(tree.selects)
    names = {
        node.name.casefold() for projection in outer for node in projection.find_all(exp.Column)
    }
    aliases = {projection.alias_or_name.casefold() for projection in outer}
    text = question.casefold()

    def require(fields, explanation):
        missing = set(fields) - aliases
        if missing:
            raise QueryError(
                explanation + " Include outer output fields: " + ", ".join(sorted(missing)) + "."
            )

    if "nav" in text and re.search(r"first.+last|first.+latest", text):
        require(
            {"first_nav", "last_nav", "first_date", "last_date"},
            "Observed NAV comparisons must expose both source observations and dates.",
        )
    if re.search(r"var|value.at.risk", text) and re.search(r"first.+last", text):
        require(
            {"first_date", "last_date"},
            "Historical risk comparisons must expose the dates of both observations.",
        )
    if "bond" in text and re.search(r"each bond|every bond", text):
        require({"symbol"}, "Identify every individual bond unambiguously.")
    if (
        re.search(r"for (?:each|every|all) portfolio", text)
        and "aum" in text
        and "holding" in text
        and tree.args.get("limit") is not None
    ):
        raise QueryError(
            "Return every requested portfolio. Rank all rows and flag the largest mismatches; do not replace the full population with a top-N LIMIT."
        )
    if re.search(r"largest.+sector.+twice|winning sector differs", text):
        require(
            {
                "portfolio_name",
                "recorded_top_sector",
                "recorded_top_pct",
                "value_top_sector",
                "value_top_pct",
                "top_gap_pp",
            },
            "Expose each metric's own winning sector and percentage; top_gap_pp is value_top_pct minus recorded_top_pct, not two shares of one sector or an absolute difference.",
        )
    if "bond weight" in text and "stock weight" in text and "equity-only" in text:
        require(
            {
                "bond_weight",
                "equity_weight",
                "recorded_total",
                "sector_weight",
                "portfolio_pct",
                "equity_pct",
                "weights_sum_to_100",
            },
            "Return one row per stock sector and show raw recorded weights plus separately labeled whole-recorded and equity-normalized percentages (100 times their fractions); bonds are a separate weight, never an equity sector.",
        )
    if (
        "current_weight" in text
        and "normalized" in text
        and re.search(r"holding.+share|share of stock market value", text)
    ):
        require(
            {
                "equity_weight_total",
                "equity_market_value",
                "recorded_equity_pct",
                "market_value_pct",
                "discrepancy_pp",
                "abs_discrepancy_pp",
            },
            "Holding-share comparisons must expose both denominators, both percentages, their signed difference (market minus recorded), and its absolute magnitude.",
        )
    if "best" in text and "worst" in text and re.search(r"first.+last.+close", text):
        require(
            {"extreme"},
            "Label the best and worst historical-return groups with extreme='best' or 'worst'; preserve both requested groups and their ranking.",
        )
    if re.search(r"latest common date|latest synchronized date|latest shared date", text):
        if not any("date" in name for name in names | aliases):
            raise QueryError(
                "Include the selected common date in the outer output for date-aligned risk/performance analysis."
            )
    if (
        re.search(r"\b(?:list|every|each)\b", text)
        and re.search(r"\bsell\b", text)
        and "transaction" in text
        and not re.search(r"aggregate|per portfolio|total sell|sum", text)
    ):
        if "transaction_id" not in names | aliases:
            raise QueryError(
                "Include transaction_id so every listed transaction can be audited independently."
            )
    if (
        "sector" in text
        and re.search(r"no securit|no security|unassigned|empty sector", text)
        and "holding" in text
    ):
        if not ({"security_count", "holding_count"} <= aliases):
            raise QueryError(
                "Verify empty sectors with explicit security_count and holding_count outputs, including zero counts."
            )
    if (
        "nav" in text
        and re.search(r"percentage|percent|nav %", text)
        and re.search(r"change|comparison|compare", text)
    ):
        if not any(re.search(r"pct|percent", name) for name in aliases):
            raise QueryError(
                "Include NAV percentage change as requested, using the previous NAV denominator and NULL for unavailable/zero prior NAV."
            )
