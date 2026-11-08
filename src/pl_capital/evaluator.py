"""Independent assessment oracle. Reference answers never enter agent planning."""

import json
import math
import os
import re
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from pl_capital.errors import ConfigurationError, DataError


def _cell_equal(actual: Any, expected: Any, tolerance: float) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, Real) and isinstance(expected, Real):
        return (
            math.isfinite(actual)
            and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=1e-8, abs_tol=tolerance)
        )
    return type(actual) is type(expected) and actual == expected


def compare_sql(
    actual: dict, expected: dict, *, ordered: bool, tolerances: list[float] | None = None
) -> tuple[bool, str]:
    """Compare positional column structure and complete rows, permitting equivalent aliases."""
    if actual.get("truncated"):
        return False, "Actual SQL result was truncated."
    columns, expected_columns = actual.get("columns"), expected.get("columns")
    rows, expected_rows = actual.get("rows"), expected.get("rows")
    if not all(
        isinstance(value, list) for value in (columns, expected_columns, rows, expected_rows)
    ):
        return False, "SQL result is missing columns or rows."
    if len(columns) != len(expected_columns):
        return False, "Column count differs from the reference."
    if len(rows) != len(expected_rows) or actual.get("row_count") != len(rows):
        return False, "Row count differs from the complete reference."
    width = len(expected_columns)
    if any(not isinstance(row, list | tuple) or len(row) != width for row in rows + expected_rows):
        return False, "Row or column shape differs from the reference."
    tolerances = tolerances or [1e-6] * width
    if len(tolerances) != width:
        return False, "Reference precision does not match result columns."

    def same_row(left, right):
        return all(
            _cell_equal(a, b, tol) for a, b, tol in zip(left, right, tolerances, strict=True)
        )

    if ordered:
        passed = all(same_row(a, b) for a, b in zip(rows, expected_rows, strict=True))
        return passed, "Matched ordered reference." if passed else "Ordered row values differ."
    # Bipartite matching preserves duplicates and avoids greedy tolerance collisions.
    matched: dict[int, int] = {}

    def assign(index: int, seen: set[int]) -> bool:
        for candidate, expected_row in enumerate(expected_rows):
            if candidate in seen or not same_row(rows[index], expected_row):
                continue
            seen.add(candidate)
            if candidate not in matched or assign(matched[candidate], seen):
                matched[candidate] = index
                return True
        return False

    passed = all(assign(index, set()) for index in range(len(rows)))
    return (
        passed,
        "Matched unordered reference multiset."
        if passed
        else "Row values or duplicate counts differ.",
    )


def reference_query(sql: str) -> dict:
    """Derive ordering and precision from the trusted supplied reference AST."""
    tree = sqlglot.parse_one(sql, read="sqlite")
    tolerances = []
    for projection in tree.expressions:
        node = projection.this if isinstance(projection, exp.Alias) else projection
        rounding = node if isinstance(node, exp.Round) else None
        decimals = rounding.args.get("decimals") if rounding is not None else None
        tolerance = 1e-6
        if isinstance(decimals, exp.Literal) and not decimals.is_string:
            precision = int(decimals.this)
            tolerance = 0.5 * 10 ** (-precision)
        tolerances.append(tolerance)
    return {"ordered": tree.args.get("order") is not None, "tolerances": tolerances}


def _reference_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    conn.execute("PRAGMA query_only=ON")
    deadline = time.monotonic() + 5
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return conn


def reference_exposure(path: Path, portfolio_name: str) -> dict:
    """SQL aggregation oracle, independent of the production Decimal calculator."""
    conn = _reference_connection(path)
    try:
        portfolio = conn.execute(
            "SELECT portfolio_id, portfolio_name FROM portfolios WHERE portfolio_name=?",
            (portfolio_name,),
        ).fetchone()
        if portfolio is None:
            raise DataError("Ground-truth portfolio is absent from the snapshot.")
        totals = conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN s.asset_type='Stock' THEN h.current_weight ELSE 0 END),0),
            COALESCE(SUM(CASE WHEN s.asset_type='Bond' THEN h.current_weight ELSE 0 END),0),
            COALESCE(SUM(h.current_weight),0),
            COALESCE(SUM(CASE WHEN s.asset_type='Stock' THEN 1 ELSE 0 END),0),
            COALESCE(SUM(CASE WHEN s.asset_type='Bond' THEN 1 ELSE 0 END),0)
            FROM holdings h JOIN securities s ON s.security_id=h.security_id WHERE h.portfolio_id=?""",
            (portfolio[0],),
        ).fetchone()
        groups = conn.execute(
            """SELECT sec.sector_name, SUM(h.current_weight) FROM holdings h
            JOIN securities s ON s.security_id=h.security_id
            JOIN sectors sec ON sec.sector_id=s.sector_id
            WHERE h.portfolio_id=? AND s.asset_type='Stock'
            GROUP BY sec.sector_name ORDER BY sec.sector_name""",
            (portfolio[0],),
        ).fetchall()
        sectors = [
            {
                "sector": name,
                "weight": str(weight),
                "whole_portfolio_pct": weight * 100,
                "equity_normalized_pct": weight / totals[0] * 100 if totals[0] else 0,
            }
            for name, weight in groups
        ]
        return {
            "portfolio_id": portfolio[0],
            "portfolio_name": portfolio[1],
            "status": "ok" if totals[3] else "no_equity_holdings",
            "sectors": sectors,
            "equity_weight_total": str(totals[0]),
            "bond_weight_total": str(totals[1]),
            "all_recorded_weights_total": str(totals[2]),
            "equity_holding_count": totals[3],
            "bond_exclusion_count": totals[4],
        }
    finally:
        conn.close()


def compare_exposure(actual: dict, expected: dict) -> tuple[bool, str]:
    for field in (
        "portfolio_id",
        "portfolio_name",
        "status",
        "equity_holding_count",
        "bond_exclusion_count",
    ):
        if actual.get(field) != expected.get(field):
            return False, f"Exposure {field} differs from the independent reference."
    for field in ("equity_weight_total", "bond_weight_total", "all_recorded_weights_total"):
        try:
            if not _cell_equal(float(actual[field]), float(expected[field]), 1e-8):
                return False, f"Exposure {field} differs from the independent reference."
        except (KeyError, TypeError, ValueError, OverflowError):
            return False, f"Exposure {field} is absent or invalid."
    sectors = actual.get("sectors")
    if not isinstance(sectors, list) or any(not isinstance(row, dict) for row in sectors):
        return False, "Sector breakdown is absent or malformed."
    try:
        names = [row["sector"] for row in sectors]
        expected_names = [row["sector"] for row in expected["sectors"]]
        if len(names) != len(set(names)) or set(names) != set(expected_names):
            return False, "Sector set or duplicate sector count differs."
        actual_sectors = {row["sector"]: row for row in sectors}
        for row in expected["sectors"]:
            for field in ("weight", "whole_portfolio_pct", "equity_normalized_pct"):
                if not _cell_equal(
                    float(actual_sectors[row["sector"]][field]), float(row[field]), 1e-6
                ):
                    return False, f"Sector {row['sector']} {field} differs from reference."
    except (KeyError, TypeError, ValueError, OverflowError):
        return False, "Sector exposure has absent or invalid values."
    return True, "Matched independent stock-only recorded-weight reference and both denominators."


def _scrub(value: Any, secret: str) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item, secret) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item, secret) for item in value]
    if isinstance(value, str):
        value = value.replace(secret, "[REDACTED]") if secret else value
        return re.sub(r"(?:gsk_|gh[pousr]_|AIza|AQ\.)[A-Za-z0-9_]{20,}", "[REDACTED]", value)
    if isinstance(value, float) and not math.isfinite(value):
        return "[NONFINITE]"
    return value


def _write_report(path: Path, report: dict):
    path = Path(path)
    content = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if len(content.encode("utf-8")) > 5_000_000:
        raise DataError("Evaluation report exceeds its 5 MB output budget.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="evaluation-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def evaluate(
    agent, root: Path | None = None, *, report: Path | None = None, live: bool = True
) -> dict:
    """Run every supplied question through the agent; mocks require explicit offline mode."""
    if live and (getattr(agent, "live", False) is not True or not agent.settings.api_key):
        raise ConfigurationError(
            f"Live evaluation requires a real {getattr(agent.settings, 'provider', 'groq').title()} agent and configured API key."
        )
    root = Path(root or agent.settings.data_root)
    try:
        questions = json.loads((root / "ground_truth_dataset.json").read_text(encoding="utf-8"))[
            "questions"
        ]
    except (OSError, ValueError, KeyError) as exc:
        raise DataError("Ground-truth dataset is missing or invalid.") from exc
    started = time.perf_counter()
    items = []
    for question in questions:
        item = {key: question[key] for key in ("id", "type", "difficulty", "question")}
        item.update(passed=False, actual=None, expected=None, reason="", sql=None, parameters={})
        began = time.perf_counter()
        answer = None
        try:
            if hasattr(agent, "reset_context"):
                agent.reset_context()
            answer = agent.answer_question(question["question"])
            item.update(
                actual=answer.result,
                sql=answer.sql,
                parameters=answer.parameters,
                intent=answer.intent,
                tool=answer.tool,
                error=answer.error,
                warnings=answer.warnings,
                agent_elapsed_ms=answer.elapsed_ms,
            )
        except Exception:  # Never serialize raw SDK exceptions; still compute the oracle below.
            item["reason"] = "Agent execution failed; inspect safe application diagnostics."
            item["error"] = "Agent execution error."
        try:
            target = "sql_query" if question["type"] == "text2sql" else "exposure_calculator"
            truth = question["ground_truth"]
            if question["type"] == "text2sql":
                conn = _reference_connection(agent.settings.db_path)
                try:
                    cursor = conn.execute(truth["sql_query"])
                    rows = [list(row) for row in cursor.fetchall()]
                    expected = {
                        "columns": [col[0] for col in cursor.description],
                        "rows": rows,
                        "row_count": len(rows),
                        "truncated": False,
                    }
                finally:
                    conn.close()
                item.update(expected=expected, reference_sql=truth["sql_query"])
                comparison = (
                    compare_sql(answer.result, expected, **reference_query(truth["sql_query"]))
                    if answer is not None
                    else None
                )
            else:
                expected = reference_exposure(
                    agent.settings.db_path, truth["parameters"]["portfolio_name"]
                )
                item["expected"] = expected
                comparison = (
                    compare_exposure(answer.result, expected) if answer is not None else None
                )
            if answer is None:
                pass
            elif answer.error:
                item["reason"] = "Agent returned an error."
            elif answer.intent != target or answer.tool != target:
                item["reason"] = f"Incorrect tool routing; expected {target}."
            else:
                item["passed"], item["reason"] = comparison
        except Exception:  # Continue all supplied questions; never serialize raw SDK exceptions.
            item["reason"] = (
                "Reference or result comparison failed; inspect safe application diagnostics."
            )
            item["error"] = "Evaluation execution error."
        item["elapsed_ms"] = round((time.perf_counter() - began) * 1000, 3)
        items.append(item)
    by_type = {}
    by_difficulty = {}
    for field, groups in (("type", by_type), ("difficulty", by_difficulty)):
        for value in sorted({item[field] for item in items}):
            selected = [item for item in items if item[field] == value]
            passed = sum(item["passed"] for item in selected)
            groups[value] = {
                "passed": passed,
                "total": len(selected),
                "accuracy": passed / len(selected),
            }
    passed = sum(item["passed"] for item in items)
    result = {
        "mode": f"live {getattr(agent.settings, 'provider', 'groq').title()} agent" if live else "offline test (mocked)",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "model": getattr(agent.settings, "model", None),
        "passed": passed,
        "total": len(items),
        "accuracy": passed / len(items) if items else 0,
        "by_type": by_type,
        "by_difficulty": by_difficulty,
        "questions": items,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "comparison_policy": "Positional column structure; ordered rows for root ORDER BY, otherwise duplicate-preserving multiset; numeric abs 1e-6/rel 1e-8 except half-unit precision for reference ROUND; stock-only exposure oracle.",
    }
    result = _scrub(result, agent.settings.api_key)
    if report is not None:
        _write_report(report, result)
    return result
