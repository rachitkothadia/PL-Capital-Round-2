"""Trusted atomic import; all analytical connections are independently read-only."""

import csv
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

from pl_capital.errors import DataError

TABLES = (
    "sectors",
    "securities",
    "benchmarks",
    "portfolios",
    "holdings",
    "transactions",
    "historical_prices",
    "portfolio_performance",
    "risk_metrics",
)
EXPECTED_COUNTS = dict(zip(TABLES, (10, 30, 13, 13, 95, 24, 330, 44, 44), strict=True))
SAFE_FUNCTIONS = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "round",
        "abs",
        "coalesce",
        "ifnull",
        "nullif",
        "lower",
        "upper",
        "length",
        "substr",
        "substring",
        "trim",
        "ltrim",
        "rtrim",
        "replace",
        "like",
        "glob",
        "date",
        "datetime",
        "strftime",
        "julianday",
        "unixepoch",
        "total",
        "row_number",
        "rank",
        "dense_rank",
        "lag",
        "lead",
        "first_value",
        "last_value",
    }
)


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for rel in ["database_schema.sql", *[f"data/{t}.csv" for t in TABLES]]:
        file = root / rel
        if not file.is_file():
            raise DataError(f"Missing supplied dataset file: {rel}. Set PL_CAPITAL_DATA_DIR.")
        digest.update(rel.encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def initialize(root: Path, path: Path, *, rebuild: bool = False) -> dict:
    """Never replace an existing DB unless explicitly requested; failed rebuilds preserve it."""
    root, path = Path(root), Path(path)
    stamp = fingerprint(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=20):
        if path.exists() and not rebuild:
            try:
                with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                    manifest = json.loads(
                        conn.execute("SELECT manifest FROM _dataset_meta").fetchone()[0]
                    )
            except (sqlite3.Error, ValueError, TypeError) as exc:
                raise DataError(
                    "Existing database is invalid; use init-db --rebuild explicitly."
                ) from exc
            if manifest["fingerprint"] != stamp:
                raise DataError("Dataset changed; use init-db --rebuild to refresh explicitly.")
            return manifest
        fd, temp_name = tempfile.mkstemp(prefix="import-", suffix=".db", dir=path.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            with sqlite3.connect(temp) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript((root / "database_schema.sql").read_text(encoding="utf-8"))
                counts = {}
                for table in TABLES:
                    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                    columns = [r[1] for r in info]
                    with (root / "data" / f"{table}.csv").open(
                        newline="", encoding="utf-8-sig"
                    ) as f:
                        reader = csv.DictReader(f)
                        if reader.fieldnames != columns:
                            raise DataError(f"CSV header mismatch in {table}.")
                        rows = []
                        for row in reader:
                            converted = []
                            for col, meta in zip(columns, info, strict=True):
                                value = row[col]
                                if value is None:
                                    raise DataError(f"Malformed CSV row in {table}.")
                                typed = None if value == "" else value
                                if typed is not None and meta[2] in {"INTEGER", "REAL"}:
                                    typed = int(value) if meta[2] == "INTEGER" else float(value)
                                    if not math.isfinite(typed):
                                        raise DataError(
                                            f"Nonfinite numeric input in {table}.{col}."
                                        )
                                converted.append(typed)
                            rows.append(converted)
                        placeholders = ",".join("?" for _ in columns)
                        # table comes from TABLES; values are exclusively bound parameters.
                        conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)  # noqa: S608
                        counts[table] = len(rows)
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise DataError("Foreign-key validation failed.")
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DataError("Database integrity validation failed.")
                manifest = {"fingerprint": stamp, "counts": counts}
                conn.execute("CREATE TABLE _dataset_meta(manifest TEXT NOT NULL)")
                conn.execute("INSERT INTO _dataset_meta VALUES (?)", (json.dumps(manifest),))
            if fingerprint(root) != stamp:
                raise DataError("Source changed during import; retry initialization.")
            os.replace(temp, path)
            return manifest
        except (sqlite3.Error, ValueError, KeyError, csv.Error, OSError) as exc:
            raise DataError(
                "Dataset import failed; verify CSV types, keys and schema. Existing database preserved."
            ) from exc
        finally:
            temp.unlink(missing_ok=True)


@contextmanager
def readonly(path: Path, *, timeout: float = 2.0, max_steps: int = 2_000_000):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA query_only=ON")
        conn.enable_load_extension(False)
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 30_000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 200)
        deadline, steps = time.monotonic() + timeout, 0

        def progress():
            nonlocal steps
            steps += 1000
            return int(time.monotonic() > deadline or steps > max_steps)

        def authorize(action, arg1, arg2, _db, _trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and arg1 in TABLES:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in SAFE_FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn.set_authorizer(authorize)
        conn.set_progress_handler(progress, 1000)
        yield conn
    finally:
        conn.close()


def schema_context(path: Path) -> dict:
    """Trusted introspection; metadata never grants writes to the analytical connection."""
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        return {t: {r[1]: r[2] for r in conn.execute(f'PRAGMA table_info("{t}")')} for t in TABLES}


def diagnostics(path: Path) -> dict:
    with readonly(path) as conn:
        weights = [
            dict(r)
            for r in conn.execute("""
            SELECT p.portfolio_name, ROUND(SUM(h.current_weight),6) AS weight_total,
            COUNT(h.holding_id) AS holding_count FROM portfolios p
            LEFT JOIN holdings h USING(portfolio_id) GROUP BY p.portfolio_id
        """)
        ]
        coverage = {
            t: conn.execute(
                f'SELECT COUNT(DISTINCT portfolio_id) FROM "{t}"'  # noqa: S608
            ).fetchone()[0]
            for t in ("portfolio_performance", "risk_metrics")
        }
        counts = {
            t: conn.execute(
                f'SELECT COUNT(*) FROM "{t}"'  # noqa: S608
            ).fetchone()[0]
            for t in TABLES
        }
        dates = list(
            conn.execute("SELECT MIN(price_date),MAX(price_date) FROM historical_prices").fetchone()
        )
    return {
        "counts": counts,
        "expected_counts_match": counts == EXPECTED_COUNTS,
        "portfolio_weights": weights,
        "portfolio_coverage": coverage,
        "historical_price_dates": dates,
        "warnings": [
            "Snapshot prices, not live quotes.",
            "Performance and risk cover only part of the portfolio universe.",
        ],
    }
