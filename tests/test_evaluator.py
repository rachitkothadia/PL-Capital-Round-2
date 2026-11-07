import json
import sqlite3

import pytest

from pl_capital.models import Answer


def query_result(rows, columns=None):
    return {
        "columns": columns or ["value"],
        "rows": rows,
        "row_count": len(rows),
        "truncated": False,
    }


@pytest.mark.parametrize(
    "actual,expected,ordered,passed",
    [
        (query_result([[13]], ["count"]), query_result([[13]], ["COUNT(*)"]), False, True),
        (query_result([["b"], ["a"]]), query_result([["a"], ["b"]]), False, True),
        (query_result([["b"], ["a"]]), query_result([["a"], ["b"]]), True, False),
        (query_result([[1], [1]]), query_result([[1], [2]]), False, False),
        (query_result([[1, 2]], ["a", "b"]), query_result([[1], [2]]), False, False),
        (query_result([[None]]), query_result([[None]]), False, True),
        (query_result([["13"]]), query_result([[13]]), False, False),
        (query_result([[True]]), query_result([[1]]), False, False),
        (query_result([[float("nan")]]), query_result([[1]]), False, False),
        (query_result([[13.00000001]]), query_result([[13]]), False, True),
        (query_result([[13.1]]), query_result([[13]]), False, False),
        (query_result([], ["a", "b"]), query_result([], ["a"]), False, False),
    ],
)
def test_sql_comparison_preserves_structure(actual, expected, ordered, passed):
    from pl_capital.evaluator import compare_sql

    assert compare_sql(actual, expected, ordered=ordered)[0] is passed


def test_tolerances_and_truncation():
    from pl_capital.evaluator import compare_sql

    assert compare_sql(
        query_result([[84.667]]), query_result([[84.67]]), ordered=True, tolerances=[0.005]
    )[0]
    assert not compare_sql(
        query_result([[84.66]]), query_result([[84.67]]), ordered=True, tolerances=[0.005]
    )[0]
    assert not compare_sql(
        query_result([[0.501]]), query_result([[0.5]]), ordered=True, tolerances=[0.0005]
    )[0]
    actual = query_result([[1]])
    actual["truncated"] = True
    assert not compare_sql(actual, query_result([[1]]), ordered=False)[0]


def test_reference_precision_and_root_ordering():
    from pl_capital.evaluator import reference_query

    reference = reference_query(
        "SELECT name, ROUND(value,2) AS pct, ROUND(x,3) AS ratio FROM t ORDER BY pct DESC"
    )
    assert reference == {"ordered": True, "tolerances": [1e-6, 0.005, 0.0005]}
    assert not reference_query("SELECT * FROM (SELECT * FROM t ORDER BY name)")["ordered"]


def test_exposure_checks_bonds_and_both_denominators():
    from pl_capital.evaluator import compare_exposure

    expected = {
        "portfolio_id": 1,
        "portfolio_name": "Mixed",
        "status": "ok",
        "sectors": [
            {
                "sector": "Technology",
                "weight": "0.5",
                "whole_portfolio_pct": 50,
                "equity_normalized_pct": 100,
            }
        ],
        "equity_weight_total": "0.5",
        "bond_weight_total": "0.5",
        "all_recorded_weights_total": "1",
        "equity_holding_count": 1,
        "bond_exclusion_count": 1,
    }
    assert compare_exposure(expected, expected)[0]
    wrong = dict(expected, bond_exclusion_count=0)
    assert not compare_exposure(wrong, expected)[0]
    wrong = dict(expected, sectors=[dict(expected["sectors"][0], whole_portfolio_pct=100)])
    assert not compare_exposure(wrong, expected)[0]
    wrong = dict(expected, sectors=expected["sectors"] * 2)
    assert not compare_exposure(wrong, expected)[0]


class OracleTestAgent:
    """Mocked evaluator mechanics only; deliberately labeled offline in every report."""

    live = False

    def __init__(self, settings):
        self.settings = settings
        self.calls = []
        self.resets = 0

    def reset_context(self):
        self.resets += 1

    def answer_question(self, question):
        from pl_capital.evaluator import reference_exposure

        self.calls.append(question)
        questions = json.loads((self.settings.data_root / "ground_truth_dataset.json").read_text())[
            "questions"
        ]
        reference = next(q for q in questions if q["question"] == question)
        if reference["type"] == "text2sql":
            sql = reference["ground_truth"]["sql_query"]
            with sqlite3.connect(self.settings.db_path) as conn:
                cursor = conn.execute(sql)
                rows = [list(row) for row in cursor.fetchall()]
                columns = [item[0] for item in cursor.description]
            return Answer(
                intent="sql_query", tool="sql_query", result=query_result(rows, columns), sql=sql
            )
        name = reference["ground_truth"]["parameters"]["portfolio_name"]
        return Answer(
            intent="exposure_calculator",
            tool="exposure_calculator",
            result=reference_exposure(self.settings.db_path, name),
        )


def test_all_ten_questions_are_sent_to_agent_with_independent_references(settings, tmp_path):
    from pl_capital.evaluator import evaluate

    agent = OracleTestAgent(settings)
    output = tmp_path / "reports" / "evaluation.json"
    report = evaluate(agent, report=output, live=False)
    assert report["mode"] == "offline test (mocked)"
    assert report["passed"] == 10 and report["total"] == 10
    assert report["by_type"]["text2sql"]["total"] == 8
    assert len(agent.calls) == 10 and agent.resets == 10
    assert json.loads(output.read_text())["passed"] == 10
    assert "test-key" not in output.read_text()
    # Windows exposes DOS permission bits here, not POSIX owner/group ACLs.
    # The inherited directory ACL applies there; serialization checks above
    # still enforce removal of credentials on every platform.
    if __import__("os").name != "nt":
        assert not output.stat().st_mode & 0o077


def test_live_mode_cannot_label_mock_as_real(settings):
    from pl_capital.errors import ConfigurationError
    from pl_capital.evaluator import evaluate

    with pytest.raises(ConfigurationError, match="real Groq"):
        evaluate(OracleTestAgent(settings))


def test_agent_failure_does_not_skip_remaining_questions(settings):
    from pl_capital.evaluator import evaluate

    class FailedAgent(OracleTestAgent):
        def answer_question(self, question):
            self.calls.append(question)
            if len(self.calls) == 1:
                raise RuntimeError("sensitive provider error")
            return Answer(error="Service unavailable", message="Service unavailable")

    agent = FailedAgent(settings)
    report = evaluate(agent, live=False)
    assert report["passed"] == 0 and len(agent.calls) == 10
    assert "sensitive provider error" not in json.dumps(report)
    assert all(item["reason"] for item in report["questions"])
    assert report["questions"][0]["expected"]["rows"] == [[13]]


def test_wrong_tool_cannot_pass_even_with_correct_values(settings):
    from pl_capital.evaluator import evaluate

    class WrongTool(OracleTestAgent):
        def answer_question(self, question):
            answer = super().answer_question(question)
            answer.tool = "other"
            return answer

    assert evaluate(WrongTool(settings), live=False)["passed"] == 0


def test_nonfinite_actual_does_not_break_report(settings, tmp_path):
    from pl_capital.evaluator import evaluate

    class Nonfinite(OracleTestAgent):
        def answer_question(self, question):
            answer = super().answer_question(question)
            if answer.intent == "sql_query":
                answer.result["rows"][0][0] = float("nan")
            return answer

    output = tmp_path / "bad-result.json"
    report = evaluate(Nonfinite(settings), live=False, report=output)
    assert report["passed"] == 2
    assert "NaN" not in output.read_text()
