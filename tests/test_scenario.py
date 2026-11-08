"""Independent financial oracles and edge cases for the deterministic scenario service."""

import json
import sqlite3
from collections import defaultdict
from decimal import ROUND_UP, Decimal, Rounded, localcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

from pl_capital.errors import DataError, EntityError
from pl_capital.scenario import ScenarioRequest, calculate_scenario

ROOT = Path(__file__).resolve().parents[1]
SHOCKS = {"Technology": Decimal("-0.22"), "Energy": Decimal("0.11"), "Financials": Decimal("-0.07")}


@pytest.fixture
def small_db(tmp_path):
    path = tmp_path / "scenario.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript((ROOT / "database_schema.sql").read_text())
        conn.executemany(
            "INSERT INTO sectors(sector_id,sector_name) VALUES (?,?)",
            [(1, "Technology"), (2, "Energy"), (3, "Financials")],
        )
        conn.executemany(
            "INSERT INTO portfolios(portfolio_id,portfolio_name,total_aum) VALUES (?,?,?)",
            [(1, "Mixed Fund", 999999), (2, "Bond Fund", 123456), (3, "Empty Fund", 100)],
        )
        conn.executemany(
            "INSERT INTO securities(security_id,symbol,company_name,asset_type,sector_id,current_price,currency) VALUES (?,?,?,?,?,?,?)",
            [
                (1, "T1", "Tech One", "Stock", 1, 10.25, "USD"),
                (2, "T2", "Tech Two", "Stock", 1, 0.1, "USD"),
                (3, "E1", "Energy One", "Stock", 2, 20, "USD"),
                (4, "B1", "Bond One", "Bond", None, 100, "USD"),
            ],
        )
        conn.executemany(
            "INSERT INTO holdings(holding_id,portfolio_id,security_id,quantity,purchase_date) VALUES (?,?,?,?,?)",
            [
                (1, 1, 1, 2, "2023-09-01"),
                (2, 1, 2, 0.2, "2023-09-01"),
                (3, 1, 3, 3, "2023-09-01"),
                (4, 1, 4, 1, "2023-09-01"),
                (5, 2, 4, 5, "2023-09-01"),
            ],
        )
    return path


def change(path, sql, parameters=()):
    with sqlite3.connect(path) as conn:
        conn.execute(sql, parameters)


def dec(value):
    return Decimal(value)


def by_name(result):
    return {p["portfolio_name"]: p for p in result["portfolios"]}


def test_main_scenario_all_13_against_independent_python_and_sql_oracles(db_path):
    result = calculate_scenario(db_path, ScenarioRequest(sector_shocks=SHOCKS))
    # Deliberately independent joins/aggregation and formulas; no service helpers or routing.
    with sqlite3.connect(db_path) as conn:
        raw = conn.execute(
            "SELECT p.portfolio_id,p.portfolio_name,h.holding_id,h.quantity,s.current_price,s.asset_type,c.sector_name FROM portfolios p LEFT JOIN holdings h ON h.portfolio_id=p.portfolio_id LEFT JOIN securities s ON s.security_id=h.security_id LEFT JOIN sectors c ON c.sector_id=s.sector_id"
        ).fetchall()
        sql_rows = conn.execute(
            """SELECT p.portfolio_id, SUM(h.quantity*s.current_price), SUM(h.quantity*s.current_price*(1+CASE WHEN s.asset_type='Bond' THEN 0 WHEN c.sector_name='Technology' THEN -0.22 WHEN c.sector_name='Energy' THEN 0.11 WHEN c.sector_name='Financials' THEN -0.07 ELSE 0 END)) FROM portfolios p JOIN holdings h ON h.portfolio_id=p.portfolio_id JOIN securities s ON s.security_id=h.security_id LEFT JOIN sectors c ON c.sector_id=s.sector_id GROUP BY p.portfolio_id"""
        ).fetchall()
    oracle = defaultdict(
        lambda: {
            "before": Decimal(0),
            "after": Decimal(0),
            "equity_before": Decimal(0),
            "equity_after": Decimal(0),
            "sectors": defaultdict(lambda: [Decimal(0), Decimal(0)]),
        }
    )
    for ident, _, holding, quantity, price, asset_type, sector in raw:
        if holding is None:
            continue
        before = Decimal(str(quantity)) * Decimal(str(price))
        after = before * (1 + (SHOCKS.get(sector, Decimal(0)) if asset_type == "Stock" else 0))
        oracle[ident]["before"] += before
        oracle[ident]["after"] += after
        if asset_type == "Stock":
            oracle[ident]["equity_before"] += before
            oracle[ident]["equity_after"] += after
            oracle[ident]["sectors"][sector][0] += after
            oracle[ident]["sectors"][sector][1] += after - before
    assert len(result["portfolios"]) == result["row_count"] == 13
    assert result["source_tables"] == ["holdings", "portfolios", "securities", "sectors"]
    assert result["currency"] == "USD"
    assert {h["holding_id"] for p in result["portfolios"] for h in p["holdings"]} == {
        row[2] for row in raw if row[2] is not None
    }
    json.dumps(result, allow_nan=False)
    for portfolio in result["portfolios"]:
        ref = oracle[portfolio["portfolio_id"]]
        assert dec(portfolio["pre_portfolio_value"]) == ref["before"]
        assert dec(portfolio["post_portfolio_value"]) == ref["after"]
        assert dec(portfolio["portfolio_pnl"]) == ref["after"] - ref["before"]
        assert dec(portfolio["equity_pnl"]) == ref["equity_after"] - ref["equity_before"]
        if ref["equity_before"]:
            assert dec(portfolio["equity_return_pct"]) == pytest.approx(
                100 * (ref["equity_after"] / ref["equity_before"] - 1), abs=Decimal("1e-23")
            )
        else:
            assert portfolio["equity_return_pct"] is None
            assert portfolio["sectors"] == []
        assert len({h["holding_id"] for h in portfolio["holdings"]}) == len(portfolio["holdings"])
        assert sum((dec(h["pnl"]) for h in portfolio["holdings"]), Decimal(0)) == dec(
            portfolio["portfolio_pnl"]
        )
        for holding in portfolio["holdings"]:
            assert dec(holding["post_value"]) - dec(holding["pre_value"]) == dec(holding["pnl"])
            if holding["asset_type"] == "Bond":
                assert dec(holding["shock"]) == dec(holding["pnl"]) == 0
        assert sum((dec(s["sector_pnl"]) for s in portfolio["sectors"]), Decimal(0)) == dec(
            portfolio["equity_pnl"]
        )
        for sector in portfolio["sectors"]:
            expected_post, expected_pnl = ref["sectors"][sector["sector"]]
            assert dec(sector["post_sector_equity_value"]) == expected_post
            assert dec(sector["sector_pnl"]) == expected_pnl
            if ref["equity_after"]:
                assert dec(sector["post_equity_normalized_sector_exposure_pct"]) == pytest.approx(
                    100 * expected_post / ref["equity_after"], abs=Decimal("1e-23")
                )
            assert dec(sector["post_whole_portfolio_sector_exposure_pct"]) == pytest.approx(
                100 * expected_post / ref["after"], abs=Decimal("1e-23")
            )
        if ref["equity_after"]:
            assert sum(
                dec(s["post_equity_normalized_sector_exposure_pct"]) for s in portfolio["sectors"]
            ) == pytest.approx(Decimal(100), abs=Decimal("1e-24"))
        negative = {sector: values[1] for sector, values in ref["sectors"].items() if values[1] < 0}
        assert portfolio["top_loss_sector"] == (
            min(negative, key=negative.get) if negative else None
        )
    actual = {p["portfolio_id"]: p for p in result["portfolios"]}
    for ident, before, after in sql_rows:
        assert float(actual[ident]["pre_portfolio_value"]) == pytest.approx(before)
        assert float(actual[ident]["post_portfolio_value"]) == pytest.approx(after)
    returns = [dec(p["portfolio_return_pct"]) for p in result["portfolios"]]
    assert returns == sorted(returns)
    for field in [
        "pre_portfolio_value",
        "post_portfolio_value",
        "portfolio_pnl",
        "pre_equity_value",
        "post_equity_value",
        "equity_pnl",
    ]:
        assert dec(result["totals"][field]) == sum(
            (dec(p[field]) for p in result["portfolios"]), Decimal(0)
        )


def test_mixed_same_sector_decimal_and_two_denominators(small_db):
    result = calculate_scenario(
        small_db,
        ScenarioRequest(sector_shocks={"Technology": "-0.22", "Energy": "0.11"}, bond_shock="0.05"),
    )
    mixed = by_name(result)["Mixed Fund"]
    assert dec(mixed["pre_portfolio_value"]) == Decimal("180.52")
    assert dec(mixed["post_portfolio_value"]) == Decimal("187.6056")
    assert dec(mixed["portfolio_pnl"]) == Decimal("7.0856")
    assert dec(mixed["pre_equity_value"]) == Decimal("80.52")
    assert dec(mixed["post_equity_value"]) == Decimal("82.6056")
    tech = next(s for s in mixed["sectors"] if s["sector"] == "Technology")
    assert dec(tech["pre_sector_equity_value"]) == Decimal("20.52")
    assert dec(tech["post_sector_equity_value"]) == Decimal("16.0056")
    assert dec(tech["sector_pnl"]) == Decimal("-4.5144")
    assert dec(tech["post_equity_normalized_sector_exposure_pct"]) > dec(
        tech["post_whole_portfolio_sector_exposure_pct"]
    )
    assert mixed["top_loss_sector"] == "Technology"
    bond = by_name(result)["Bond Fund"]
    assert dec(bond["portfolio_return_pct"]) == Decimal(5)
    assert bond["equity_return_pct"] is None
    assert bond["top_loss_sector"] is None
    assert bond["sectors"] == []
    assert by_name(result)["Empty Fund"]["portfolio_return_pct"] is None
    assert result["portfolios"][-1]["portfolio_name"] == "Empty Fund"


def test_identity_scale_and_uniform_shock_metamorphic_properties(small_db):
    baseline = calculate_scenario(small_db, ScenarioRequest(sector_shocks={}))
    for p in baseline["portfolios"]:
        assert dec(p["portfolio_pnl"]) == 0
        assert p["pre_portfolio_value"] == p["post_portfolio_value"]
        assert p["top_loss_sector"] is None
    request = ScenarioRequest(
        sector_shocks=SHOCKS, unmentioned_equity_shock="0.03", bond_shock="-0.09"
    )
    before = by_name(calculate_scenario(small_db, request))
    # Write exact intended decimal inputs; SQLite REAL multiplication itself would add noise.
    with sqlite3.connect(small_db) as conn:
        rows = conn.execute("SELECT holding_id,quantity FROM holdings").fetchall()
        conn.executemany(
            "UPDATE holdings SET quantity=? WHERE holding_id=?",
            [(str(Decimal(str(q)) * 7), ident) for ident, q in rows],
        )
    after = by_name(calculate_scenario(small_db, request))
    for name in before:
        for field in ["pre_portfolio_value", "post_portfolio_value", "portfolio_pnl"]:
            assert dec(after[name][field]) == dec(before[name][field]) * 7
        for field in ["portfolio_return_pct", "equity_return_pct"]:
            assert after[name][field] == before[name][field]
    uniform = calculate_scenario(
        small_db,
        ScenarioRequest(sector_shocks={}, unmentioned_equity_shock="-0.17", bond_shock="-0.17"),
    )
    for p in uniform["portfolios"]:
        if dec(p["pre_portfolio_value"]):
            assert dec(p["portfolio_return_pct"]) == Decimal(-17)


def test_single_all_equity_extreme_loss_and_no_negative_sector(small_db):
    change(small_db, "DELETE FROM holdings WHERE holding_id<>1")
    loss = by_name(
        calculate_scenario(
            small_db,
            ScenarioRequest(sector_shocks={"technology": -1}, portfolio_filter=["Mixed Fund"]),
        )
    )
    p = loss["Mixed Fund"]
    assert dec(p["post_portfolio_value"]) == 0
    assert dec(p["portfolio_return_pct"]) == dec(p["equity_return_pct"]) == -100
    assert p["sectors"][0]["post_equity_normalized_sector_exposure_pct"] is None
    gain = by_name(
        calculate_scenario(
            small_db, ScenarioRequest(sector_shocks={"Technology": 10}, portfolio_filter=["1"])
        )
    )
    assert dec(gain["Mixed Fund"]["portfolio_return_pct"]) == 1000
    assert gain["Mixed Fund"]["top_loss_sector"] is None


def test_unmentioned_equities_receive_only_default_and_bond_losses_are_not_sector_losses(small_db):
    request = ScenarioRequest(
        sector_shocks={"Technology": "-0.22"}, unmentioned_equity_shock="0.25", bond_shock="-0.1"
    )
    mixed = by_name(calculate_scenario(small_db, request))["Mixed Fund"]
    energy = next(h for h in mixed["holdings"] if h["symbol"] == "E1")
    assert energy["shock"] == "0.25"
    assert dec(energy["post_value"]) == Decimal(75)
    for holding in mixed["holdings"]:
        if holding["asset_type"] == "Bond":
            assert holding["shock"] == "-0.1"
            assert dec(holding["post_value"]) == Decimal(90)
    bond_loss = by_name(calculate_scenario(small_db, ScenarioRequest(bond_shock="-1")))[
        "Mixed Fund"
    ]
    assert dec(bond_loss["portfolio_pnl"]) < 0
    assert bond_loss["top_loss_sector"] is None


def test_null_quantity_duplicate_holdings_and_unknown_asset_are_rejected(small_db):
    # Deliberately damaged schema bypasses importer constraints; calculator still defends its inputs.
    with sqlite3.connect(small_db) as conn:
        conn.executescript(
            "ALTER TABLE holdings RENAME TO old_holdings; CREATE TABLE holdings AS SELECT * FROM old_holdings; DROP TABLE old_holdings;"
        )
    change(small_db, "UPDATE holdings SET quantity=NULL WHERE holding_id=1")
    with pytest.raises(DataError, match="quantity"):
        calculate_scenario(small_db, ScenarioRequest())
    change(small_db, "UPDATE holdings SET quantity=2 WHERE holding_id=1")
    change(small_db, "INSERT INTO holdings SELECT * FROM holdings WHERE holding_id=1")
    with pytest.raises(DataError, match="Duplicate"):
        calculate_scenario(small_db, ScenarioRequest())
    change(small_db, "DELETE FROM holdings WHERE rowid=(SELECT MAX(rowid) FROM holdings)")
    with sqlite3.connect(small_db) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE securities SET asset_type='Derivative' WHERE security_id=1")
    with pytest.raises(DataError, match="classification"):
        calculate_scenario(small_db, ScenarioRequest())


@pytest.mark.parametrize(
    "value",
    [
        -22,
        "-1.00001",
        "10.1",
        True,
        None,
        "NaN",
        "Infinity",
        float("inf"),
        "22%",
        "__import__('os')",
        "0.0000000000000000001",
    ],
)
def test_reject_invalid_fractional_shocks(value):
    with pytest.raises(ValidationError):
        ScenarioRequest(sector_shocks={"Technology": value})
    with pytest.raises(ValidationError):
        ScenarioRequest(sector_shocks={}, bond_shock=value)


def test_request_extra_fields_labels_filters_and_mutation(small_db):
    for kwargs in [
        {"sql": "DELETE FROM holdings"},
        {"scenario_label": ""},
        {"portfolio_filter": []},
        {"portfolio_filter": [""]},
        {"sector_shocks": {"": 0}},
        {"sector_shocks": {" Technology": 0, "Technology": 1}},
    ]:
        with pytest.raises(ValidationError):
            ScenarioRequest(**{"sector_shocks": {}, **kwargs})
    request = ScenarioRequest(sector_shocks={"Technology": 0})
    request.sector_shocks["Technology"] = Decimal("NaN")
    with pytest.raises(ValidationError):
        calculate_scenario(small_db, request)


def test_unknown_ambiguous_canonical_names_and_filter_no_duplicates(small_db):
    for sectors in [{"Imaginary Sector": 0}, {"Technology": 0, "technology": 1}]:
        with pytest.raises(EntityError):
            calculate_scenario(small_db, ScenarioRequest(sector_shocks=sectors))
    for funds in [["Missing Fund"], ["Fund"], ["Mixed Fund'; DROP TABLE holdings; --"]]:
        with pytest.raises(EntityError):
            calculate_scenario(small_db, ScenarioRequest(sector_shocks={}, portfolio_filter=funds))
    result = calculate_scenario(
        small_db, ScenarioRequest(sector_shocks={}, portfolio_filter=["Mixed Fund", "1"])
    )
    assert result["row_count"] == 1
    assert result["portfolios"][0]["portfolio_name"] == "Mixed Fund"


@pytest.mark.parametrize(
    "column,value",
    [
        ("current_price", None),
        ("current_price", -1),
        ("current_price", "NaN"),
        ("current_price", "Infinity"),
        ("current_price", float("inf")),
        ("current_price", 1e100),
        ("quantity", -1),
        ("quantity", "NaN"),
        ("quantity", "Infinity"),
        ("quantity", float("inf")),
        ("quantity", 1e100),
    ],
)
def test_invalid_data_never_silently_excluded(small_db, column, value):
    table = "holdings" if column == "quantity" else "securities"
    ident = "holding_id" if column == "quantity" else "security_id"
    change(small_db, f"UPDATE {table} SET {column}=? WHERE {ident}=1", (value,))
    with pytest.raises(DataError):
        calculate_scenario(small_db, ScenarioRequest(sector_shocks={}))


@pytest.mark.parametrize(
    "sql,parameters",
    [
        ("UPDATE securities SET sector_id=NULL WHERE security_id=1", ()),
        ("UPDATE securities SET sector_id=999 WHERE security_id=1", ()),
        ("UPDATE securities SET currency=NULL WHERE security_id=1", ()),
        ("UPDATE securities SET currency='Dollars' WHERE security_id=1", ()),
        ("UPDATE securities SET currency='EUR' WHERE security_id=1", ()),
        ("UPDATE holdings SET security_id=999 WHERE holding_id=1", ()),
    ],
)
def test_invalid_classification_mapping_currency_or_orphan(small_db, sql, parameters):
    change(small_db, sql, parameters)
    with pytest.raises(DataError):
        calculate_scenario(small_db, ScenarioRequest(sector_shocks={}))


def test_zero_quantity_price_are_visible_and_undefined_returns_are_none(small_db):
    change(small_db, "UPDATE securities SET current_price=0 WHERE security_id=1")
    change(small_db, "UPDATE holdings SET quantity=0 WHERE security_id IN (2,3,4)")
    result = calculate_scenario(small_db, ScenarioRequest(sector_shocks=SHOCKS))
    assert result["warnings"]
    for p in result["portfolios"]:
        assert dec(p["pre_portfolio_value"]) == 0
        assert p["portfolio_return_pct"] is p["equity_return_pct"] is None
        assert p["top_loss_sector"] is None


def test_database_is_read_only_and_bad_database_is_public_data_error(small_db, tmp_path):
    original = small_db.read_bytes()
    calculate_scenario(small_db, ScenarioRequest(sector_shocks=SHOCKS))
    assert small_db.read_bytes() == original
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not a database")
    with pytest.raises(DataError):
        calculate_scenario(path, ScenarioRequest(sector_shocks={}))
    with pytest.raises(DataError):
        calculate_scenario(tmp_path / "missing.sqlite3", ScenarioRequest(sector_shocks={}))


def test_exact_decimal_outputs_do_not_depend_on_callers_decimal_context(small_db):
    request = ScenarioRequest(sector_shocks={"Technology": "-0.123456789012345678"})
    expected = calculate_scenario(small_db, request)
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_UP
        context.traps[Rounded] = True
        assert calculate_scenario(small_db, request) == expected
