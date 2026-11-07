import pytest


def test_genuine_stock_exposures_and_aliases(db_path):
    from pl_capital.exposure import calculate

    tech = calculate(db_path, "Tech Innovation Fund")
    assert [(r.sector, r.whole_portfolio_pct) for r in tech.sectors] == [("Technology", 100)]
    international = calculate(db_path, "international equity")
    assert {r.sector: r.whole_portfolio_pct for r in international.sectors} == {
        "Technology": 36,
        "Energy": 38,
        "Automotive": 15,
        "Consumer Staples": 11,
    }
    assert calculate(db_path, str(international.portfolio_id)) == international


def test_mixed_portfolio_has_two_denominators(db_path):
    from pl_capital.exposure import calculate

    value = calculate(db_path, "Balanced Portfolio")
    assert value.bond_exclusion_count > 0
    assert float(value.equity_weight_total) < 1
    assert sum(r.whole_portfolio_pct for r in value.sectors) < 100
    assert sum(r.equity_normalized_pct for r in value.sectors) == pytest.approx(100, abs=1e-5)


def test_no_equity_and_missing_ambiguous_entities(db_path):
    from pl_capital.errors import EntityError
    from pl_capital.exposure import calculate

    assert calculate(db_path, "Fixed Income Plus").status == "no_equity_holdings"
    assert calculate(db_path, "Total Bond Market Index Fund").sectors == []
    for name in ["nonexistent fund", "international", "total"]:
        with pytest.raises(EntityError):
            calculate(db_path, name)
