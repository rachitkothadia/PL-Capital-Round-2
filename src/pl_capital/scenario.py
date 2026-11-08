"""Deterministic hypothetical market shocks; supplied SQLite prices remain authoritative."""

import re
import sqlite3
from collections import defaultdict
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    localcontext,
)
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pl_capital.database import readonly
from pl_capital.errors import DataError, EntityError

MAIN_SCENARIO_QUESTION = (
    "Run a hypothetical market stress test across all 13 portfolios using the supplied holdings "
    "and current security prices. Assume Technology stocks fall 22%, Energy stocks rise 11%, "
    "Financials stocks fall 7%, all other equities remain unchanged, and bonds remain unchanged. "
    "For each portfolio, calculate its pre-shock and post-shock market value, total dollar P&L, "
    "portfolio percentage return, equity-only percentage return, post-shock equity-normalized "
    "sector exposures, and the sector contributing most negatively to P&L. Rank portfolios from "
    "largest percentage loss to largest gain. Show the formulas and explain why reported AUM "
    "must not be used as the denominator. Clearly label this a hypothetical scenario, not a forecast."
)

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


def _shock(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Shocks must be finite fractional numbers, for example -0.22 for -22%.")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(
            "Shocks must be finite fractional numbers, not percentages or expressions."
        ) from exc
    if not number.is_finite() or not -ONE <= number <= Decimal(10):
        raise ValueError("A price shock must be between -1 (-100%) and 10 (+1000%).")
    if number.as_tuple().exponent < -18:
        raise ValueError("A fractional shock supports at most 18 decimal places.")
    return number


class ScenarioRequest(BaseModel):
    """Fractions only: callers convert natural-language percentage inputs exactly once."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    sector_shocks: dict[str, Decimal] = Field(default_factory=dict)
    unmentioned_equity_shock: Decimal = ZERO
    bond_shock: Decimal = ZERO
    portfolio_filter: list[str] | None = None
    scenario_label: str = Field(default="Hypothetical market shock", min_length=1, max_length=200)

    @field_validator("sector_shocks", mode="before")
    @classmethod
    def validate_sectors(cls, value):
        if not isinstance(value, dict) or len(value) > 100:
            raise ValueError("Supply at most 100 sector names mapped to fractional shocks.")
        result = {}
        for name, shock in value.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise ValueError("Sector names must be nonempty strings of at most 100 characters.")
            if name.strip() in result:
                raise ValueError("Each sector must have exactly one shock.")
            result[name.strip()] = _shock(shock)
        return result

    @field_validator("unmentioned_equity_shock", "bond_shock", mode="before")
    @classmethod
    def validate_shock(cls, value):
        return _shock(value)

    @field_validator("portfolio_filter", mode="before")
    @classmethod
    def validate_filter(cls, value):
        if value is None:
            return None
        if not isinstance(value, list) or not 1 <= len(value) <= 100:
            raise ValueError(
                "Supply a nonempty list of at most 100 portfolio names or IDs, or null for all."
            )
        if any(not isinstance(name, str) or not name.strip() or len(name) > 200 for name in value):
            raise ValueError(
                "Portfolio filters must contain nonempty names or numeric IDs as strings."
            )
        return [name.strip() for name in value]

    @field_validator("scenario_label")
    @classmethod
    def validate_label(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Use a nonempty scenario label without control characters.")
        return value.strip()


def _number(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise DataError(
            f"A holding has a missing or invalid {field}; repair the supplied snapshot."
        ) from exc
    if not number.is_finite() or number < ZERO:
        raise DataError(
            f"A holding has a nonfinite or negative {field}; repair the supplied snapshot."
        )
    if (
        len(number.as_tuple().digits) > 30
        or number.as_tuple().exponent < -18
        or number.adjusted() > 24
    ):
        raise DataError(
            f"A holding's {field} exceeds the supported decimal precision or magnitude."
        )
    return number


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == ZERO:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= ZERO:
        return None
    # Money is exact; nonterminating ratios have a documented 128-significant-digit context.
    with localcontext() as context:
        context.traps[Inexact] = False
        return HUNDRED * numerator / denominator


def _json_safe(value):
    if isinstance(value, Decimal):
        return _text(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def calculate_scenario(db_path: Path, request: ScenarioRequest) -> dict:
    """Apply validated price shocks without models, mutable SQL, AUM denominators or network calls."""
    # Revalidate mutable nested dictionaries as well as assignment-validated fields.
    request = ScenarioRequest.model_validate(request.model_dump())
    try:
        with localcontext(Context(prec=128, rounding=ROUND_HALF_EVEN)) as context:
            context.traps[Inexact] = True
            return _calculate(Path(db_path), request)
    except (sqlite3.Error, OSError) as exc:
        raise DataError(
            "Cannot read the supplied scenario snapshot; check or rebuild the local database."
        ) from exc
    except DecimalException as exc:
        raise DataError(
            "Snapshot values exceed reliable scenario calculation precision; check the data."
        ) from exc


def _calculate(path: Path, request: ScenarioRequest) -> dict:
    with readonly(path) as conn:
        portfolios = conn.execute(
            "SELECT portfolio_id,portfolio_name,total_aum FROM portfolios ORDER BY portfolio_id"
        ).fetchall()
        sector_rows = conn.execute(
            "SELECT sector_id,sector_name FROM sectors ORDER BY sector_id"
        ).fetchall()
    canonical = {}
    for row in sector_rows:
        name = row["sector_name"]
        if not isinstance(name, str) or not name.strip() or name.casefold() in canonical:
            raise DataError("The supplied sector catalog has missing or ambiguous names.")
        canonical[name.casefold()] = name
    shocks = {}
    for name, shock in request.sector_shocks.items():
        sector = canonical.get(name.casefold())
        if sector is None:
            raise EntityError(f"Unknown sector '{name}'. Use a sector from the supplied dataset.")
        if sector in shocks:
            raise EntityError(f"Sector '{sector}' was supplied more than once; specify one shock.")
        shocks[sector] = shock
    if request.portfolio_filter is not None:
        # Exposure's result models import the shared Plan, which imports ScenarioRequest.
        from pl_capital.exposure import resolve_portfolio

        selected = {resolve_portfolio(path, name)[0] for name in request.portfolio_filter}
        portfolios = [p for p in portfolios if p["portfolio_id"] in selected]
    selected = {p["portfolio_id"] for p in portfolios}
    # Fixed, trusted read-only SQL; user parameters never become SQL syntax.
    with readonly(path) as conn:
        holdings = conn.execute("""SELECT h.holding_id,h.portfolio_id,h.security_id,h.quantity,h.purchase_date,
            s.symbol,s.asset_type,s.current_price,s.currency,s.sector_id,c.sector_name
            FROM holdings h LEFT JOIN securities s ON s.security_id=h.security_id
            LEFT JOIN sectors c ON c.sector_id=s.sector_id ORDER BY h.holding_id""").fetchall()
    items = defaultdict(list)
    currencies = set()
    warnings = []
    seen = set()
    dates = set()
    all_portfolios = {p["portfolio_id"] for p in portfolios}
    for row in holdings:
        if row["portfolio_id"] not in selected:
            if request.portfolio_filter is None and row["portfolio_id"] not in all_portfolios:
                raise DataError(
                    "A holding references an unknown portfolio; repair the supplied snapshot."
                )
            continue
        key = (row["portfolio_id"], row["security_id"])
        if key in seen:
            raise DataError(
                "Duplicate portfolio/security holdings prevent reliable scenario calculations."
            )
        seen.add(key)
        quantity = _number(row["quantity"], "quantity")
        price = _number(row["current_price"], "current price")
        currency = row["currency"]
        if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise DataError(
                "A holding lacks a valid three-letter currency; no currency is assumed."
            )
        currencies.add(currency)
        asset_type = row["asset_type"]
        sector = row["sector_name"]
        if asset_type == "Stock":
            if not sector or canonical.get(sector.casefold()) != sector:
                raise DataError(
                    "A stock holding lacks a valid sector mapping; repair the supplied snapshot."
                )
            shock = shocks.get(sector, request.unmentioned_equity_shock)
        elif asset_type == "Bond":
            shock = request.bond_shock
        else:
            raise DataError("A holding lacks a supplied Stock/Bond asset classification.")
        before = quantity * price
        after = before * (ONE + shock)
        items[row["portfolio_id"]].append(
            {
                "holding_id": row["holding_id"],
                "security_id": row["security_id"],
                "symbol": row["symbol"],
                "asset_type": asset_type,
                "sector": sector,
                "currency": currency,
                "quantity": quantity,
                "current_price": price,
                "shock": shock,
                "pre_value": before,
                "post_value": after,
                "pnl": after - before,
                "purchase_date": row["purchase_date"],
            }
        )
        if row["purchase_date"]:
            dates.add(row["purchase_date"])
        if quantity == ZERO or price == ZERO:
            warnings.append(
                f"Holding {row['holding_id']} has zero quantity or price and contributes zero market value."
            )
    if len(currencies) > 1:
        raise DataError(
            "Selected holdings contain multiple currencies; a supplied FX conversion snapshot is required."
        )
    currency = next(iter(currencies), None)
    results = []
    for portfolio in portfolios:
        audit = items[portfolio["portfolio_id"]]
        equity = [holding for holding in audit if holding["asset_type"] == "Stock"]
        before = sum((h["pre_value"] for h in audit), ZERO)
        after = sum((h["post_value"] for h in audit), ZERO)
        eq_before = sum((h["pre_value"] for h in equity), ZERO)
        eq_after = sum((h["post_value"] for h in equity), ZERO)
        sector_audit = []
        for sector in sorted({h["sector"] for h in equity}):
            matched = [h for h in equity if h["sector"] == sector]
            sector_before = sum((h["pre_value"] for h in matched), ZERO)
            sector_after = sum((h["post_value"] for h in matched), ZERO)
            sector_audit.append(
                {
                    "sector": sector,
                    "shock": shocks.get(sector, request.unmentioned_equity_shock),
                    "holding_count": len(matched),
                    "pre_sector_equity_value": sector_before,
                    "post_sector_equity_value": sector_after,
                    "sector_pnl": sector_after - sector_before,
                    "post_equity_normalized_sector_exposure_pct": _percent(sector_after, eq_after),
                    "post_whole_portfolio_sector_exposure_pct": _percent(sector_after, after),
                }
            )
        losers = [s for s in sector_audit if s["sector_pnl"] < ZERO]
        worst = min(losers, key=lambda s: (s["sector_pnl"], s["sector"])) if losers else None
        results.append(
            {
                "portfolio_id": portfolio["portfolio_id"],
                "portfolio_name": portfolio["portfolio_name"],
                "currency": currency if audit else None,
                "pre_portfolio_value": before,
                "post_portfolio_value": after,
                "portfolio_pnl": after - before,
                "portfolio_return_pct": _percent(after - before, before),
                "pre_equity_value": eq_before,
                "post_equity_value": eq_after,
                "equity_pnl": eq_after - eq_before,
                "equity_return_pct": _percent(eq_after - eq_before, eq_before),
                "top_loss_sector": worst["sector"] if worst else None,
                "top_loss_sector_pnl": worst["sector_pnl"] if worst else None,
                "reported_total_aum": None
                if portfolio["total_aum"] is None
                else _number(portfolio["total_aum"], "reported AUM"),
                "sectors": sector_audit,
                "holdings": audit,
            }
        )
    results.sort(
        key=lambda p: (
            p["portfolio_return_pct"] is None,
            p["portfolio_return_pct"] or ZERO,
            p["portfolio_name"],
            p["portfolio_id"],
        )
    )
    value_fields = [
        "pre_portfolio_value",
        "post_portfolio_value",
        "portfolio_pnl",
        "pre_equity_value",
        "post_equity_value",
        "equity_pnl",
    ]
    totals = {field: sum((p[field] for p in results), ZERO) for field in value_fields}
    totals["portfolio_return_pct"] = _percent(
        totals["portfolio_pnl"], totals["pre_portfolio_value"]
    )
    totals["equity_return_pct"] = _percent(totals["equity_pnl"], totals["pre_equity_value"])
    columns = [
        "portfolio_name",
        "currency",
        "pre_portfolio_value",
        "post_portfolio_value",
        "portfolio_pnl",
        "portfolio_return_pct",
        "equity_return_pct",
        "top_loss_sector",
    ]
    return _json_safe(
        {
            "scenario_label": request.scenario_label,
            "hypothetical": True,
            "sector_shocks": shocks,
            "unmentioned_equity_shock": request.unmentioned_equity_shock,
            "bond_shock": request.bond_shock,
            "currency": currency,
            "columns": columns,
            "rows": [[p[column] for column in columns] for p in results],
            "row_count": len(results),
            "portfolios": results,
            "totals": totals,
            "source_tables": ["holdings", "portfolios", "securities", "sectors"],
            "source_dates": {
                "security_current_price_as_of": [None],
                "holdings_purchase_date": sorted(dates),
            },
            "warnings": warnings,
            "assumptions": [
                "Hypothetical scenario, not a forecast or recommendation.",
                "Prices are securities.current_price from the historical supplied snapshot, not live market prices. No current-price observation date is supplied; purchase dates are not price dates.",
                f"Unmentioned equities receive a fractional shock of {_text(request.unmentioned_equity_shock)}; bonds receive {_text(request.bond_shock)}. Bond sector classifications do not determine their shock.",
                "Portfolio value uses every supplied holding's quantity × current price. No fees, trades, income, FX changes or rebalancing are simulated.",
                "Reported total_aum and recorded current_weight describe different source measures and need not equal the available holdings market value; neither is a return denominator. The dataset does not reconcile the difference.",
                "Missing, negative, nonfinite prices/quantities, unknown stock sectors or mixed currencies cause an explicit error; zero-value holdings are retained with a warning.",
                "Money uses exact Decimal arithmetic on SQLite numeric values converted with str; source REAL storage may already limit precision. Ratios use 128 significant digits; round only for display.",
                "Rank ascending by portfolio percentage return, then portfolio name/ID; undefined zero-value returns follow defined returns. Worst-sector ties use sector name; no negative sector P&L means no loss sector.",
            ],
            "formulas": {
                "holding": "pre = quantity × current_price; post = pre × (1 + shock); pnl = post − pre",
                "portfolio": "pre/post = SUM(all holding pre/post); pnl = post − pre; return_pct = 100 × pnl / pre (N/A if pre = 0)",
                "equity": "pre/post_equity = SUM(Stock pre/post); equity_pnl = post_equity − pre_equity; equity_return_pct = 100 × equity_pnl / pre_equity (N/A if pre_equity = 0)",
                "sector": "sector_pnl = SUM(Stock pnl in sector); post_equity_normalized_sector_exposure_pct = 100 × post_sector_equity_value / post_equity_value (N/A if denominator = 0)",
                "whole_portfolio_sector": "post_whole_portfolio_sector_exposure_pct = 100 × post_sector_equity_value / post_portfolio_value (N/A if denominator = 0)",
            },
        }
    )
