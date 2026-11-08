import copy
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from pl_capital.models import Answer

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_preserves_all_twenty_exact_question_bodies():
    from pl_capital.challenges import load_questions

    cases = load_questions(ROOT)
    bodies = [case["question"] for case in cases]
    assert len(cases) == 20
    # Pin the supplied exact wording even on CI, where local prompt files are ignored.
    assert hashlib.sha256(json.dumps(bodies, ensure_ascii=False).encode()).hexdigest() == "d86fc4d6bd19896b03e6d93e7fa2d39cc1f0e34cb6c997f4fb9f2c6b2debeed2"
    source_path = ROOT / "Prompts/PL_Capital_20_Advanced_Test_Questions.md"
    if source_path.exists():
        original = re.findall(r"^\d+\. \*\*[^\n]+?\*\* (.+)$", source_path.read_text(), re.M)
        assert bodies == original
    assert [case["id"] for case in cases] == list(range(1, 21))
    for case in cases:
        assert all(
            case[field]
            for field in (
                "category",
                "why_tricky",
                "required_tables",
                "expected_shape",
                "assumptions",
                "reference_sql",
                "required_columns",
            )
        )
        assert case["agent_status"] == "not_run"
        assert case["question"] in (ROOT / "docs/advanced-test-questions.md").read_text()


def test_all_reference_sql_agrees_with_independent_python(settings):
    from pl_capital.challenges import verify_references

    report = verify_references(settings.data_root, settings.db_path)
    assert report["mode"] == "reference-only; no agent or Gemini calls"
    assert report["passed"] == report["total"] == 20
    assert all(item["status"] == "pass" for item in report["questions"])
    results = {item["id"]: item["reference_result"] for item in report["questions"]}
    aum = results[5]
    rank = aum["columns"].index("mismatch_rank")
    flag = aum["columns"].index("is_top_five")
    assert len(aum["rows"]) == 13
    assert [row[rank] for row in aum["rows"]] == list(range(1, 14))
    assert sum(row[flag] for row in aum["rows"]) == 5
    extremes = results[11]
    assert len(extremes["rows"]) == 10
    assert [row[0] for row in extremes["rows"]].count("best") == 5
    assert [row[0] for row in extremes["rows"]].count("worst") == 5
    assert len(results[14]["rows"]) == 4
    assert results[20]["rows"] == []


def test_four_close_streak_boundaries_are_observation_based(settings):
    from pl_capital.challenges import reference_results

    streaks = reference_results(settings.data_root, settings.db_path, ids=[12])[12]
    with closing(sqlite3.connect(settings.db_path)) as conn:
        for symbol, declines, start, end, count in streaks["rows"]:
            observations = conn.execute(
                """SELECT hp.price_date,hp.close_price FROM historical_prices hp
                JOIN securities s USING(security_id) WHERE s.symbol=? AND hp.price_date BETWEEN ? AND ?
                ORDER BY hp.price_date""",
                (symbol, start, end),
            ).fetchall()
            assert len(observations) == count == declines + 1
            assert declines >= 3
            assert all(
                right[1] < left[1]
                for left, right in zip(observations, observations[1:], strict=False)
            )


def test_negative_var_direction_is_not_reversed(settings):
    from pl_capital.challenges import reference_results

    result = reference_results(settings.data_root, settings.db_path, ids=[16])[16]
    for row in result["rows"]:
        values = dict(zip(result["columns"], row, strict=True))
        assert values["signed_change"] == pytest.approx(
            values["last_var_95"] - values["first_var_95"]
        )
        assert values["magnitude_change"] == pytest.approx(
            abs(values["last_var_95"]) - abs(values["first_var_95"])
        )
        if values["signed_change"] > 0:
            assert values["signed_direction"] == "less negative"
            assert values["magnitude_direction"] == "decreased"


class MockReferenceAgent:
    """Tests evaluator mechanics only; this is never reported as a live agent."""

    live = False

    def __init__(self, settings):
        from pl_capital.challenges import load_questions, reference_results

        self.settings = settings
        self.cases = {case["question"]: case for case in load_questions(settings.data_root)}
        self.results = reference_results(settings.data_root, settings.db_path)
        self.calls = []
        self.resets = 0

    def reset_context(self):
        self.resets += 1

    def answer_question(self, question):
        self.calls.append(question)
        case = self.cases[question]
        return Answer(
            intent="sql_query",
            tool="sql_query",
            sql=case["reference_sql"],
            result=copy.deepcopy(self.results[case["id"]]),
            message="Offline mocked evaluator test",
        )


def test_all_twenty_actual_calls_and_offline_label(settings, tmp_path):
    from pl_capital.challenges import evaluate_challenges

    agent = MockReferenceAgent(settings)
    output = tmp_path / "advanced.json"
    report = evaluate_challenges(agent, live=False, report=output)
    assert len(agent.calls) == agent.resets == 20
    assert report["mode"] == "offline test (mocked)"
    assert report["counts"] == {
        "pass": 20,
        "fail": 0,
        "unsupported": 0,
        "inconclusive": 0,
        "not_run": 0,
    }
    assert json.loads(output.read_text())["counts"]["pass"] == 20
    assert "test-key" not in output.read_text()
    if os.name != "nt":
        assert not output.stat().st_mode & 0o077


def test_selection_and_bounded_run_leave_every_other_case_not_run(settings):
    from pl_capital.challenges import evaluate_challenges

    agent = MockReferenceAgent(settings)
    report = evaluate_challenges(agent, live=False, ids=[1, 20], max_questions=1)
    assert len(agent.calls) == 1
    assert report["counts"]["pass"] == 1
    assert report["counts"]["not_run"] == 19
    assert len(report["questions"]) == report["total"] == 20


@pytest.mark.parametrize(
    "ids,maximum", [([0], 20), ([21], 20), ([1, 1], 20), ([True], 20), (None, 21), (None, -1)]
)
def test_invalid_run_bounds_are_rejected(settings, ids, maximum):
    from pl_capital.challenges import evaluate_challenges
    from pl_capital.errors import ConfigurationError

    with pytest.raises(ConfigurationError):
        evaluate_challenges(
            MockReferenceAgent(settings), live=False, ids=ids, max_questions=maximum
        )


def test_mock_cannot_be_labeled_live(settings):
    from pl_capital.challenges import evaluate_challenges
    from pl_capital.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="real Gemini"):
        evaluate_challenges(MockReferenceAgent(settings))


def test_semantic_aliases_and_reordered_columns_match(settings):
    from pl_capital.challenges import compare_challenge, load_questions, reference_results

    case = load_questions(settings.data_root)[8]
    expected = reference_results(settings.data_root, settings.db_path, ids=[9])[9]
    actual = copy.deepcopy(expected)
    actual["columns"] = [
        "equity_fraction" if name == "equity_value_fraction" else name for name in actual["columns"]
    ]
    actual["columns"].reverse()
    actual["rows"] = [list(reversed(row)) for row in actual["rows"]]
    status, _ = compare_challenge(case, actual, expected)
    assert status == "pass"


def test_unknown_shape_is_inconclusive_and_real_value_error_is_fail(settings):
    from pl_capital.challenges import compare_challenge, load_questions, reference_results

    case = load_questions(settings.data_root)[8]
    expected = reference_results(settings.data_root, settings.db_path, ids=[9])[9]
    actual = copy.deepcopy(expected)
    actual["columns"] = [f"unknown_{i}" for i in range(len(actual["columns"]))]
    assert compare_challenge(case, actual, expected)[0] == "inconclusive"
    actual = copy.deepcopy(expected)
    actual["rows"][0][actual["columns"].index("equity_value_fraction")] += 0.001
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_fail_unsupported_and_provider_outage_are_distinct(settings):
    from pl_capital.challenges import evaluate_challenges

    class LimitedAgent(MockReferenceAgent):
        def answer_question(self, question):
            self.calls.append(question)
            if len(self.calls) == 1:
                return Answer(
                    intent="out_of_scope", message="This compound analysis is not supported."
                )
            if len(self.calls) == 2:
                return Answer(error="Gemini connection failed after bounded retries.")
            return Answer(
                intent="sql_query", tool="sql_query", error="SQL references an unknown column."
            )

    report = evaluate_challenges(LimitedAgent(settings), live=False, ids=[1, 2, 3])
    assert report["counts"] == {
        "pass": 0,
        "fail": 1,
        "unsupported": 1,
        "inconclusive": 1,
        "not_run": 17,
    }


def test_equal_overlap_scores_accept_any_tie_order_and_pair_orientation(settings):
    from pl_capital.challenges import compare_challenge, load_questions, reference_results

    case = load_questions(settings.data_root)[6]
    expected = reference_results(settings.data_root, settings.db_path, ids=[7])[7]
    actual = copy.deepcopy(expected)
    score = actual["columns"].index("jaccard_similarity")
    groups = {}
    for row in actual["rows"]:
        groups.setdefault(row[score], []).append(row)
    assert any(len(rows) > 1 for rows in groups.values())
    actual["rows"] = [row for rows in groups.values() for row in reversed(rows)]
    assert compare_challenge(case, actual, expected)[0] == "pass"
    for row in actual["rows"]:
        row[0], row[1] = row[1], row[0]
        row[2], row[3] = row[3], row[2]
    assert compare_challenge(case, actual, expected)[0] == "pass"


def test_overlap_ids_are_valid_identity_and_wrong_values_still_fail(settings):
    from pl_capital.challenges import compare_challenge, load_questions, reference_results

    case = load_questions(settings.data_root)[6]
    expected = reference_results(settings.data_root, settings.db_path, ids=[7])[7]
    selected = [i for i, name in enumerate(expected["columns"]) if name not in {"portfolio_a", "portfolio_b"}]
    actual = {**expected, "columns": [expected["columns"][i] for i in selected],
              "rows": [[row[i] for i in selected] for row in expected["rows"]]}
    assert compare_challenge(case, actual, expected)[0] == "pass"
    actual["rows"][0][-1] += 0.01
    assert compare_challenge(case, actual, expected)[0] == "fail"


def test_recorded_top_sector_tie_has_explicit_alphabetical_choice(settings):
    from pl_capital.challenges import reference_results, verify_references

    with closing(sqlite3.connect(settings.db_path)) as conn, conn:
        conn.execute("UPDATE holdings SET current_weight=0 WHERE portfolio_id=1")
        conn.execute("UPDATE holdings SET current_weight=0.5 WHERE portfolio_id=1 AND security_id IN (SELECT security_id FROM securities WHERE symbol IN ('AAPL','AMZN'))")
    result = reference_results(settings.data_root, settings.db_path, ids=[1])[1]
    row = next(row for row in result["rows"] if row[0] == "Growth Equity Fund")
    assert row[1] == "Consumer Discretionary"
    assert row[3] == "Technology"
    assert row[2] == 50
    assert verify_references(settings.data_root, settings.db_path)["passed"] == 20


def test_return_ties_and_small_universe_preserve_best_worst_overlap(settings):
    from pl_capital.challenges import reference_results, verify_references

    with closing(sqlite3.connect(settings.db_path)) as conn, conn:
        conn.execute("UPDATE securities SET asset_type='Bond' WHERE security_id NOT IN (1,2,3)")
        conn.execute("UPDATE securities SET current_price=100 WHERE security_id IN (1,2,3)")
        conn.execute("UPDATE historical_prices SET close_price=100 WHERE security_id IN (1,2,3)")
    result = reference_results(settings.data_root, settings.db_path, ids=[11])[11]
    assert len(result["rows"]) == 6
    for group in ("best", "worst"):
        selected = [row for row in result["rows"] if row[0] == group]
        assert [row[1] for row in selected] == [1, 2, 3]
        assert [row[2] for row in selected] == ["AAPL", "GOOGL", "MSFT"]
        assert [row[7] for row in selected] == [0, 0, 0]
    assert verify_references(settings.data_root, settings.db_path)["passed"] == 20


def test_streaks_span_missing_calendar_dates_and_choose_earliest_tied_run(settings):
    from pl_capital.challenges import reference_results, verify_references

    dates = ["2023-09-25", "2023-09-27", "2023-09-29", "2023-10-02", "2023-10-03", "2023-10-04", "2023-10-06", "2023-10-09"]
    with closing(sqlite3.connect(settings.db_path)) as conn, conn:
        conn.execute("DELETE FROM historical_prices WHERE security_id=1 AND price_date NOT IN (" + ",".join("?" for _ in dates) + ")", dates)
        for date, price in zip(dates, [100, 90, 80, 70, 100, 90, 80, 70], strict=True):
            conn.execute("UPDATE historical_prices SET close_price=? WHERE security_id=1 AND price_date=?", (price, date))
    result = reference_results(settings.data_root, settings.db_path, ids=[12])[12]
    assert next(row for row in result["rows"] if row[0] == "AAPL") == ["AAPL", 3, "2023-09-25", "2023-10-02", 4]
    assert verify_references(settings.data_root, settings.db_path)["passed"] == 20


def test_latest_common_date_is_not_the_latest_individual_date(settings):
    from pl_capital.challenges import reference_results, verify_references

    with closing(sqlite3.connect(settings.db_path)) as conn, conn:
        conn.execute("UPDATE risk_metrics SET calculation_date='2023-10-10' WHERE portfolio_id=1 AND calculation_date='2023-10-09'")
    result = reference_results(settings.data_root, settings.db_path, ids=[14])[14]
    assert next(row for row in result["rows"] if row[0] == "Growth Equity Fund")[1] == "2023-10-06"
    assert len(result["rows"]) == 4
    assert verify_references(settings.data_root, settings.db_path)["passed"] == 20


def test_zero_equity_value_denominators_stay_unavailable(settings):
    from pl_capital.challenges import reference_results, verify_references

    with closing(sqlite3.connect(settings.db_path)) as conn, conn:
        conn.execute("UPDATE securities SET current_price=0 WHERE asset_type='Stock'")
    results = reference_results(settings.data_root, settings.db_path, ids=[1, 3, 6, 9])
    assert results[1]["rows"] == results[3]["rows"] == results[6]["rows"] == []
    assert all(row[-1] is None for row in results[9]["rows"])
    assert verify_references(settings.data_root, settings.db_path)["passed"] == 20
