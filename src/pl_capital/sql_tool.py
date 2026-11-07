import json
import sqlite3
import time
from pathlib import Path

from pl_capital.database import readonly, schema_context
from pl_capital.errors import QueryError
from pl_capital.models import QueryResult
from pl_capital.sql_safety import validate


def execute(
    path: Path,
    sql: str,
    parameters: dict,
    *,
    max_rows: int = 300,
    timeout: float = 2.0,
    max_steps: int = 2_000_000,
) -> QueryResult:
    started = time.perf_counter()
    sql, tables = validate(sql, parameters, schema_context(path))
    try:
        with readonly(path, timeout=timeout, max_steps=max_steps) as conn:
            cursor = conn.execute(sql, parameters)
            columns = [c[0] for c in cursor.description]
            rows = [list(row) for row in cursor.fetchmany(max_rows + 1)]
            if len(json.dumps(rows, ensure_ascii=False, allow_nan=False)) > 200_000:
                raise QueryError("Result exceeds the output size budget; narrow the query.")
            return QueryResult(
                columns=columns,
                rows=rows[:max_rows],
                row_count=min(len(rows), max_rows),
                truncated=len(rows) > max_rows,
                source_tables=tables,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            )
    except (sqlite3.Error, ValueError, OverflowError) as exc:
        # SQLite messages contain table/column names, never SDK credentials/request headers.
        raise QueryError(f"SQL execution rejected: {str(exc)[:200]}") from exc
