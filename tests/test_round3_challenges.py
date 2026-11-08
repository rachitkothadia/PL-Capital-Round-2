"""Semantic aliases must preserve financial units, completeness and independently checked metadata."""

import copy
import sqlite3

import pytest

from pl_capital.challenges import (
    compare_challenge,
    load_questions,
    reference_results,
    verify_references,
)


@pytest.fixture
def references(settings):
    return reference_results(settings.data_root, settings.db_path)


ALIASES = {
    1: {
        "value_top_sector": "top_market_sector",
        "value_top_pct": "top_market_pct",
        "top_gap_pp": "gap_pct",
    },
    3: {"equity_market_value": "total_stock_value"},
    4: {"discrepancy_pp": "discrepancy_pct"},
    5: {"holdings_to_aum_ratio": "ratio", "aum_coverage_pct": "percentage_of_aum"},
    6: {"abs_discrepancy_pp": "abs_percentage_point_diff"},
    9: {"equity_value_fraction": "fraction"},
    11: {"last_close_matches_current": "matches_current"},
    12: {"longest_decline_streak": "max_len"},
    13: {"intraday_range_pct": "percentage"},
    15: {"observation_count": "obs_count"},
    16: {
        "first_var_95": "first_var",
        "last_var_95": "last_var",
        "magnitude_change": "abs_magnitude_change",
    },
    17: {"total_fees": "total_transaction_fees"},
}


@pytest.mark.parametrize("ident", list(ALIASES))
def test_unique_aliases_pass_and_numeric_changes_still_fail(settings, references, ident):
    case = load_questions(settings.data_root)[ident - 1]
    expected = references[ident]
    actual = copy.deepcopy(expected)
    actual["columns"] = [ALIASES[ident].get(name, name) for name in actual["columns"]]
    assert compare_challenge(case, actual, expected)[0] == "pass"
    numeric = next(i for i, value in enumerate(actual["rows"][0]) if type(value) in (int, float))
    actual["rows"][0][numeric] += 0.01
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_fractional_bond_share_alias_converts_once_without_magnitude_guessing(settings, references):
    case = load_questions(settings.data_root)[18]
    expected = references[19]
    actual = copy.deepcopy(expected)
    index = actual["columns"].index("bond_share_pct")
    actual["columns"][index] = "bond_share"
    for row in actual["rows"]:
        row[index] /= 100
    assert compare_challenge(case, actual, expected)[0] == "pass"
    for row in actual["rows"]:
        row[index] *= 100
    assert compare_challenge(case, actual, expected)[0] == "fail"


@pytest.mark.parametrize(
    "ident,field,table,key",
    [
        (9, "company_name", "securities", "symbol"),
        (10, "sector_description", "sectors", "sector_name"),
    ],
)
def test_optional_metadata_is_independently_enriched_and_actually_checked(
    settings, references, ident, field, table, key
):
    case = load_questions(settings.data_root)[ident - 1]
    expected = references[ident]
    with sqlite3.connect(settings.db_path) as conn:
        catalog = dict(conn.execute(f"SELECT {key},{field} FROM {table}"))
    actual = copy.deepcopy(expected)
    index = actual["columns"].index(key)
    actual["columns"].append(field)
    for row in actual["rows"]:
        row.append(catalog[row[index]])
    assert compare_challenge(case, actual, expected)[0] == "pass"
    actual["rows"][0][-1] = "Wrong source metadata"
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_metadata_does_not_mask_missing_fields_duplicates_or_bad_ranking(settings, references):
    case = load_questions(settings.data_root)[8]
    expected = references[9]
    actual = copy.deepcopy(expected)
    index = actual["columns"].index("equity_value_fraction")
    actual["columns"].pop(index)
    for row in actual["rows"]:
        row.pop(index)
    assert compare_challenge(case, actual, expected)[0] == "fail"
    actual = copy.deepcopy(expected)
    actual["rows"][1] = actual["rows"][0][:]
    assert compare_challenge(case, actual, expected)[0] == "fail"
    actual = copy.deepcopy(expected)
    actual["rows"].reverse()
    assert compare_challenge(case, actual, expected)[0] == "fail"
    actual = copy.deepcopy(expected)
    actual["columns"].append("unexplained_metric")
    for row in actual["rows"]:
        row.append(0)
    assert compare_challenge(case, actual, expected)[0] == "inconclusive"


def test_units_directions_tolerances_and_all_twenty_references_are_preserved(settings, references):
    assert verify_references(settings.data_root, settings.db_path)["passed"] == 20
    for case in load_questions(settings.data_root):
        expected = references[case["id"]]
        assert compare_challenge(case, expected, expected)[0] == "pass"
    case = load_questions(settings.data_root)[3]
    expected = references[4]
    actual = copy.deepcopy(expected)
    index = actual["columns"].index("discrepancy_pp")
    actual["columns"][index] = "discrepancy_pct"
    for row in actual["rows"]:
        row[index] = abs(row[index])
    assert compare_challenge(case, actual, expected)[0] == "fail"
    actual = copy.deepcopy(expected)
    actual["rows"][0][index] += 1e-8
    assert compare_challenge(case, actual, expected)[0] == "pass"
    actual["rows"][0][index] += 1e-4
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_ambiguous_competing_aliases_remain_inconclusive(settings, references):
    case = load_questions(settings.data_root)[8]
    expected = references[9]
    actual = copy.deepcopy(expected)
    actual["columns"].append("fraction")
    for row in actual["rows"]:
        row.append(row[actual["columns"].index("equity_value_fraction")])
    assert compare_challenge(case, actual, expected)[0] == "inconclusive"


def test_sql_metadata_enrichment_is_checked_against_independent_python(settings, monkeypatch):
    from pl_capital import challenges

    original = challenges._sql_optional_columns

    def corrupt_metadata(connection, result):
        optional = original(connection, result)
        if optional.get("company_name"):
            optional["company_name"][0] = "Incorrect oracle company"
        return optional

    monkeypatch.setattr(challenges, "_sql_optional_columns", corrupt_metadata)
    result = verify_references(settings.data_root, settings.db_path)
    assert result["passed"] < 20
    assert next(q for q in result["questions"] if q["id"] == 9)["status"] == "fail"


@pytest.mark.parametrize(
    "ident,aliases",
    [
        (
            1,
            {
                "recorded_top_sector": "weight_winner",
                "recorded_top_pct": "weight_winner_pct",
                "value_top_sector": "market_winner",
                "value_top_pct": "market_winner_pct",
                "top_gap_pp": "gap_pct_points",
            },
        ),
        (7, {"portfolio_a": "name_a", "portfolio_b": "name_b"}),
        (9, {"equity_value_fraction": "fraction_of_total"}),
        (11, {"last_close_matches_current": "price_match"}),
        (12, {"start_date": "interval_start", "end_date": "interval_end"}),
    ],
)
def test_fresh_run_unique_aliases_keep_values_signs_and_complete_rows(
    settings, references, ident, aliases
):
    case = load_questions(settings.data_root)[ident - 1]
    expected = references[ident]
    actual = copy.deepcopy(expected)
    actual["columns"] = [aliases.get(name, name) for name in actual["columns"]]
    assert compare_challenge(case, actual, expected)[0] == "pass"
    actual["rows"].pop()
    actual["row_count"] -= 1
    assert compare_challenge(case, actual, expected)[0] == "fail"
    if ident == 1:
        actual = copy.deepcopy(expected)
        index = actual["columns"].index("top_gap_pp")
        actual["columns"][index] = "gap_pct_points"
        actual["rows"][0][index] *= -1
        assert compare_challenge(case, actual, expected)[0] == "fail"


def test_fractional_equity_weight_aliases_convert_once_and_keep_denominators_required(
    settings, references
):
    case = load_questions(settings.data_root)[5]
    expected = references[6]
    actual = copy.deepcopy(expected)
    for canonical, alias in [
        ("market_value_pct", "calculated_weight"),
        ("recorded_equity_pct", "normalized_recorded_weight"),
    ]:
        index = actual["columns"].index(canonical)
        actual["columns"][index] = alias
        for row in actual["rows"]:
            row[index] /= 100
    assert compare_challenge(case, actual, expected)[0] == "pass"
    for alias in ["calculated_weight", "normalized_recorded_weight"]:
        bad = copy.deepcopy(actual)
        index = bad["columns"].index(alias)
        for row in bad["rows"]:
            row[index] *= 100
        assert compare_challenge(case, bad, expected)[0] == "fail"
    index = actual["columns"].index("equity_market_value")
    actual["columns"].pop(index)
    for row in actual["rows"]:
        row.pop(index)
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_is_current_match_alias_validates_the_flag_instead_of_ignoring_it(settings, references):
    case = load_questions(settings.data_root)[10]
    expected = references[11]
    actual = copy.deepcopy(expected)
    index = actual["columns"].index("last_close_matches_current")
    actual["columns"][index] = "is_current_match"
    assert compare_challenge(case, actual, expected)[0] == "pass"
    actual["rows"][0][index] = 1 - actual["rows"][0][index]
    assert compare_challenge(case, actual, expected)[0] == "fail"


@pytest.fixture
def tall_risk_case(settings):
    # Create genuine High/Low overlap so tests cannot pass merely because source results are empty.
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE portfolios SET target_risk_level='Low' WHERE portfolio_id=1")
        cursor = conn.execute("""WITH groups AS (
            SELECT s.symbol,p.target_risk_level,COUNT(DISTINCT h.portfolio_id) AS distinct_portfolios,
                SUM(h.quantity) AS total_quantity,SUM(h.quantity*s.current_price) AS total_market_value
            FROM holdings h JOIN securities s USING(security_id) JOIN portfolios p USING(portfolio_id)
            WHERE s.asset_type='Stock' AND p.target_risk_level IN ('High','Low')
            GROUP BY s.symbol,p.target_risk_level), overlap AS (
            SELECT symbol FROM groups GROUP BY symbol HAVING COUNT(*)=2)
            SELECT g.* FROM groups g JOIN overlap USING(symbol) ORDER BY g.symbol,g.target_risk_level""")
        actual = {
            "columns": [item[0] for item in cursor.description],
            "rows": [list(row) for row in cursor],
            "truncated": False,
        }
    actual["row_count"] = len(actual["rows"])
    expected = reference_results(settings.data_root, settings.db_path, ids=[8])[8]
    assert expected["rows"] and actual["rows"]
    assert verify_references(settings.data_root, settings.db_path)["passed"] == 20
    return load_questions(settings.data_root)[7], actual, expected


def test_complete_tall_risk_layout_matches_independent_wide_reference(tall_risk_case):
    case, actual, expected = tall_risk_case
    assert compare_challenge(case, actual, expected)[0] == "pass"
    actual["rows"].reverse()
    assert compare_challenge(case, actual, expected)[0] == "pass"


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_value",
        "wrong_unit",
        "missing_group",
        "duplicate_group",
        "unknown_risk",
        "missing_symbol_pair",
    ],
)
def test_tall_risk_layout_rejects_wrong_or_incomplete_measures(tall_risk_case, mutation):
    case, actual, expected = tall_risk_case
    if mutation == "wrong_value":
        actual["rows"][0][2] += 1
    elif mutation == "wrong_unit":
        actual["rows"][0][4] /= 100
    elif mutation == "missing_group":
        actual["rows"].pop()
    elif mutation == "duplicate_group":
        actual["rows"].append(actual["rows"][0][:])
    elif mutation == "unknown_risk":
        actual["rows"][0][1] = "Moderate"
    else:
        actual["rows"] = actual["rows"][2:]
    actual["row_count"] = len(actual["rows"])
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_tall_risk_layout_does_not_ignore_extras_or_missing_columns(tall_risk_case):
    case, actual, expected = tall_risk_case
    unknown = copy.deepcopy(actual)
    unknown["columns"].append("unverified_metadata")
    for row in unknown["rows"]:
        row.append("anything")
    assert compare_challenge(case, unknown, expected)[0] == "inconclusive"
    actual["columns"].pop()
    for row in actual["rows"]:
        row.pop()
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_tall_risk_optional_company_metadata_is_checked_for_both_groups_and_source(tall_risk_case):
    case, actual, expected = tall_risk_case
    names = {
        row[expected["columns"].index("symbol")]: row[expected["columns"].index("company_name")]
        for row in expected["rows"]
    }
    actual["columns"].append("company_name")
    for row in actual["rows"]:
        row.append(names[row[0]])
    assert compare_challenge(case, actual, expected)[0] == "pass"
    wrong_group = copy.deepcopy(actual)
    wrong_group["rows"][0][-1] = "Wrong group company"
    assert compare_challenge(case, wrong_group, expected)[0] == "fail"
    for row in actual["rows"]:
        row[-1] = "Consistent but wrong company"
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_tall_empty_risk_layout_only_passes_when_complete_schema_and_population_match(
    settings, references
):
    case = load_questions(settings.data_root)[7]
    actual = {
        "columns": [
            "symbol",
            "target_risk_level",
            "distinct_portfolios",
            "total_quantity",
            "total_market_value",
        ],
        "rows": [],
        "row_count": 0,
    }
    assert references[8]["rows"] == []
    assert compare_challenge(case, actual, references[8])[0] == "pass"
    actual["columns"].append("unknown_extra")
    assert compare_challenge(case, actual, references[8])[0] == "inconclusive"


def test_reported_aum_alias_preserves_value_checks(settings, references):
    case = load_questions(settings.data_root)[4]
    expected = references[5]
    actual = copy.deepcopy(expected)
    index = actual["columns"].index("total_aum")
    actual["columns"][index] = "reported_aum"
    assert compare_challenge(case, actual, expected)[0] == "pass"
    actual["rows"][0][index] += 1
    assert compare_challenge(case, actual, expected)[0] == "fail"


@pytest.mark.parametrize(
    "ident,field,alias",
    [
        (15, "nav_change_pct", "pct_nav_change"),
        (15, "nav_change", "abs_nav_change"),
        (7, "portfolio_a", "p1_name"),
        (7, "portfolio_b", "p2_name"),
        (11, "last_close_matches_current", "is_last_close_current"),
    ],
)
def test_explicit_identifier_and_price_match_aliases_still_reject_wrong_values(
    settings, references, ident, field, alias
):
    expected = references[ident]
    actual = copy.deepcopy(expected)
    index = actual["columns"].index(field)
    actual["columns"][index] = alias
    case = load_questions(settings.data_root)[ident - 1]
    assert compare_challenge(case, actual, expected)[0] == "pass"
    value = actual["rows"][0][index]
    actual["rows"][0][index] = "Wrong portfolio" if isinstance(value, str) else 1 - value
    assert compare_challenge(case, actual, expected)[0] == "fail"
