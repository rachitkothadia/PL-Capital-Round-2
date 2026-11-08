"""Small independent datasets exercise metric definitions without evaluation fixtures."""

import sqlite3

import pytest

from pl_capital.errors import QueryError
from pl_capital.metric_validation import verify_advanced_metrics

WINNERS = "For each portfolio identify the largest stock sector twice, by recorded weight and by market value. Return portfolios where the winning sector differs."
STREAKS = "Find stock symbols with at least three consecutive closing-price declines; show each longest decline streak and its start and end dates."
AUM = "For every portfolio, compare recorded total_aum with SUM(quantity * current_price). Show the dollar difference, ratio, percentage of AUM represented by listed holdings, and the five largest mismatches. Clearly distinguish AUM from holdings market value."
SHARES = "Within each portfolio, calculate each equity holding's share of stock market value, compare it with current_weight normalized over all equity weights, and return the ten largest absolute percentage-point discrepancies, including the security and portfolio names."


@pytest.fixture
def metric_db(tmp_path):
    path = tmp_path / "metrics.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE portfolios(portfolio_id INTEGER,portfolio_name TEXT,total_aum REAL);
            CREATE TABLE sectors(sector_id INTEGER,sector_name TEXT);
            CREATE TABLE securities(security_id INTEGER,symbol TEXT,company_name TEXT,asset_type TEXT,sector_id INTEGER,current_price REAL);
            CREATE TABLE holdings(portfolio_id INTEGER,security_id INTEGER,current_weight REAL,quantity REAL);
            CREATE TABLE historical_prices(security_id INTEGER,price_date TEXT,close_price REAL);
            INSERT INTO portfolios VALUES(1,'Mismatch',999999),(2,'Same',999999),(3,'Tie',999999),(4,'Bond Only',999999),(5,'Negative Gap',999999);
            INSERT INTO sectors VALUES(1,'Alpha'),(2,'Beta');
            INSERT INTO securities VALUES(1,'AA','Acme Inc.','Stock',1,10),(2,'BB','Beryl Corporation','Stock',2,10),(3,'CC','Cobalt Inc.','Stock',1,10),(4,'BD','Bond Asset','Bond',NULL,100);
            INSERT INTO holdings VALUES(1,1,12,1),(1,2,8,4),(1,4,80,100),(2,1,70,7),(2,2,30,3),(3,1,50,1),(3,2,50,4),(4,4,100,100),(5,1,90,4),(5,2,10,6);
        """)
        prices = [
            (1, "2023-01-01", 10),
            (1, "2023-01-03", 9),
            (1, "2023-01-08", 8),
            (1, "2023-01-09", 7),
            (1, "2023-01-10", 8),
            (1, "2023-01-13", 7),
            (1, "2023-01-20", 6),
            (1, "2023-01-22", 5),
            (2, "2023-01-01", 10),
            (2, "2023-01-03", 9),
            (2, "2023-01-08", 8),
            (2, "2023-01-09", 7),
            (2, "2023-01-10", 6),
            (3, "2023-01-01", 10),
            (3, "2023-01-03", 9),
            (3, "2023-01-08", 9),
            (3, "2023-01-09", 8),
            (3, "2023-01-10", 7),
            (4, "2023-01-01", 10),
            (4, "2023-01-03", 9),
            (4, "2023-01-08", 8),
            (4, "2023-01-09", 7),
            (4, "2023-01-10", 6),
        ]
        conn.executemany("INSERT INTO historical_prices VALUES(?,?,?)", prices)
    return path


def winning_result():
    return dict(
        columns=[
            "portfolio_name",
            "recorded_top_sector",
            "recorded_top_pct",
            "value_top_sector",
            "value_top_pct",
            "top_gap_pp",
        ],
        rows=[
            ["Mismatch", "Alpha", 60, "Beta", 80, 20],
            ["Tie", "Alpha", 50, "Beta", 80, 30],
            ["Negative Gap", "Alpha", 90, "Beta", 60, -30],
        ],
    )


def streak_result(threshold=3):
    rows = [["AA", 3, "2023-01-01", "2023-01-09"], ["BB", 4, "2023-01-01", "2023-01-10"]]
    return dict(
        columns=["symbol", "longest_decline_streak", "start_date", "end_date"],
        rows=[r for r in rows if r[1] >= threshold],
    )


def test_winner_percentages_use_own_stock_denominators_and_signed_gap(metric_db):
    assert verify_advanced_metrics(metric_db, WINNERS, winning_result()) == ["stock_sector_winners"]


@pytest.mark.parametrize("wrong_gap", [30, -50, 50])
def test_correct_looking_winners_with_wrong_gap_are_rejected(metric_db, wrong_gap):
    result = winning_result()
    result["rows"][2][-1] = wrong_gap
    with pytest.raises(QueryError, match="top_gap_pp=value_top_pct-recorded_top_pct"):
        verify_advanced_metrics(metric_db, WINNERS, result)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "nonqualifying", "wrong_tie", "wrong_denominator"]
)
def test_winner_population_ties_and_denominators(metric_db, change):
    result = winning_result()
    if change == "missing":
        result["rows"].pop()
    elif change == "duplicate":
        result["rows"].append(result["rows"][0])
    elif change == "nonqualifying":
        result["rows"].append(["Same", "Alpha", 70, "Alpha", 70, 0])
    elif change == "wrong_tie":
        result["rows"][1][1] = "Beta"
    else:
        result["rows"][0][2] = 12
    with pytest.raises(QueryError):
        verify_advanced_metrics(metric_db, WINNERS, result)


@pytest.mark.parametrize(
    ("token", "threshold"), [("three", 3), ("four", 4), ("3", 3), ("4", 4), ("five", 5), ("5", 5)]
)
def test_observed_declines_thresholds_and_empty_population(metric_db, token, threshold):
    question = STREAKS.replace("three", token)
    assert verify_advanced_metrics(metric_db, question, streak_result(threshold)) == [
        "observed_close_decline_streaks"
    ]


def test_incorrect_empty_decline_result_is_rejected(metric_db):
    result = streak_result()
    result["rows"] = []
    with pytest.raises(QueryError, match="population"):
        verify_advanced_metrics(metric_db, STREAKS, result)


@pytest.mark.parametrize(
    "change", ["late_tie", "wrong_start", "observation_count", "equal_break", "bond", "duplicate"]
)
def test_decline_run_boundaries_ties_and_stock_population(metric_db, change):
    result = streak_result()
    if change == "late_tie":
        result["rows"][0][2:] = ["2023-01-10", "2023-01-22"]
    elif change == "wrong_start":
        result["rows"][0][2] = "2023-01-03"
    elif change == "observation_count":
        result["rows"][0][1] = 4
    elif change == "equal_break":
        result["rows"].append(["CC", 4, "2023-01-01", "2023-01-10"])
    elif change == "bond":
        result["rows"].append(["BD", 4, "2023-01-01", "2023-01-10"])
    else:
        result["rows"].append(result["rows"][0])
    with pytest.raises(QueryError, match="observed|Observed"):
        verify_advanced_metrics(metric_db, STREAKS, result)


def test_reasonable_streak_aliases_are_accepted(metric_db):
    result = streak_result()
    result["columns"] = ["stock_symbol", "max_streak", "streak_start_date", "streak_end_date"]
    assert verify_advanced_metrics(metric_db, STREAKS, result)


@pytest.mark.parametrize("phrase", ["close-to-close", "closing-to-closing"])
def test_observed_close_to_close_phrasing_runs_validation(metric_db, phrase):
    question = (
        f"List stock symbols with at least three consecutive observed {phrase} declines. "
        "Show the longest decline streak and its interval start and end; break ties by earliest start."
    )
    result = streak_result()
    result["columns"] = ["symbol", "longest_decline_streak", "interval_start", "interval_end"]
    assert verify_advanced_metrics(metric_db, question, result) == [
        "observed_close_decline_streaks"
    ]
    result["rows"] = []
    with pytest.raises(QueryError, match="population"):
        verify_advanced_metrics(metric_db, question, result)


def test_winning_percentages_preserve_full_precision(metric_db):
    result = winning_result()
    result["rows"][0][2] += 0.00001
    with pytest.raises(QueryError, match="percentage"):
        verify_advanced_metrics(metric_db, WINNERS, result)


@pytest.mark.parametrize(
    "question",
    [
        "How many portfolios are there?",
        "Show all stock prices",
        "Find stocks with consecutive closing declines",
        "Find stock symbols with at least zero consecutive closing-price declines",
        "Find stock symbols with at least three consecutive closing-price declines since 2023-01-01",
        "Find AA stock symbols with at least three consecutive closing-price declines",
        "Find XYZ stocks with at least three consecutive closing-price declines",
        "Find stocks with at least three consecutive closing-price declines for XYZ",
        "Find Acme stock symbols with at least three consecutive closing-price declines",
        "Find Alpha sector stock symbols with at least three consecutive closing-price declines",
        "Find stocks with at least three consecutive closing-price declines, only in the US",
    ],
)
def test_irrelevant_ambiguous_or_filtered_questions_skip(metric_db, question):
    assert verify_advanced_metrics(metric_db, question, {}) == []


def test_validation_never_mutates_database_or_result(metric_db):
    before = metric_db.read_bytes()
    winners, streaks = winning_result(), streak_result()
    expected_winners, expected_streaks = winning_result(), streak_result()
    verify_advanced_metrics(metric_db, WINNERS, winners)
    verify_advanced_metrics(metric_db, STREAKS, streaks)
    assert metric_db.read_bytes() == before
    assert winners == expected_winners
    assert streaks == expected_streaks


def aum_result():
    rows = []
    for rank, (name, value) in enumerate(
        [
            ("Tie", 50),
            ("Negative Gap", 100),
            ("Same", 100),
            ("Bond Only", 10000),
            ("Mismatch", 10050),
        ],
        start=1,
    ):
        rows.append(
            [name, 999999, value, 999999 - value, value / 999999, 100 * value / 999999, rank, 1]
        )
    return dict(
        columns=[
            "portfolio_name",
            "total_aum",
            "holdings_market_value",
            "dollar_difference",
            "ratio",
            "aum_percentage_represented",
            "mismatch_rank",
            "is_top_five",
        ],
        rows=rows,
    )


def share_result(count=10):
    # Hand calculations from the independent tiny fixture: own-stock denominators.
    rows = [
        ["Mismatch", "AA", "Acme Inc.", 50, 20, 20, 60, -40, 40],
        ["Mismatch", "BB", "Beryl Corporation", 50, 20, 80, 40, 40, 40],
        ["Negative Gap", "AA", "Acme Inc.", 100, 100, 40, 90, -50, 50],
        ["Negative Gap", "BB", "Beryl Corporation", 100, 100, 60, 10, 50, 50],
        ["Same", "AA", "Acme Inc.", 100, 100, 70, 70, 0, 0],
        ["Same", "BB", "Beryl Corporation", 100, 100, 30, 30, 0, 0],
        ["Tie", "AA", "Acme Inc.", 50, 100, 20, 50, -30, 30],
        ["Tie", "BB", "Beryl Corporation", 50, 100, 80, 50, 30, 30],
    ]
    rows.sort(key=lambda row: (-row[-1], row[0], row[1]))
    return dict(
        columns=[
            "portfolio_name",
            "symbol",
            "company_name",
            "equity_market_value",
            "equity_weight_total",
            "market_value_pct",
            "recorded_equity_pct",
            "discrepancy_pp",
            "abs_discrepancy_pp",
        ],
        rows=rows[:count],
    )


def test_aum_coverage_values_all_portfolios_and_mismatch_ranking(metric_db):
    assert verify_advanced_metrics(metric_db, AUM, aum_result()) == ["aum_holdings_comparison"]


def test_generic_aum_difference_requires_aum_minus_holdings(metric_db):
    result = aum_result()
    result["rows"][0][3] *= -1
    with pytest.raises(QueryError, match="AUM minus holdings"):
        verify_advanced_metrics(metric_db, AUM, result)


def test_explicit_reverse_aum_difference_is_verified_by_its_label(metric_db):
    result = aum_result()
    result["columns"][3] = "holdings_minus_aum"
    for row in result["rows"]:
        row[3] *= -1
    assert verify_advanced_metrics(metric_db, AUM, result)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "ratio", "coverage", "rank", "order", "flag", "value"]
)
def test_aum_invalid_population_values_and_optional_rank_are_rejected(metric_db, change):
    result = aum_result()
    if change == "missing":
        result["rows"].pop()
    elif change == "duplicate":
        result["rows"].append(result["rows"][0])
    elif change == "order":
        result["rows"].reverse()
    else:
        column = {"ratio": 4, "coverage": 5, "rank": 6, "flag": 7, "value": 2}[change]
        result["rows"][0][column] = 0
    with pytest.raises(QueryError):
        verify_advanced_metrics(metric_db, AUM, result)


def test_aum_zero_aum_and_no_holdings_remain_in_population(metric_db):
    with sqlite3.connect(metric_db) as conn:
        conn.execute("INSERT INTO portfolios VALUES(6,'Empty',0)")
    result = aum_result()
    result["rows"].append(["Empty", 0, 0, 0, None, None, 6, 0])
    assert verify_advanced_metrics(metric_db, AUM, result)


@pytest.mark.parametrize(("word", "count"), [("ten", 10), ("10", 10), ("three", 3), ("3", 3)])
def test_stock_share_top_n_uses_both_whole_equity_denominators(metric_db, word, count):
    assert verify_advanced_metrics(metric_db, SHARES.replace("ten", word), share_result(count)) == [
        "equity_holding_share_discrepancies"
    ]


@pytest.mark.parametrize(
    "change",
    [
        "holding_as_denominator",
        "wrong_weight_denominator",
        "sign",
        "abs",
        "percentage",
        "tie",
        "missing",
        "duplicate",
        "name",
    ],
)
def test_stock_share_incorrect_values_and_population_are_rejected(metric_db, change):
    result = share_result()
    if change == "holding_as_denominator":
        result["rows"][0][3] = 40  # Individual holding value, instead of portfolio equity value100.
    elif change == "wrong_weight_denominator":
        result["rows"][0][4] = 90
    elif change == "sign":
        result["rows"][0][-2] *= -1
    elif change == "abs":
        result["rows"][0][-1] *= -1
    elif change == "percentage":
        result["rows"][0][5] = 0.4
    elif change == "tie":
        result["rows"][0], result["rows"][1] = result["rows"][1], result["rows"][0]
    elif change == "missing":
        result["rows"].pop()
    elif change == "duplicate":
        result["rows"].append(result["rows"][0])
    else:
        result["rows"][0][2] = "Invented company"
    with pytest.raises(QueryError):
        verify_advanced_metrics(metric_db, SHARES, result)


def test_optional_raw_stock_holding_values_are_verified(metric_db):
    result = share_result(3)
    result["columns"].extend(["holding_market_value", "current_weight"])
    result["rows"][0].extend([40, 90])
    result["rows"][1].extend([60, 10])
    result["rows"][2].extend([10, 12])
    assert verify_advanced_metrics(metric_db, SHARES.replace("ten", "three"), result)
    result["rows"][2][-1] = 80
    with pytest.raises(QueryError):
        verify_advanced_metrics(metric_db, SHARES.replace("ten", "three"), result)


def test_stock_shares_exclude_undefined_zero_denominators(metric_db):
    with sqlite3.connect(metric_db) as conn:
        conn.execute("INSERT INTO portfolios VALUES(6,'Zero Stock Denominator',0)")
        conn.execute("INSERT INTO holdings VALUES(6,1,0,0)")
    assert verify_advanced_metrics(metric_db, SHARES, share_result())


@pytest.mark.parametrize(
    "question",
    [
        AUM.replace("every portfolio", "every active portfolio"),
        AUM + " Only include Mismatch.",
        SHARES + " Only include Technology.",
        SHARES.replace("ten largest", "largest"),
        SHARES + " For Acme.",
    ],
)
def test_aum_and_stock_share_filters_or_ambiguous_limits_skip(metric_db, question):
    assert verify_advanced_metrics(metric_db, question, {}) == []


def test_new_comparison_checks_do_not_mutate_sources_or_results(metric_db):
    before = metric_db.read_bytes()
    aum, shares = aum_result(), share_result()
    verify_advanced_metrics(metric_db, AUM, aum)
    verify_advanced_metrics(metric_db, SHARES, shares)
    assert aum == aum_result() and shares == share_result()
    assert metric_db.read_bytes() == before
