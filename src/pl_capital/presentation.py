"""Small, deterministic evidence views. Raw diagnostics are a separate opt-in."""

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal

import sqlglot
from sqlglot import exp

from pl_capital.models import Answer
from pl_capital.redaction import clean_text, redact


@dataclass
class TableView:
    columns: list[str]
    rows: list[list[str]]
    total_rows: int
    truncated: bool = False


@dataclass
class EvidenceSection:
    title: str
    lines: list[str] = field(default_factory=list)
    code: str | None = None
    language: str = "text"


@dataclass
class AnswerView:
    headline: str
    message: str
    steps: list[str]
    provenance: str
    warnings: list[str]
    table: TableView | None
    sections: list[EvidenceSection]


def _number_units(text: str, column: str, currency: str | None) -> str:
    label = column.lower()
    if label.endswith("_pp") or "percentage_points" in label:
        return text + " pp"
    if "percentage" in label or label.endswith("_pct"):
        return text + "%"
    if any(word in label for word in ("ratio", "fraction", "weight", "share", "hhi")):
        return text
    money = any(word in label for word in (
        "price", "aum", "value", "cost_basis", "notional", "proceeds", "fees", "nav",
    ))
    return "$" + text if money and currency == "USD" else text


def format_cell(value, column: str = "", *, currency: str | None = None) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return _number_units(f"{value:,}", column, currency)
    if isinstance(value, float | Decimal):
        if not math.isfinite(float(value)):
            return "Not available"
        raw = format(Decimal(format(float(value), ".10g")), "f")
        # Preserve significant fractional digits; display is not a scoring oracle.
        whole, _, fraction = raw.partition(".")
        fraction = fraction.rstrip("0")
        text = (
            ("-" if whole.startswith("-") and int(whole) == 0 else "")
            + f"{int(whole):,}"
            + ("." + fraction if fraction else "")
        )
        return _number_units(text, column, currency)
    return clean_text(value)


def _retrieval(answer):
    return next((event.data for event in answer.trace if event.stage == "retrieval"), {})


def _sql_sections(answer: Answer) -> tuple[list[str], list[EvidenceSection]]:
    sql = answer.executed_sql
    if not sql:
        return ["No SQL statement produced an accepted result."], []
    params = answer.executed_parameters or answer.parameters
    sections = [
        EvidenceSection("Executed SQL", code=clean_text(sql), language="sql"),
        EvidenceSection(
            "Bound parameters",
            code=json.dumps(redact(params), ensure_ascii=False, indent=2),
            language="json",
        ),
    ]
    operations = []
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
        for expression in tree.expressions:
            operations.append("Compute output: " + expression.sql(dialect="sqlite") + ".")
        counts = list(tree.find_all(exp.Count))
        if len(tree.expressions) == 1 and len(counts) == 1 and isinstance(counts[0].this, exp.Star):
            operations[0] = "Count each row of the selected source after any displayed filters."
        for cte in tree.find_all(exp.CTE):
            operations.append(
                f"Intermediate result: {cte.alias_or_name} (computed by the displayed WITH query)."
            )
        for join in tree.find_all(exp.Join):
            predicate = join.args.get("on")
            using = join.args.get("using")
            condition = (
                predicate.sql(dialect="sqlite")
                if predicate
                else ", ".join(c.name for c in using or [])
            )
            operations.append(
                f"Join {join.this.sql(dialect='sqlite')}"
                + (f" on {condition}." if condition else ".")
            )
        for where in tree.find_all(exp.Where):
            condition = where.this.copy()
            for placeholder in list(condition.find_all(exp.Placeholder)):
                if placeholder.name in params:
                    placeholder.replace(exp.convert(params[placeholder.name]))
            operations.append("Filter: " + condition.sql(dialect="sqlite") + ".")
        for group in tree.find_all(exp.Group):
            operations.append(
                "Group by "
                + ", ".join(node.sql(dialect="sqlite") for node in group.expressions)
                + "."
            )
        if tree.args.get("order"):
            operations.append("Sort: " + tree.args["order"].sql(dialect="sqlite") + ".")
        if tree.args.get("limit"):
            operations.append("Limit: " + tree.args["limit"].sql(dialect="sqlite") + ".")
        if list(tree.find_all(exp.Window)):
            operations.append(
                "Window operations use the displayed PARTITION BY / ORDER BY observation order; calendar gaps are not filled."
            )
        if not operations:
            operations.append(
                "Read the displayed SELECT expressions from the listed source tables, without joins or filters."
            )
    except (sqlglot.errors.SqlglotError, ValueError, RecursionError):
        operations.append(
            "See the exact executed SQL above; a safe textual interpretation is unavailable."
        )
    sections.append(
        EvidenceSection("Query operations", [clean_text(line) for line in operations[:24]])
    )
    count = answer.result.get("row_count", len(answer.result.get("rows", [])))
    steps = [
        f"Read authoritative SQLite tables: {', '.join(answer.result.get('source_tables', [])) or 'shown in the SQL'}.",
        operations[0],
        f"Return {count} row{'s' if count != 1 else ''}; numeric values come from SQLite, not model arithmetic.",
    ]
    if any(event.stage == "validation" for event in answer.trace):
        steps.insert(
            1,
            "Validated one read-only SELECT with approved tables, functions and bound parameters.",
        )
    checks = [f"Returned rows: {count}.", "NULL is displayed as Not available; zero remains zero."]
    if answer.result.get("rows"):
        cells = answer.result["rows"][0]
        columns = answer.result.get("columns", [])
        checks.append("First returned record: " + "; ".join(
            f"{column} = {format_cell(value, column, currency=answer.currency)}"
            for column, value in list(zip(columns, cells, strict=True))[:8]
        ) + ".")
    checks.append("Display uses up to 10 significant digits; JSON export preserves returned numeric values.")
    if answer.result.get("truncated"):
        checks.append("The query result reached the row cap; it is incomplete.")
    if any(event.stage == "metric_verification" for event in answer.trace):
        checks.append(
            "Sector values, the all-holdings denominator and percentage units were independently verified."
        )
    sections.append(EvidenceSection("Result checks", checks))
    return steps[:5], sections


def _exposure_sections(answer: Answer):
    result = answer.result
    equity = result.get("equity_weight_total", "0")
    bond = result.get("bond_weight_total", "0")
    total = result.get("all_recorded_weights_total", "0")
    lines = [
        f"Stock weight sum = {equity}; bond weight sum = {bond}; all recorded weights = {total}."
    ]
    for sector in result.get("sectors", []):
        lines.append(
            f"{sector['sector']}: {sector['weight']} × 100 = {sector['whole_portfolio_pct']}% of the whole portfolio; {sector['weight']} / {equity} × 100 = {sector['equity_normalized_pct']}% of recorded equity."
        )
    if not result.get("sectors"):
        lines.append(
            "No positive equity denominator is available, so no equity-normalized percentage is calculated."
        )
    steps = [
        f"Match portfolio: {result.get('portfolio_name', 'requested portfolio')}.",
        f"Include {result.get('equity_holding_count', 0)} stock holdings; exclude {result.get('bond_exclusion_count', 0)} bond holdings.",
        f"Sum recorded stock weights by sector; total stock weight is {equity}.",
        "Show sector weight × 100 for the whole portfolio, then sector weight / total stock weight × 100 for equity only.",
    ]
    return steps, [
        EvidenceSection("Sector arithmetic", lines),
        EvidenceSection(
            "Coverage checks",
            [
                f"Recorded weights total {total}; no missing allocation is invented or silently scaled.",
                *result.get("warnings", []),
            ],
        ),
    ]


def build_answer_view(answer: Answer) -> AnswerView:
    result = answer.result
    table = None
    headline = answer.error or answer.message or "Analysis complete"
    message = ""
    if answer.error:
        steps, sections = (
            [
                "Analysis stopped safely; no successful answer is claimed.",
                "Review the error and the rejected/proposed query in optional diagnostics.",
            ],
            [],
        )
    elif "sectors" in result:
        headline = f"{result.get('portfolio_name', 'Portfolio')} — sector exposure"
        if result.get("status") == "no_equity_holdings":
            headline = f"{result.get('portfolio_name', 'Portfolio')}: no equity exposure"
        table = TableView(
            ["Sector", "Portfolio %", "Equity %"],
            [
                [
                    clean_text(s["sector"]),
                    format_cell(s["whole_portfolio_pct"], "allocation_pct"),
                    format_cell(s["equity_normalized_pct"], "allocation_pct"),
                ]
                for s in result["sectors"]
            ],
            len(result["sectors"]),
        )
        steps, sections = _exposure_sections(answer)
    elif "columns" in result:
        rows, columns = result.get("rows", []), result["columns"]
        headline = f"{len(rows)} matching records" if rows else "No matching records"
        if len(rows) == len(columns) == 1:
            label = columns[0].replace("_", " ")
            try:
                tree = sqlglot.parse_one(answer.executed_sql or "", read="sqlite")
                count_expr = tree.expressions[0].unalias() if isinstance(tree, exp.Select) else None
                counted = isinstance(count_expr, exp.Count) and isinstance(
                    count_expr.this, exp.Star
                )
                sources = result.get("source_tables", [])
                if counted and len(sources) == 1:
                    headline = f"{format_cell(rows[0][0])} {sources[0].replace('_', ' ')}"
                else:
                    headline = (
                        f"{label}: {format_cell(rows[0][0], columns[0], currency=answer.currency)}"
                    )
            except (sqlglot.errors.SqlglotError, ValueError, IndexError):
                headline = (
                    f"{label}: {format_cell(rows[0][0], columns[0], currency=answer.currency)}"
                )
        elif rows:
            table = TableView(
                [clean_text(c).replace("_", " ") for c in columns],
                [
                    [
                        format_cell(v, c, currency=answer.currency)
                        for c, v in zip(columns, row, strict=True)
                    ]
                    for row in rows[:8]
                ],
                result.get("row_count", len(rows)),
                bool(result.get("truncated")),
            )
        steps, sections = _sql_sections(answer)
    else:
        steps = [
            "No financial calculation was executed.",
            answer.message or "Provide a descriptive portfolio question.",
        ]
        sections = []
    retrieved = _retrieval(answer)
    graph_label = (
        "Graph context used" if retrieved.get("used") else "SQLite schema / graph fallback"
    )
    tables = ", ".join(result.get("source_tables", [])) or (
        "holdings, securities, sectors, portfolios" if "sectors" in result else "no result tables"
    )
    provenance = (
        f"{answer.tool or answer.intent} · {tables} · {graph_label} · {answer.elapsed_ms:.0f} ms"
    )
    graph_lines = [clean_text(retrieved.get("reason", "No graph retrieval was recorded."))]
    if retrieved.get("used"):
        for entity in retrieved.get("entities", [])[:5]:
            graph_lines.append(
                "Matched "
                + clean_text(entity.get("type", "entity"))
                + ": "
                + clean_text(entity.get("name", entity.get("symbol", entity.get("portfolio", ""))))
            )
    sections += [
        EvidenceSection(
            "Source and assumptions",
            [
                f"SQLite source tables: {tables}.",
                "Security prices are supplied snapshot values, not live quotes.",
                *answer.assumptions,
                *[
                    f"{name} observation dates: {dates[0]} through {dates[-1]}."
                    for name, dates in answer.source_dates.items()
                    if dates and dates[0] is not None
                ],
            ],
        ),
        EvidenceSection("Graph context", graph_lines),
    ]
    warnings = list(dict.fromkeys(clean_text(w) for w in answer.warnings))
    return AnswerView(
        clean_text(headline),
        clean_text(message),
        [clean_text(s) for s in steps],
        clean_text(provenance),
        warnings,
        table,
        sections,
    )


def diagnostic_payload(answer: Answer, secret: str = "") -> dict:
    return redact(answer.model_dump(mode="json"), secret)
