"""Recorded-weight equity exposure. No model arithmetic or synthetic missing weights."""

import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

from pl_capital.database import readonly
from pl_capital.errors import DataError, EntityError
from pl_capital.models import ExposureResult, SectorExposure


def resolve_portfolio(path: Path, name: str | int) -> tuple[int, str]:
    value = str(name).strip().casefold()
    if not value or len(value) > 200:
        raise EntityError("Supply a portfolio name or numeric ID.")
    with readonly(path) as conn:
        choices = [
            (r[0], r[1]) for r in conn.execute("SELECT portfolio_id,portfolio_name FROM portfolios")
        ]
    for ident, canonical in choices:
        if value == str(ident) or value == canonical.casefold():
            return ident, canonical

    def alias(text):
        return re.sub(r"\s+", " ", re.sub(r"\b(fund|portfolio)\b", "", text.casefold())).strip()

    matches = [(i, n) for i, n in choices if value == alias(n)]
    if not matches:
        matches = [(i, n) for i, n in choices if value in n.casefold()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise EntityError(
            "Ambiguous portfolio; specify one of: " + "; ".join(n for _, n in matches)
        )
    ranked = sorted(
        [(SequenceMatcher(None, value, alias(n)).ratio(), i, n) for i, n in choices], reverse=True
    )
    if ranked and ranked[0][0] >= 0.87 and (len(ranked) < 2 or ranked[0][0] - ranked[1][0] >= 0.1):
        return ranked[0][1], ranked[0][2]
    raise EntityError("Portfolio not found. Use its exact name or numeric ID.")


def calculate(path: Path, portfolio: str | int) -> ExposureResult:
    ident, name = resolve_portfolio(path, portfolio)
    with readonly(path) as conn:
        rows = conn.execute(
            """
            SELECT h.holding_id,h.security_id,h.current_weight,s.asset_type,sec.sector_name
            FROM holdings h JOIN securities s USING(security_id)
            LEFT JOIN sectors sec USING(sector_id) WHERE h.portfolio_id=:id
            ORDER BY h.holding_id
        """,
            {"id": ident},
        ).fetchall()
    sectors = defaultdict(Decimal)
    equity = bond = Decimal(0)
    equity_count = bond_count = 0
    seen = set()
    for row in rows:
        if row["security_id"] in seen:
            raise DataError("Duplicate holdings prevent a reliable exposure calculation.")
        seen.add(row["security_id"])
        try:
            weight = Decimal(str(row["current_weight"]))
        except InvalidOperation as exc:
            raise DataError("Holding weight is missing or invalid.") from exc
        if not weight.is_finite() or weight < 0 or weight > 1:
            raise DataError("Holding weight must be a finite fraction between 0 and 1.")
        if row["asset_type"] == "Stock":
            if not row["sector_name"]:
                raise DataError("Stock holding lacks a valid sector mapping.")
            sectors[row["sector_name"]] += weight
            equity += weight
            equity_count += 1
        elif row["asset_type"] == "Bond":
            bond += weight
            bond_count += 1
        else:
            raise DataError("Unknown asset classification.")
    total = equity + bond
    warnings = []
    if abs(total - 1) > Decimal("0.000001"):
        warnings.append(
            f"Recorded weights total {total * 100}% of the portfolio; missing weights are not filled."
        )
    if not equity:
        warnings.append(
            "No positive-weight equity holdings; bonds are excluded and normalization is unavailable."
        )

    def percent(value):
        try:
            return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
        except DecimalException as exc:
            raise DataError("Holding weights exceed the supported calculation precision.") from exc

    return ExposureResult(
        portfolio_id=ident,
        portfolio_name=name,
        status="ok" if equity else "no_equity_holdings",
        sectors=[
            SectorExposure(
                sector=sector,
                weight=str(weight),
                whole_portfolio_pct=percent(weight * 100),
                equity_normalized_pct=percent(weight / equity * 100),
            )
            for sector, weight in sorted(sectors.items())
        ]
        if equity
        else [],
        equity_weight_total=str(equity),
        bond_weight_total=str(bond),
        all_recorded_weights_total=str(total),
        equity_holding_count=equity_count,
        bond_exclusion_count=bond_count,
        warnings=warnings,
    )
