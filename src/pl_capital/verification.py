"""Independent runtime metric checks; never a source of replacement agent answers."""

import math
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, DecimalException

from pl_capital.database import readonly
from pl_capital.errors import QueryError


def verify_market_values(path, question: str, sector_names: list[str], result: dict) -> bool:
    """Validate a clearly requested named-sector portfolio value/percentage breakdown.

    This generalizes to any sector actually present in the data. It reads no
    assessment question IDs/references and never supplies SQL or answers. A
    failed model query must be regenerated through the bounded correction path.
    """
    text = question.casefold()
    # Apply only to the unfiltered cross-portfolio metric whose full population
    # is unambiguous. Named funds, top-N and other denominators retain SQL's
    # general path rather than being forced into this specialized contract.
    if not re.search(
        r"(?:for\s+(?:each|every|all)\s+(?:portfolio|fund)|(?:per|by)\s+portfolio)", text
    ):
        return False
    if re.search(
        r"\b(?:top|bottom|active|inactive|risk|aum|where|only|except|excluding|greater|fewer|largest|smallest)\b|assets under management|current_weight|recorded weight",
        text,
    ):
        return False
    named = [name for name in sector_names if name.casefold() in text]
    if len(named) != 1 or not all(
        (
            re.search(r"value|valuation", text),
            re.search(r"percent|\bshare\b|%", text),
        )
    ):
        return False
    sector = named[0]
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
