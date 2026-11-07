"""An AST allowlist complements (never replaces) SQLite's read-only enforcement."""

import math
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, SqlglotError
from sqlglot.optimizer.qualify import qualify

from pl_capital.database import SAFE_FUNCTIONS
from pl_capital.errors import QueryError


def validate_audit_projection(sql: str, *, question: str = "") -> None:
    """General ratio display policy, separate from the SQL security boundary.

    The agent must ask Groq to repair a deficient plan; this never rewrites SQL
    or supplies known assessment answers. Ratios expose their denominators.
    Percentage tables use the documented default rounding and ranking.
    """
    tree = sqlglot.parse_one(sql, read="sqlite")
    if not isinstance(tree, exp.Select):
        return
    projected = [p.this if isinstance(p, exp.Alias) else p for p in tree.expressions]
    columns = {p.sql(dialect="sqlite").lower() for p in projected if isinstance(p, exp.Column)}
    for projection in tree.expressions:
        divisions = list(projection.find_all(exp.Div))
        for division in divisions:
            denominator = division.expression
            if (
                isinstance(denominator, exp.Column)
                and denominator.sql(dialect="sqlite").lower() not in columns
            ):
                raise QueryError(
                    "Auditable ratios must include the denominator as a separate output column."
                )
        percentage = (
            len(tree.expressions) > 1
            and bool(divisions)
            and any(
                isinstance(node, exp.Literal)
                and not node.is_string
                and node.this in {"100", "100.0"}
                for node in projection.walk()
            )
        )
        if not percentage:
            continue
        rounding = projection.find(exp.Round)
        if rounding is None or str(rounding.args.get("decimals")) != "2":
            raise QueryError(
                "Percentage outputs must use ROUND(expression, 2) for the documented display precision."
            )
        if re.search(
            r"\b(?:sort|sorted|order|ordered|rank)\b.{0,40}\b(?:by|ascend|descend|alphabet)",
            question,
            re.I,
        ):
            continue
        order = tree.args.get("order")
        alias = projection.alias_or_name.lower()
        if (
            not order
            or not order.expressions
            or not order.expressions[0].args.get("desc")
            or order.expressions[0].this.name.lower() != alias
        ):
            raise QueryError(
                "Percentage breakdowns must use the documented default descending percentage ordering."
            )


def validate(sql: str, parameters: dict, schema: dict) -> tuple[str, list[str]]:
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 30_000:
        raise QueryError("SQL must contain one bounded SELECT statement.")
    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except (ParseError, SqlglotError, RecursionError) as exc:
        raise QueryError("SQL could not be parsed as SQLite SELECT.") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select | exp.SetOperation):
        raise QueryError("Exactly one SELECT or WITH SELECT is permitted.")
    tree = statements[0]
    blocked = {
        "Insert",
        "Update",
        "Delete",
        "Create",
        "Drop",
        "Alter",
        "Command",
        "Pragma",
        "Attach",
        "Detach",
        "Copy",
        "Merge",
        "Into",
        "Transaction",
        "Commit",
        "Rollback",
        "LoadData",
        "Execute",
        "Grant",
        "Revoke",
        "Use",
        "Lock",
        "Unlock",
    }
    nodes = list(tree.walk())
    if len(nodes) > 2000:
        raise QueryError("SQL AST exceeds the query complexity budget.")
    if any(type(node).__name__ in blocked for node in nodes):
        raise QueryError("SQL contains a forbidden operation.")
    if any(node.args.get("recursive") for node in tree.find_all(exp.With)):
        raise QueryError("Recursive CTEs are outside the query budget.")
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier) or table.db or table.catalog:
            raise QueryError("Only named dataset tables and CTEs are permitted.")
        name = table.name.lower()
        if name not in schema and name not in ctes:
            raise QueryError(f"Unknown or forbidden table: {name}.")
        if name in schema:
            tables.add(name)
    for func in tree.find_all(exp.Func):
        name = func.name.lower() if isinstance(func, exp.Anonymous) else func.sql_name().lower()
        if name not in SAFE_FUNCTIONS | {"cast", "case", "if", "extract", "ts_or_ds_to_date"}:
            raise QueryError(f"Function is not allowed: {name}.")
    placeholders = []
    for node in tree.find_all(exp.Placeholder):
        name = node.name
        if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            raise QueryError("Use named :parameters only.")
        placeholders.append(name)
    if set(placeholders) != set(parameters):
        raise QueryError("Declared parameters must exactly match SQL placeholders.")
    for value in parameters.values():
        if not isinstance(value, str | int | float | bool | type(None)):
            raise QueryError("Only scalar SQL parameter values are permitted.")
        if isinstance(value, str) and len(value) > 2000:
            raise QueryError("SQL parameter exceeds size limit.")
        if isinstance(value, float) and not math.isfinite(value):
            raise QueryError("Nonfinite SQL parameter rejected.")
    try:
        qualify(
            tree.copy(),
            dialect="sqlite",
            schema=schema,
            validate_qualify_columns=True,
            infer_schema=False,
            identify=False,
            quote_identifiers=False,
        )
    except (OptimizeError, SqlglotError, ValueError, RecursionError) as exc:
        raise QueryError("SQL references an unknown or ambiguous column.") from exc
    return sql.strip(), sorted(tables)
