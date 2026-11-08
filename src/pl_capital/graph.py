"""Optional local relationship graph; SQLite remains the numerical authority."""

import importlib
import json
import sqlite3
import sys
from contextlib import closing
from time import perf_counter

from filelock import FileLock

from pl_capital.config import Settings
from pl_capital.database import TABLES, readonly, schema_context

GRAPH_VERSION = "v1"


def _load_lite():
    """Import lazily so the core package never requires a native graph library."""
    return importlib.import_module("redislite.falkordb_client").FalkorDB


class GraphContext:
    """Own the embedded client and accept only fixed, parameterized traversals.

    No user-supplied Cypher reaches this adapter. All writes originate in the
    trusted snapshot ingestion below. Errors produce a visible SQLite fallback.
    """

    def __init__(self, settings: Settings, *, lazy: bool = False):
        self.settings = settings
        self._db = None
        self._graph = None
        self._backend = "sqlite"
        self._reason = "Graph disabled by GRAPH_BACKEND=off."
        self._graph_name = ""
        self._startup_attempted = False
        self._startup_ms = 0.0
        self._closed = False
        if settings.graph_backend == "off":
            return
        if sys.platform == "win32":
            self._reason = (
                "Native Windows uses SQLite; FalkorDBLite requires supported macOS/Linux."
            )
            return
        self._reason = (
            "Graph not started; SQLite schema is available until relationship context is needed."
        )
        if not lazy:
            self.ensure_started()

    def ensure_started(self) -> bool:
        """Start at most once; irrelevant requests never need the native server."""
        if self._graph is not None and self._backend == "falkordblite":
            return True
        if (
            self._closed
            or self._startup_attempted
            or self.settings.graph_backend == "off"
            or sys.platform == "win32"
        ):
            return False
        self._startup_attempted = True
        started = perf_counter()
        try:
            factory = _load_lite()
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.settings.cache_dir / "graph.lock"), timeout=2):
                self._db = factory(
                    str(self.settings.cache_dir / "graph.rdb"),
                    socket_timeout=2,
                    socket_connect_timeout=2,
                )
            self.synchronize()
            self._backend = "falkordblite"
            self._reason = "Local relationship graph synchronized with the SQLite snapshot."
        except Exception as exc:
            self._fallback(
                f"FalkorDBLite unavailable ({type(exc).__name__}); "
                "use uv run --extra graph pl-capital on macOS/Linux; "
                "macOS also requires libomp. SQLite remains fully operational."
            )
        finally:
            self._startup_ms = round((perf_counter() - started) * 1000, 3)
        return self._backend == "falkordblite"

    def status(self) -> dict:
        return {
            "backend": self._backend,
            "status": "ready"
            if self._backend == "falkordblite"
            else (
                "deferred"
                if not self._startup_attempted
                and not self._closed
                and self.settings.graph_backend != "off"
                and sys.platform != "win32"
                else "fallback"
            ),
            "requested": self.settings.graph_backend,
            "reason": self._reason,
            "graph": self._graph_name if self._backend == "falkordblite" else None,
            "startup_attempted": self._startup_attempted,
            "startup_ms": self._startup_ms,
        }

    def _fallback(self, reason: str) -> None:
        self.close()
        self._backend = "sqlite"
        self._reason = reason

    def synchronize(self) -> None:
        """Idempotent MERGE ingestion under a per-cache interprocess lock.

        A graph namespace includes the schema version and dataset checksum,
        preventing changed inputs from reusing obsolete relationships. The
        completion marker is written last; interrupted ingestion can be retried.
        """
        if self._db is None:
            return
        path = self.settings.db_path.resolve()
        with FileLock(str(self.settings.cache_dir / "graph.lock"), timeout=2):
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                manifest = json.loads(
                    conn.execute("SELECT manifest FROM _dataset_meta").fetchone()[0]
                )
                stamp = manifest["fingerprint"]
                links = []
                for table in TABLES:
                    links.extend(
                        {
                            "source": table,
                            "target": row[2],
                            "column": row[3],
                            "target_column": row[4],
                        }
                        for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')
                    )
            self._graph_name = f"pl_capital_{GRAPH_VERSION}_{stamp[:20]}"
            self._graph = self._db.select_graph(self._graph_name)
            # GRAPH.RO_QUERY cannot read a graph key that has never been created.
            self._graph.query(
                "MERGE (s:Snapshot {fingerprint:$stamp}) ON CREATE SET s.complete=false",
                {"stamp": stamp},
                timeout=1000,
            )
            done = self._graph.ro_query(
                "MATCH (s:Snapshot {fingerprint:$stamp}) RETURN s.complete",
                {"stamp": stamp},
                timeout=1000,
            ).result_set
            if done and done[0][0] is True:
                return
            schema = schema_context(path)
            with readonly(path) as conn:
                portfolios = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT portfolio_id AS id,portfolio_name AS name FROM portfolios"
                    )
                ]
                securities = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT security_id AS id,symbol,company_name AS name,asset_type,sector_id FROM securities"
                    )
                ]
                sectors = [
                    dict(r)
                    for r in conn.execute("SELECT sector_id AS id,sector_name AS name FROM sectors")
                ]
                holdings = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT holding_id AS id,portfolio_id,security_id FROM holdings"
                    )
                ]
            writes = [
                (
                    "UNWIND $rows AS row MERGE (n:Table {name:row.name})",
                    [{"name": t} for t in schema],
                ),
                (
                    "UNWIND $rows AS row MATCH (t:Table {name:row.table_name}) "
                    "MERGE (c:Column {key:row.key}) SET c.name=row.name,c.data_type=row.data_type "
                    "MERGE (t)-[:HAS_COLUMN]->(c)",
                    [
                        {"key": f"{t}.{c}", "table_name": t, "name": c, "data_type": typ}
                        for t, cols in schema.items()
                        for c, typ in cols.items()
                    ],
                ),
                (
                    "UNWIND $rows AS row MATCH (a:Table {name:row.source}),(b:Table {name:row.target}) "
                    "MERGE (a)-[:REFERENCES {column:row.column,target_column:row.target_column}]->(b)",
                    links,
                ),
                (
                    "UNWIND $rows AS row MERGE (p:Portfolio {id:row.id}) SET p.name=row.name",
                    portfolios,
                ),
                ("UNWIND $rows AS row MERGE (s:Sector {id:row.id}) SET s.name=row.name", sectors),
                (
                    "UNWIND $rows AS row MERGE (s:Security {id:row.id}) "
                    "SET s.name=row.name,s.symbol=row.symbol,s.asset_type=row.asset_type",
                    securities,
                ),
                (
                    "UNWIND $rows AS row MATCH (s:Security {id:row.id}),(sec:Sector {id:row.sector_id}) "
                    "MERGE (s)-[:IN_SECTOR]->(sec)",
                    [r for r in securities if r["sector_id"] is not None],
                ),
                (
                    "UNWIND $rows AS row MATCH (p:Portfolio {id:row.portfolio_id}),"
                    "(s:Security {id:row.security_id}) MERGE (p)-[:HOLDS {holding_id:row.id}]->(s)",
                    holdings,
                ),
            ]
            for query, rows in writes:
                self._graph.query(query, {"rows": rows}, timeout=2000)
            self._graph.query(
                "MERGE (s:Snapshot {fingerprint:$stamp}) SET s.complete=true,s.version=$version",
                {"stamp": stamp, "version": GRAPH_VERSION},
                timeout=1000,
            )

    def counts(self) -> dict:
        """Small diagnostic with fixed labels, never arbitrary Cypher."""
        if self._graph is None:
            return {}
        result = {}
        for label in ("Portfolio", "Security", "Sector", "Table", "Column"):
            result[label] = self._graph.ro_query(
                f"MATCH (n:{label}) RETURN count(n)",
                timeout=1000,
            ).result_set[0][0]
        result["HOLDS"] = self._graph.ro_query(
            "MATCH ()-[r:HOLDS]->() RETURN count(r)",
            timeout=1000,
        ).result_set[0][0]
        return result

    def portfolio_links(self, name: str) -> list[dict]:
        if self._graph is None:
            return []
        rows = self._graph.ro_query(
            "MATCH (p:Portfolio)-[:HOLDS]->(s:Security)-[:IN_SECTOR]->(sec:Sector) "
            "WHERE toLower(p.name)=toLower($name) "
            "RETURN p.name,s.symbol,s.asset_type,sec.name ORDER BY s.symbol LIMIT 60",
            {"name": name[:200]},
            timeout=1000,
        ).result_set
        return [
            dict(zip(("portfolio", "symbol", "asset_type", "sector"), r, strict=True)) for r in rows
        ]

    def retrieve(self, question: str) -> dict:
        from pl_capital.retrieval import retrieve

        return retrieve(self, question)

    def close(self) -> None:
        self._closed = True
        client, self._db = self._db, None
        self._graph = None
        if client is not None:
            self._backend = "sqlite"
            self._reason = "Graph connection closed; using SQLite metadata."
            try:
                client.close()
            except Exception:
                self._reason += " Graph client cleanup could not be confirmed."
