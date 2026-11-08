"""Additional assessment challenges, isolated from production agent planning.

The catalog contains questions and reference SQL, never stored answer numbers.
Every SQL oracle is checked against separately written Python calculations.
This module is entered only by explicit challenge evaluation, never routing.
"""

import json
import math
import os
import re
import sqlite3
import tempfile
import time
from collections import defaultdict
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pl_capital.database import TABLES, fingerprint
from pl_capital.errors import ConfigurationError, DataError

STATUSES = ("pass", "fail", "unsupported", "inconclusive", "not_run")


def load_questions(root: Path | None = None) -> list[dict]:
    candidates = [Path(root or Path.cwd()) / "tests/challenges/advanced_questions.json"]
    candidates += [
        Path(__file__).parents[2] / "tests/challenges/advanced_questions.json",
        Path(__file__).parent / "resources/advanced_questions.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
                if [q["id"] for q in questions] != list(range(1, 21)):
                    raise ValueError("Expected the twenty distinct source questions.")
                return questions
            except (ValueError, KeyError, TypeError) as exc:
                raise DataError("Advanced challenge catalog is invalid.") from exc
    raise DataError("Advanced challenge catalog is absent; run from the assessment checkout.")


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    disable_extensions = getattr(connection, "enable_load_extension", None)
    if disable_extensions is not None:
        try:
            disable_extensions(False)
        except sqlite3.NotSupportedError:
            pass
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 200_000)
    deadline = time.monotonic() + 10
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return connection


def _selected_ids(ids, maximum=20) -> list[int]:
    if type(maximum) is not int or not 0 <= maximum <= 20:
        raise ConfigurationError("Challenge max_questions must be an integer between 0 and 20.")
    selected = list(range(1, 21)) if ids is None else list(ids)
    if any(type(ident) is not int or not 1 <= ident <= 20 for ident in selected) or len(
        set(selected)
    ) != len(selected):
        raise ConfigurationError("Challenge IDs must be distinct integers from 1 through 20.")
    return selected[:maximum]


def reference_results(data_root: Path, db_path: Path, *, ids=None) -> dict[int, dict]:
    selected = _selected_ids(ids)
    results = {}
    with closing(_connect(db_path)) as connection:
        for case in load_questions(data_root):
            if case["id"] not in selected:
                continue
            cursor = connection.execute(case["reference_sql"])
            rows = [list(row) for row in cursor.fetchmany(1001)]
            if len(rows) > 1000:
                raise DataError("Challenge reference exceeded its 1000-row budget.")
            result = {
                "columns": [item[0] for item in cursor.description],
                "rows": rows,
                "row_count": len(rows),
                "truncated": False,
            }
            if len(json.dumps(result, allow_nan=False).encode()) > 1_000_000:
                raise DataError("Challenge reference exceeded its 1 MB output budget.")
            results[case["id"]] = result
    return results


def _decimal(value) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite():
        raise DataError("Independent challenge reference encountered nonfinite source data.")
    return number


def _number(value):
    return float(value) if isinstance(value, Decimal) else value


def _python_references(path: Path) -> dict[int, list[dict]]:
    """Pure Python group/set/time-series calculations, not SQL-oracle replay."""
    with closing(_connect(path)) as connection:
        data = {
            table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]  # noqa: S608
            for table in TABLES
        }
    portfolios = {row["portfolio_id"]: row for row in data["portfolios"]}
    securities = {row["security_id"]: row for row in data["securities"]}
    sectors = {row["sector_id"]: row for row in data["sectors"]}
    holdings = []
    by_portfolio = defaultdict(list)
    by_security = defaultdict(list)
    for original in data["holdings"]:
        security = securities[original["security_id"]]
        row = {
            **security,
            **portfolios[original["portfolio_id"]],
            **original,
            "sector_name": sectors.get(security["sector_id"], {}).get("sector_name"),
        }
        row["value"] = _decimal(row["quantity"]) * _decimal(row["current_price"])
        row["weight"] = _decimal(row["current_weight"])
        holdings.append(row)
        by_portfolio[row["portfolio_id"]].append(row)
        by_security[row["security_id"]].append(row)
    equity = [row for row in holdings if row["asset_type"] == "Stock"]
    stock_groups = defaultdict(list)
    for row in equity:
        stock_groups[row["portfolio_id"]].append(row)

    def total(rows, key):
        return sum((_decimal(row[key]) for row in rows), Decimal(0))

    def sector_totals(rows, key):
        values = defaultdict(Decimal)
        for row in rows:
            values[row["sector_name"]] += row[key]
        return values

    answers = {ident: [] for ident in range(1, 21)}
    for ident, rows in stock_groups.items():
        weight, value = total(rows, "weight"), total(rows, "value")
        sw, sv = sector_totals(rows, "weight"), sector_totals(rows, "value")
        if weight > 0 and value > 0:
            recorded = min(sw, key=lambda name: (-sw[name], name))
            valued = min(sv, key=lambda name: (-sv[name], name))
            if recorded != valued:
                recorded_pct, valued_pct = 100 * sw[recorded] / weight, 100 * sv[valued] / value
                answers[1].append(
                    {
                        "portfolio_name": portfolios[ident]["portfolio_name"],
                        "recorded_top_sector": recorded,
                        "recorded_top_pct": recorded_pct,
                        "value_top_sector": valued,
                        "value_top_pct": valued_pct,
                        "top_gap_pp": valued_pct - recorded_pct,
                        "equity_weight_total": weight,
                        "equity_market_value": value,
                    }
                )
        if value > 0:
            hhi = sum(((part / value) ** 2 for part in sv.values()), Decimal(0))
            answers[3].append(
                {
                    "portfolio_name": portfolios[ident]["portfolio_name"],
                    "hhi": hhi,
                    "effective_sector_count": 1 / hhi,
                    "top_sector": min(sv, key=lambda name: (-sv[name], name)),
                    "equity_market_value": value,
                }
            )
        if weight > 0 and value > 0:
            for row in rows:
                rw, mv = 100 * row["weight"] / weight, 100 * row["value"] / value
                answers[6].append(
                    {
                        "portfolio_name": row["portfolio_name"],
                        "symbol": row["symbol"],
                        "company_name": row["company_name"],
                        "equity_weight_total": weight,
                        "equity_market_value": value,
                        "current_weight": row["weight"],
                        "holding_market_value": row["value"],
                        "recorded_equity_pct": rw,
                        "market_value_pct": mv,
                        "discrepancy_pp": mv - rw,
                        "abs_discrepancy_pp": abs(mv - rw),
                    }
                )
    answers[1].sort(key=lambda row: row["portfolio_name"])
    answers[3].sort(key=lambda row: (-row["hhi"], row["portfolio_name"]))
    answers[6].sort(
        key=lambda row: (-row["abs_discrepancy_pp"].quantize(Decimal("0.0000000001")), row["portfolio_name"], row["symbol"])
    )
    answers[6] = answers[6][:10]
    for ident, portfolio in portfolios.items():
        rows = by_portfolio[ident]
        stocks = stock_groups[ident]
        bonds = [row for row in rows if row["asset_type"] == "Bond"]
        recorded, stock_weight, bond_weight = (
            total(rows, "weight"),
            total(stocks, "weight"),
            total(bonds, "weight"),
        )
        if portfolio["portfolio_name"] in {"Conservative Income Fund", "Balanced Portfolio"}:
            for name, weight in sorted(sector_totals(stocks, "weight").items()):
                answers[2].append(
                    {
                        "portfolio_name": portfolio["portfolio_name"],
                        "sector_name": name,
                        "bond_weight": bond_weight,
                        "equity_weight": stock_weight,
                        "recorded_total": recorded,
                        "sector_weight": weight,
                        "portfolio_pct": 100 * weight / recorded if recorded else None,
                        "equity_pct": 100 * weight / stock_weight if stock_weight else None,
                        "weights_sum_to_100": int(abs(recorded - 1) < Decimal("1e-10")),
                    }
                )
        if rows and abs(recorded - 1) > Decimal("0.005"):
            answers[4].append(
                {
                    "portfolio_name": portfolio["portfolio_name"],
                    "recorded_weight_sum": recorded,
                    "discrepancy_pp": 100 * (recorded - 1),
                    "has_bonds": int(bool(bonds)),
                }
            )
        value = total(rows, "value") if rows else None
        aum = _decimal(portfolio["total_aum"]) if portfolio["total_aum"] is not None else None
        ratio = value / aum if value is not None and aum else None
        answers[5].append(
            {
                "portfolio_name": portfolio["portfolio_name"],
                "total_aum": aum,
                "holdings_market_value": value,
                "difference": aum - value if aum is not None and value is not None else None,
                "holdings_to_aum_ratio": ratio,
                "aum_coverage_pct": 100 * ratio if ratio is not None else None,
            }
        )
        stock_sectors = {row["sector_id"] for row in stocks if row["sector_id"] is not None}
        if stocks and bonds and len(stock_sectors) > 2 and abs(recorded - 1) >= Decimal("0.005"):
            answers[20].append(
                {
                    "portfolio_name": portfolio["portfolio_name"],
                    "stock_holding_count": len(stocks),
                    "bond_holding_count": len(bonds),
                    "equity_sector_count": len(stock_sectors),
                    "recorded_weight_sum": recorded,
                    "discrepancy_pp": 100 * (recorded - 1),
                }
            )
        bond_value = total(bonds, "value")
        for row in bonds:
            answers[19].append(
                {
                    "portfolio_name": row["portfolio_name"],
                    "symbol": row["symbol"],
                    "maturity_date": row["maturity_date"],
                    "coupon_rate": row["coupon_rate"],
                    "quantity": row["quantity"],
                    "bond_market_value": row["value"],
                    "total_bond_market_value": bond_value,
                    "bond_share_pct": 100 * row["value"] / bond_value if bond_value else None,
                }
            )
    answers[2].sort(key=lambda row: (row["portfolio_name"], row["sector_name"]))
    answers[4].sort(key=lambda row: (-abs(row["discrepancy_pp"]), row["portfolio_name"]))
    answers[5].sort(
        key=lambda row: (
            row["difference"] is None,
            -abs(row["difference"] or 0),
            row["portfolio_name"],
        )
    )
    for rank, row in enumerate(answers[5], 1):
        row.update(mismatch_rank=rank, is_top_five=int(rank <= 5))
    sets = {ident: {row["security_id"] for row in rows} for ident, rows in stock_groups.items()}
    ids = sorted(sets)
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            intersection, union = len(sets[left] & sets[right]), len(sets[left] | sets[right])
            if intersection >= 3:
                answers[7].append(
                    {
                        "portfolio_a_id": left,
                        "portfolio_b_id": right,
                        "portfolio_a": portfolios[left]["portfolio_name"],
                        "portfolio_b": portfolios[right]["portfolio_name"],
                        "intersection_count": intersection,
                        "union_count": union,
                        "jaccard_similarity": Decimal(intersection) / union,
                    }
                )
    answers[7].sort(
        key=lambda row: (-row["jaccard_similarity"], row["portfolio_a_id"], row["portfolio_b_id"])
    )
    all_equity_value = total(equity, "value")
    for ident, rows in by_security.items():
        security = securities[ident]
        if security["asset_type"] != "Stock":
            continue
        high = [row for row in rows if row["target_risk_level"] == "High"]
        low = [row for row in rows if row["target_risk_level"] == "Low"]
        if high and low:
            answers[8].append(
                {
                    "symbol": security["symbol"],
                    "company_name": security["company_name"],
                    "high_portfolio_count": len({row["portfolio_id"] for row in high}),
                    "low_portfolio_count": len({row["portfolio_id"] for row in low}),
                    "high_quantity": total(high, "quantity"),
                    "low_quantity": total(low, "quantity"),
                    "high_market_value": total(high, "value"),
                    "low_market_value": total(low, "value"),
                }
            )
        value = total(rows, "value")
        answers[9].append(
            {
                "symbol": security["symbol"],
                "sector_name": sectors.get(security["sector_id"], {}).get("sector_name"),
                "portfolio_count": len({row["portfolio_id"] for row in rows}),
                "total_quantity": total(rows, "quantity"),
                "market_value": value,
                "total_equity_market_value": all_equity_value,
                "equity_value_fraction": value / all_equity_value if all_equity_value else None,
            }
        )
    answers[8].sort(key=lambda row: row["symbol"])
    answers[9].sort(key=lambda row: (-row["market_value"], row["symbol"]))
    answers[9] = answers[9][:5]
    for sector in sectors.values():
        assigned = {
            security["security_id"]
            for security in securities.values()
            if security["sector_id"] == sector["sector_id"]
        }
        if not assigned:
            answers[10].append(
                {
                    "sector_id": sector["sector_id"],
                    "sector_name": sector["sector_name"],
                    "security_count": len(assigned),
                    "holding_count": sum(row["security_id"] in assigned for row in holdings),
                }
            )
    answers[10].sort(key=lambda row: row["sector_name"])
    _python_time_series(data, portfolios, securities, answers)
    transactions = defaultdict(list)
    for transaction in data["transactions"]:
        transactions[transaction["portfolio_id"]].append(transaction)
        if transaction["transaction_type"] == "SELL":
            holding = next(
                (
                    row
                    for row in by_portfolio[transaction["portfolio_id"]]
                    if row["security_id"] == transaction["security_id"]
                ),
                None,
            )
            gross = _decimal(transaction["quantity"]) * _decimal(transaction["price"])
            answers[18].append(
                {
                    "transaction_id": transaction["transaction_id"],
                    "portfolio_name": portfolios[transaction["portfolio_id"]]["portfolio_name"],
                    "symbol": securities[transaction["security_id"]]["symbol"],
                    "transaction_date": transaction["transaction_date"],
                    "quantity": transaction["quantity"],
                    "price": transaction["price"],
                    "gross_proceeds": gross,
                    "fees": transaction["fees"],
                    "net_proceeds": gross - _decimal(transaction["fees"]),
                    "current_holding_quantity": holding["quantity"] if holding else None,
                }
            )
    for ident, rows in transactions.items():
        buys = sum(
            (
                _decimal(row["quantity"]) * _decimal(row["price"])
                for row in rows
                if row["transaction_type"] == "BUY"
            ),
            Decimal(0),
        )
        sells = sum(
            (
                _decimal(row["quantity"]) * _decimal(row["price"])
                for row in rows
                if row["transaction_type"] == "SELL"
            ),
            Decimal(0),
        )
        fees = total(rows, "fees")
        answers[17].append(
            {
                "portfolio_name": portfolios[ident]["portfolio_name"],
                "buy_notional": buys,
                "sell_notional": sells,
                "total_fees": fees,
                "net_cash_movement": sells - buys - fees,
                "transaction_count": len(rows),
                "buy_count": sum(row["transaction_type"] == "BUY" for row in rows),
                "sell_count": sum(row["transaction_type"] == "SELL" for row in rows),
            }
        )
    answers[17].sort(key=lambda row: row["portfolio_name"])
    answers[18].sort(key=lambda row: (row["transaction_date"], row["transaction_id"]))
    answers[19].sort(key=lambda row: (row["portfolio_name"], row["symbol"]))
    answers[20].sort(key=lambda row: row["portfolio_name"])
    return {
        ident: [{key: _number(value) for key, value in row.items()} for row in rows]
        for ident, rows in answers.items()
    }


def _python_time_series(data, portfolios, securities, answers):
    prices = defaultdict(list)
    for row in data["historical_prices"]:
        if securities[row["security_id"]]["asset_type"] == "Stock":
            prices[row["security_id"]].append(row)
    returns = []
    for ident, observations in prices.items():
        observations.sort(key=lambda row: row["price_date"])
        first, last = observations[0], observations[-1]
        security = securities[ident]
        if len(observations) >= 2 and first["close_price"] > 0:
            returns.append(
                {
                    "symbol": security["symbol"],
                    "first_date": first["price_date"],
                    "last_date": last["price_date"],
                    "first_close": first["close_price"],
                    "last_close": last["close_price"],
                    "return_pct": 100
                    * (_decimal(last["close_price"]) / _decimal(first["close_price"]) - 1),
                    "current_price": security["current_price"],
                    "last_close_matches_current": int(
                        abs(_decimal(security["current_price"]) - _decimal(last["close_price"]))
                        <= Decimal("1e-9")
                    ),
                }
            )
        run, best = 0, None
        start = None
        for previous, current in zip(observations, observations[1:], strict=False):
            if current["close_price"] < previous["close_price"]:
                if not run:
                    start = previous["price_date"]
                run += 1
                if best is None or run > best[0]:
                    best = (run, start, current["price_date"])
            else:
                run = 0
        if best and best[0] >= 3:
            answers[12].append(
                {
                    "symbol": security["symbol"],
                    "longest_decline_streak": best[0],
                    "start_date": best[1],
                    "end_date": best[2],
                    "observation_count": best[0] + 1,
                }
            )
        for row in observations:
            if (
                row["open_price"] is not None
                and row["open_price"] > 0
                and row["high_price"] is not None
                and row["low_price"] is not None
            ):
                answers[13].append(
                    {
                        "symbol": security["symbol"],
                        "price_date": row["price_date"],
                        "open_price": row["open_price"],
                        "high_price": row["high_price"],
                        "low_price": row["low_price"],
                        "intraday_range_pct": 100
                        * (_decimal(row["high_price"]) - _decimal(row["low_price"]))
                        / _decimal(row["open_price"]),
                    }
                )
    for group, ordered in (
        ("best", sorted(returns, key=lambda row: (-row["return_pct"], row["symbol"]))),
        ("worst", sorted(returns, key=lambda row: (row["return_pct"], row["symbol"]))),
    ):
        answers[11].extend(
            dict(extreme=group, rank_in_group=index, **row)
            for index, row in enumerate(ordered[:5], 1)
        )
    answers[12].sort(key=lambda row: (-row["longest_decline_streak"], row["symbol"]))
    answers[13].sort(key=lambda row: (-row["intraday_range_pct"], row["symbol"], row["price_date"]))
    answers[13] = answers[13][:10]
    performance = defaultdict(list)
    risk = defaultdict(list)
    risk_by_key = {
        (row["portfolio_id"], row["calculation_date"]): row for row in data["risk_metrics"]
    }
    common = defaultdict(list)
    for row in data["portfolio_performance"]:
        performance[row["portfolio_id"]].append(row)
        if (row["portfolio_id"], row["performance_date"]) in risk_by_key:
            common[row["portfolio_id"]].append(row)
    for row in data["risk_metrics"]:
        risk[row["portfolio_id"]].append(row)
    for ident, rows in common.items():
        selected = max(rows, key=lambda row: row["performance_date"])
        matching = risk_by_key[(ident, selected["performance_date"])]
        answers[14].append(
            {
                "portfolio_name": portfolios[ident]["portfolio_name"],
                "common_date": selected["performance_date"],
                "return_1m": selected["total_return_1m"],
                "volatility": selected["volatility"],
                "sharpe_ratio": selected["sharpe_ratio"],
                "var_95": matching["var_95"],
                "cvar_95": matching["cvar_95"],
                "beta": matching["beta"],
                "max_drawdown": selected["max_drawdown"],
            }
        )
    for ident, rows in performance.items():
        rows.sort(key=lambda row: row["performance_date"])
        first, last = rows[0], rows[-1]
        if first["nav"] > 0:
            answers[15].append(
                {
                    "portfolio_name": portfolios[ident]["portfolio_name"],
                    "first_date": first["performance_date"],
                    "last_date": last["performance_date"],
                    "first_nav": first["nav"],
                    "last_nav": last["nav"],
                    "nav_change": _decimal(last["nav"]) - _decimal(first["nav"]),
                    "nav_change_pct": 100 * (_decimal(last["nav"]) / _decimal(first["nav"]) - 1),
                    "observation_count": len(rows),
                }
            )
    for ident, rows in risk.items():
        rows.sort(key=lambda row: row["calculation_date"])
        first, last = rows[0], rows[-1]
        signed = _decimal(last["var_95"]) - _decimal(first["var_95"])
        magnitude = abs(_decimal(last["var_95"])) - abs(_decimal(first["var_95"]))
        answers[16].append(
            {
                "portfolio_name": portfolios[ident]["portfolio_name"],
                "first_date": first["calculation_date"],
                "last_date": last["calculation_date"],
                "first_var_95": first["var_95"],
                "last_var_95": last["var_95"],
                "signed_change": signed,
                "magnitude_change": magnitude,
                "signed_direction": "less negative"
                if signed > 0
                else "more negative"
                if signed < 0
                else "unchanged",
                "magnitude_direction": "increased"
                if magnitude > 0
                else "decreased"
                if magnitude < 0
                else "unchanged",
            }
        )
    answers[14].sort(key=lambda row: row["portfolio_name"])
    answers[15].sort(key=lambda row: (-row["nav_change_pct"], row["portfolio_name"]))
    answers[16].sort(key=lambda row: row["portfolio_name"])


ALIASES = {
    "portfolio_name": "portfolio fund fund_name",
    "sector_name": "sector",
    "symbol": "ticker stock_symbol security_symbol bond_symbol",
    "company_name": "security_name stock_name company",
    "recorded_top_sector": "weight_top_sector top_recorded_sector top_weight_sector recorded_sector largest_weight_sector",
    "recorded_top_pct": "recorded_top_percentage weight_top_pct recorded_weight_pct top_weight_pct recorded_percentage",
    "value_top_sector": "market_value_top_sector top_value_sector valuation_sector market_top_sector largest_value_sector",
    "value_top_pct": "value_top_percentage market_value_top_pct market_top_pct top_value_pct valuation_percentage",
    "top_gap_pp": "gap_pp percentage_point_gap top_percentage_gap value_minus_recorded_gap recorded_minus_value_gap",
    "equity_weight_total": "total_equity_weight total_stock_weight stock_weight_total equity_weight_sum",
    "equity_market_value": "stock_market_value total_stock_market_value total_equity_market_value equity_value stock_value",
    "bond_weight": "bond_weight_total total_bond_weight",
    "equity_weight": "stock_weight equity_weight_total total_equity_weight total_stock_weight",
    "recorded_total": "total_recorded_weight recorded_weight_total total_weight recorded_weight_sum",
    "sector_weight": "sector_weight_sum raw_sector_weight",
    "portfolio_pct": "whole_portfolio_pct portfolio_percentage whole_portfolio_percentage sector_portfolio_pct portfolio_relative_pct",
    "equity_pct": "equity_normalized_pct equity_percentage equity_normalized_percentage stock_sector_pct",
    "weights_sum_to_100": "is_complete weights_sum_100 sum_to_100 sums_to_100 weight_coverage_complete",
    "hhi": "sector_hhi concentration_index herfindahl_index herfindahl_hirschman_index",
    "effective_sector_count": "effective_sectors effective_number_of_sectors inverse_hhi",
    "top_sector": "largest_sector dominant_sector",
    "recorded_weight_sum": "weight_sum recorded_sum total_weight recorded_total total_recorded_weight sum_current_weight",
    "discrepancy_pp": "weight_discrepancy_pp difference_pp signed_gap_pp signed_discrepancy_pp discrepancy_percentage_points",
    "has_bonds": "holds_bonds holds_bond bond_present has_bond_holdings",
    "total_aum": "aum recorded_aum",
    "holdings_market_value": "holdings_value total_holdings_value listed_holdings_value market_value total_market_value",
    "difference": "aum_minus_holdings aum_gap dollar_difference aum_difference mismatch holdings_minus_aum",
    "holdings_to_aum_ratio": "coverage_ratio holdings_aum_ratio holdings_to_aum aum_ratio aum_to_holdings_ratio",
    "aum_coverage_pct": "coverage_pct coverage_percentage aum_percentage percent_of_aum holdings_coverage_pct",
    "mismatch_rank": "rank mismatch_position discrepancy_rank",
    "is_top_five": "is_top_5 top_five top5 largest_five",
    "current_weight": "recorded_weight holding_weight",
    "holding_market_value": "holding_value security_market_value holding_mv",
    "recorded_equity_pct": "recorded_equity_percentage normalized_weight_pct recorded_normalized_pct weight_normalized_pct recorded_pct",
    "market_value_pct": "market_value_percentage value_normalized_pct market_value_normalized_pct value_pct market_pct",
    "abs_discrepancy_pp": "absolute_discrepancy_pp absolute_gap_pp abs_gap_pp absolute_difference_pp abs_difference_pp",
    "portfolio_a_id": "portfolio_id_a portfolio1_id portfolio_id_1",
    "portfolio_b_id": "portfolio_id_b portfolio2_id portfolio_id_2",
    "portfolio_a": "portfolio_a_name portfolio1 portfolio_1 portfolio_name_1 first_portfolio",
    "portfolio_b": "portfolio_b_name portfolio2 portfolio_2 portfolio_name_2 second_portfolio",
    "intersection_count": "shared_count common_stocks shared_stock_count overlap_count intersection",
    "union_count": "union union_size total_unique_stocks",
    "jaccard_similarity": "jaccard jaccard_index similarity jaccard_pct jaccard_percentage",
    "high_portfolio_count": "high_count high_risk_count high_risk_portfolio_count high_risk_portfolios",
    "low_portfolio_count": "low_count low_risk_count low_risk_portfolio_count low_risk_portfolios",
    "high_quantity": "high_risk_quantity high_total_quantity high_shares",
    "low_quantity": "low_risk_quantity low_total_quantity low_shares",
    "high_market_value": "high_risk_market_value high_total_value high_value",
    "low_market_value": "low_risk_market_value low_total_value low_value",
    "portfolio_count": "distinct_portfolio_count portfolios_count num_portfolios fund_count",
    "total_quantity": "total_shares aggregate_quantity aggregate_shares shares quantity",
    "market_value": "aggregate_value aggregate_market_value total_value total_market_value held_market_value",
    "total_equity_market_value": "all_equity_value total_equity_value all_stock_value total_stock_market_value equity_denominator",
    "equity_value_fraction": "equity_fraction fraction_of_equity share_of_equity equity_share total_equity_fraction equity_value_pct equity_percentage share_pct",
    "security_count": "securities_count mapped_security_count mapped_securities",
    "holding_count": "holdings_count mapped_holding_count num_holdings",
    "extreme": "group category return_group ranking_group side",
    "rank_in_group": "rank return_rank group_rank rank_position",
    "first_date": "start_date first_observation_date earliest_date first_price_date first_performance_date first_risk_date",
    "last_date": "end_date last_observation_date latest_date last_price_date last_performance_date last_risk_date",
    "first_close": "first_close_price start_close initial_close first_price",
    "last_close": "last_close_price end_close final_close last_price",
    "return_pct": "return_percentage historical_return_pct price_return_pct total_return_pct observed_return_pct",
    "current_price": "recorded_current_price snapshot_price",
    "last_close_matches_current": "matches_current_price current_matches_last current_price_equals_last_close price_matches equals_current_price",
    "longest_decline_streak": "longest_streak longest_losing_streak max_decline_streak decline_streak streak_length consecutive_declines",
    "start_date": "streak_start_date streak_start first_date",
    "end_date": "streak_end_date streak_end last_date",
    "observation_count": "observations num_observations data_points observation_points price_observation_count",
    "price_date": "date observation_date",
    "intraday_range_pct": "range_pct intraday_range_percentage intraday_pct percentage_range range_percentage pct_change",
    "common_date": "latest_common_date observation_date date latest_date synchronized_date performance_date calculation_date",
    "return_1m": "total_return_1m one_month_return return_1m_pct one_month_return_pct",
    "volatility": "volatility_pct volatility_percentage",
    "sharpe_ratio": "sharpe",
    "var_95": "var95 var_95_pct var95_pct",
    "cvar_95": "cvar95 cvar_95_pct cvar95_pct",
    "max_drawdown": "maximum_drawdown drawdown max_drawdown_pct drawdown_pct",
    "first_nav": "initial_nav start_nav",
    "last_nav": "final_nav end_nav",
    "nav_change": "absolute_nav_change nav_absolute_change nav_change_abs absolute_change nav_difference",
    "nav_change_pct": "nav_percentage_change percentage_nav_change nav_return_pct percentage_change pct_change",
    "first_var_95": "first_var95 var_first initial_var95 initial_var_95 start_var_95",
    "last_var_95": "last_var95 var_last final_var95 final_var_95 end_var_95",
    "signed_change": "signed_var_change var_signed_change var_change signed_difference",
    "magnitude_change": "absolute_magnitude_change change_in_magnitude var_magnitude_change abs_var_change abs_change",
    "signed_direction": "var_direction signed_var_direction direction",
    "magnitude_direction": "absolute_direction magnitude_trend risk_magnitude_direction",
    "buy_notional": "gross_buys buy_cost total_buys gross_buy_notional buy_value",
    "sell_notional": "gross_sells sell_proceeds total_sells gross_sell_notional sell_value",
    "total_fees": "fees transaction_fees all_fees",
    "net_cash_movement": "observed_cash_movement observed_transaction_cash_movement net_cash_flow net_cashflow cash_movement net_movement",
    "transaction_count": "transactions_count num_transactions total_transactions",
    "buy_count": "buy_transactions buy_transaction_count",
    "sell_count": "sell_transactions sell_transaction_count",
    "gross_proceeds": "gross_sale_proceeds sale_proceeds gross_sell_value",
    "fees": "fee transaction_fee",
    "net_proceeds": "net_sale_proceeds sale_net_proceeds",
    "current_holding_quantity": "holding_quantity current_quantity held_quantity current_shares",
    "bond_market_value": "bond_value holding_value holding_market_value market_value",
    "total_bond_market_value": "portfolio_bond_value total_bond_value bond_value_total bond_denominator",
    "bond_share_pct": "bond_share_percentage bond_percentage share_of_bond_value_pct bond_weight_pct bond_pct",
    "stock_holding_count": "stock_count equity_count equity_holding_count stock_holdings",
    "bond_holding_count": "bond_count bond_holdings",
    "equity_sector_count": "stock_sector_count sector_count distinct_equity_sectors distinct_stock_sectors",
}
FRACTION_FIELDS = {
    "jaccard_similarity",
    "equity_value_fraction",
    "holdings_to_aum_ratio",
}
FLAGS = {"weights_sum_to_100", "has_bonds", "is_top_five", "last_close_matches_current"}


def _label(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower().split(".")[-1])


def _equivalent(actual, expected) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, int | float) and isinstance(expected, int | float):
        return (
            math.isfinite(actual)
            and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6)
        )
    return (
        isinstance(actual, str)
        and isinstance(expected, str)
        and actual.strip().casefold() == expected.strip().casefold()
    )


def _rows_equal(actual: list, expected: list, ordered: bool) -> bool:
    if len(actual) != len(expected):
        return False

    def same(left, right):
        return len(left) == len(right) and all(
            _equivalent(a, b) for a, b in zip(left, right, strict=True)
        )

    if ordered:
        return all(same(left, right) for left, right in zip(actual, expected, strict=True))
    matches = {}

    def assign(index, seen):
        for candidate, row in enumerate(expected):
            if candidate in seen or not same(actual[index], row):
                continue
            seen.add(candidate)
            if candidate not in matches or assign(matches[candidate], seen):
                matches[candidate] = index
                return True
        return False

    return all(assign(index, set()) for index in range(len(actual)))


def _unit(value, canonical: str, actual_label: str):
    if value is None:
        return value
    normalized = _label(actual_label)
    if canonical in FLAGS:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, str) and value.casefold() in {"yes", "true", "no", "false"}:
            return int(value.casefold() in {"yes", "true"})
    if canonical == "extreme" and isinstance(value, str):
        if re.fullmatch(r"(?:best|top)(?:\s*5|\s+five)?", value.strip(), re.I):
            return "best"
        if re.fullmatch(r"(?:worst|bottom)(?:\s*5|\s+five)?", value.strip(), re.I):
            return "worst"
    if canonical in {"signed_direction", "magnitude_direction"} and isinstance(value, str):
        text = value.replace("_", " ").casefold()
        for label in ("less negative", "more negative", "unchanged", "increased", "decreased"):
            if label in text:
                return label
    if (
        canonical in FRACTION_FIELDS
        and ("pct" in normalized or "percentage" in normalized)
        and isinstance(value, int | float)
    ):
        return value / 100
    if (
        canonical == "holdings_to_aum_ratio"
        and normalized == "aumtoholdingsratio"
        and isinstance(value, int | float)
    ):
        return 1 / value if value else None
    if (
        canonical == "difference"
        and normalized == "holdingsminusaum"
        and isinstance(value, int | float)
    ):
        return -value
    if (
        canonical == "top_gap_pp"
        and normalized == "recordedminusvaluegap"
        and isinstance(value, int | float)
    ):
        return -value
    return value


def compare_challenge(case: dict, actual: dict, expected: dict) -> tuple[str, str]:
    """Compare known semantic columns; unfamiliar shapes require human review."""
    if actual.get("truncated"):
        return "fail", "Agent result is truncated, so the complete requested set was not returned."
    columns, rows = actual.get("columns"), actual.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) > 1000:
        return (
            "inconclusive",
            "Agent did not return a bounded tabular result that this comparator understands.",
        )
    if any(not isinstance(row, list | tuple) or len(row) != len(columns) for row in rows):
        return "inconclusive", "Agent result has an unknown or malformed row/column shape."
    if actual.get("row_count") != len(rows):
        return "fail", "Declared row count differs from actual returned rows."
    mapping = {}
    for index, name in enumerate(columns):
        direct = [field for field in expected["columns"] if _label(name) == _label(field)]
        candidates = direct or [
            field
            for field in expected["columns"]
            if _label(name) in {_label(alias) for alias in ALIASES.get(field, "").split()}
        ]
        if len(candidates) != 1 or candidates[0] in mapping:
            return (
                "inconclusive",
                f"Column {name!r} has no unique documented semantic mapping; manual review required.",
            )
        mapping[candidates[0]] = (index, name)
    missing = set(case["required_columns"]) - set(mapping)
    if case["id"] == 7 and {"portfolio_a_id", "portfolio_b_id"} <= set(mapping):
        # IDs identify the two funds just as unambiguously as their names.
        missing -= {"portfolio_a", "portfolio_b"}
    if missing:
        return "fail", "Requested measures are missing: " + ", ".join(sorted(missing)) + "."
    fields = [field for field in expected["columns"] if field in mapping]
    normalized = [
        [_unit(row[mapping[field][0]], field, mapping[field][1]) for field in fields]
        for row in rows
    ]
    wanted = [
        [row[expected["columns"].index(field)] for field in fields] for row in expected["rows"]
    ]
    if case["id"] == 7:
        # An unordered portfolio pair is the same pair in either orientation.
        # Similarity ranking is required; equal-score pairs can appear in any order.
        for collection in (normalized, wanted):
            keys = ("portfolio_a_id", "portfolio_b_id") if {"portfolio_a_id", "portfolio_b_id"} <= set(fields) else ("portfolio_a", "portfolio_b")
            left, right = (fields.index(name) for name in keys)
            for row in collection:
                if row[left] > row[right]:
                    for a, b in (("portfolio_a_id", "portfolio_b_id"), ("portfolio_a", "portfolio_b")):
                        if a in fields and b in fields:
                            i, j = fields.index(a), fields.index(b)
                            row[i], row[j] = row[j], row[i]
        score = fields.index("jaccard_similarity")
        ranked = all(float(a[score]) >= float(b[score]) - 1e-9 for a, b in zip(normalized, normalized[1:], strict=False))
        matched = ranked and _rows_equal(normalized, wanted, False)
    else:
        matched = _rows_equal(normalized, wanted, case["ordered"])
    if matched:
        return (
            "pass",
            "Matched the independent reference for every returned semantic column and required measure.",
        )
    if len(normalized) != len(wanted):
        return "fail", f"Expected {len(wanted)} rows; agent returned {len(normalized)}."
    return (
        "fail",
        "Values, duplicates, required ranking, or numeric precision differ from the independent reference.",
    )


def verify_references(data_root: Path, db_path: Path) -> dict:
    cases = load_questions(data_root)
    sql_results = reference_results(data_root, db_path)
    python_rows = _python_references(db_path)
    items = []
    for case in cases:
        result = sql_results[case["id"]]
        calculated = python_rows[case["id"]]
        if any(set(row) != set(result["columns"]) for row in calculated):
            status, reason = "fail", "Independent Python fields differ from SQL reference columns."
        else:
            rows = [[row[field] for field in result["columns"]] for row in calculated]
            status = "pass" if _rows_equal(result["rows"], rows, case["ordered"]) else "fail"
            reason = (
                "SQL reference agrees with independent Python data calculations."
                if status == "pass"
                else "SQL/Python reference mismatch; do not use this case for live scoring."
            )
        items.append(
            {
                "id": case["id"],
                "category": case["category"],
                "status": status,
                "reason": reason,
                "reference_result": result,
                "independent_row_count": len(calculated),
            }
        )
    return {
        "mode": "reference-only; no agent or Groq calls",
        "total": len(cases),
        "passed": sum(item["status"] == "pass" for item in items),
        "questions": items,
        "dataset_fingerprint": fingerprint(Path(data_root)),
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


def _redact(value, secret: str):
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(item, secret) for item in value]
    if isinstance(value, str):
        value = value.replace(secret, "[REDACTED]") if secret else value
        return re.sub(r"(?:gsk_|gh[pousr]_)[A-Za-z0-9_]{20,}", "[REDACTED]", value)
    if isinstance(value, float) and not math.isfinite(value):
        return "[NONFINITE]"
    return value


def _save(path: Path, report: dict):
    path = Path(path)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > 5_000_000:
        raise DataError("Challenge report exceeds its 5 MB budget.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="challenge-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(encoded)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def evaluate_challenges(
    agent,
    root: Path | None = None,
    *,
    live: bool = True,
    ids=None,
    report: Path | None = None,
    max_questions: int = 20,
) -> dict:
    """Run at most twenty real questions; never conflate unavailable with passing."""
    if live and (getattr(agent, "live", False) is not True or not agent.settings.api_key):
        raise ConfigurationError(
            "Live challenges require a real Groq agent and configured API key."
        )
    root = Path(root or agent.settings.data_root)
    selected = _selected_ids(ids, max_questions)
    cases = load_questions(root)
    references = verify_references(root, agent.settings.db_path)
    reference_items = {item["id"]: item for item in references["questions"]}
    started = time.perf_counter()
    items = []
    provider_error = re.compile(
        r"groq|rate.?limit|timed?\s*out|network|connection failed|authentication|api.?key", re.I
    )
    for case in cases:
        item = {key: case[key] for key in ("id", "category", "question", "assumptions")}
        item.update(
            status="not_run",
            reason="Not selected or outside the bounded run.",
            actual=None,
            expected=reference_items[case["id"]]["reference_result"],
            reference_status=reference_items[case["id"]]["status"],
            sql=None,
            parameters={},
            elapsed_ms=0,
        )
        if case["id"] not in selected:
            items.append(item)
            continue
        began = time.perf_counter()
        try:
            if hasattr(agent, "reset_context"):
                agent.reset_context()
            answer = agent.answer_question(case["question"])
            item.update(
                actual=answer.result,
                sql=answer.sql,
                parameters=answer.parameters,
                intent=answer.intent,
                tool=answer.tool,
                error=answer.error,
                message=answer.message,
                warnings=answer.warnings,
                agent_elapsed_ms=answer.elapsed_ms,
            )
            if item["reference_status"] != "pass":
                item.update(
                    status="inconclusive",
                    reason="Independent reference did not validate; no accuracy claim is made.",
                )
            elif answer.error:
                status = "inconclusive" if provider_error.search(answer.error) else "fail"
                item.update(
                    status=status,
                    reason="Provider/configuration unavailable; no result to score."
                    if status == "inconclusive"
                    else "Agent query or calculation failed.",
                )
            elif answer.intent in {"out_of_scope", "clarification_needed"}:
                unsupported = re.search(
                    r"not supported|unsupported|cannot support|does not support",
                    answer.message,
                    re.I,
                )
                item.update(
                    status="unsupported"
                    if unsupported or answer.intent == "out_of_scope"
                    else "inconclusive",
                    reason="Agent reported this legitimate compound analysis unsupported."
                    if unsupported or answer.intent == "out_of_scope"
                    else "Agent requested clarification; no final result was scored.",
                )
            elif answer.tool != "sql_query":
                item.update(
                    status="unsupported",
                    reason="The selected tool did not provide the compound tabular analysis required by this challenge.",
                )
            else:
                status, reason = compare_challenge(case, answer.result, item["expected"])
                item.update(status=status, reason=reason)
        except Exception:
            item.update(
                status="inconclusive",
                reason="Execution failed without a safe typed answer; raw exception details withheld.",
            )
        item["elapsed_ms"] = round((time.perf_counter() - began) * 1000, 3)
        items.append(item)
    counts = {status: sum(item["status"] == status for item in items) for status in STATUSES}
    result = {
        "suite": "advanced challenges; not official ground truth",
        "mode": "live Groq agent" if live else "offline test (mocked)",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "model": agent.settings.model,
        "total": len(cases),
        "attempted": sum(item["status"] != "not_run" for item in items),
        "selected_ids": selected,
        "counts": counts,
        "passed": counts["pass"],
        "accuracy_over_all_twenty": counts["pass"] / len(cases),
        "reference_passed": references["passed"],
        "questions": items,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "comparison_policy": "Known semantic aliases/reordered columns; all required measures and any recognized optional fields; complete duplicate-preserving rows; ranking only where requested; numeric abs1e-6/rel1e-10; unknown shapes are inconclusive. Qualitative explanations remain available for human review.",
    }
    result = _redact(result, agent.settings.api_key)
    if report is not None:
        _save(report, result)
    return result
