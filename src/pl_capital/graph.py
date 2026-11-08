"""Optional local relationship graph; SQLite remains the numerical authority."""

import hashlib
import importlib
import json
import platform
import re
import sqlite3
import sys
from contextlib import closing
from importlib.metadata import PackageNotFoundError, version
from time import perf_counter
from uuid import uuid4

from filelock import FileLock

from pl_capital.config import Settings
from pl_capital.database import TABLES

GRAPH_VERSION = "v2"


def _snapshot(path):
    """Read one consistent SQLite snapshot, including actual rows, never just its import manifest."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        schema, tables, links = {}, {}, []
        for table in TABLES:
            schema[table] = {r[1]: r[2] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            # Identifiers come only from the application's fixed TABLES allowlist.
            sql = f'SELECT * FROM "{table}" ORDER BY rowid'  # noqa: S608
            tables[table] = [dict(r) for r in conn.execute(sql)]
            links.extend(
                dict(source=table, target=r[2], column=r[3], target_column=r[4])
                for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')
            )
    payload = dict(version=GRAPH_VERSION, schema=schema, tables=tables, links=links)
    stamp = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return stamp, schema, tables, links


def snapshot_fingerprint(path) -> str:
    return _snapshot(path)[0]


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
        self._snapshot_id = None
        self._sync_status = "not_started"
        self._error_type = None
        self._package_imported = False
        self._source_counts = {}
        self._storage_name = f"graph-{GRAPH_VERSION}.rdb"
        pointer = settings.cache_dir / "graph-store.json"
        if pointer.is_file():
            try:
                name = json.loads(pointer.read_text())["filename"]
                if re.fullmatch(r"graph-v2(?:-recovery-[a-f0-9]{12})?\.rdb", name):
                    self._storage_name = name
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Ignore an invalid cache pointer; never follow arbitrary user paths.
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
            try:
                self.synchronize()
                return True
            except Exception as exc:
                self._error_type = type(exc).__name__
                self._fallback(
                    f"Graph synchronization failed ({self._error_type}); using SQLite metadata. Run pl-capital graph rebuild to retry."
                )
                return False
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
            self._package_imported = True
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.settings.cache_dir / "graph.lock"), timeout=2):
                self._db = factory(
                    str(self.settings.cache_dir / self._storage_name),
                    socket_timeout=2,
                    socket_connect_timeout=2,
                )
            self.synchronize()
            self._backend = "falkordblite"
            self._error_type = None
            self._reason = "Local relationship graph synchronized with the SQLite snapshot."
        except Exception as exc:
            self._error_type = type(exc).__name__
            self._fallback(
                f"FalkorDBLite unavailable ({type(exc).__name__}); "
                "run uv sync --locked on supported macOS/Linux "
                "(uv sync --extra graph --locked remains compatible); "
                "on macOS run brew install libomp if the native loader reports libomp missing. "
                "Use pl-capital graph rebuild for a damaged graph cache. SQLite remains fully operational."
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
            "schema_version": GRAPH_VERSION,
            "snapshot_id": self._snapshot_id,
            "sync_status": self._sync_status,
            "error_type": self._error_type,
        }

    def _fallback(self, reason: str) -> None:
        self.close()
        self._backend = "sqlite"
        self._reason = reason

    def synchronize(self, *, rebuild: bool = False) -> None:
        """Idempotent MERGE ingestion under a per-cache interprocess lock.

        A graph namespace includes the schema version and actual SQLite checksum,
        preventing changed inputs from reusing obsolete relationships. The
        completion marker is written last; interrupted ingestion can be retried.
        """
        if self._db is None:
            return
        path = self.settings.db_path.resolve()
        with FileLock(str(self.settings.cache_dir / "graph.lock"), timeout=2):
            stamp, schema, tables, links = _snapshot(path)
            self._source_counts = {
                "Portfolio": len(tables["portfolios"]),
                "Holding": len(tables["holdings"]),
                "Security": len(tables["securities"]),
                "Sector": len(tables["sectors"]),
                "Table": len(schema),
                "Column": sum(map(len, schema.values())),
                "HOLDS": len(tables["holdings"]),
                "HAS_HOLDING": len(tables["holdings"]),
                "OF_SECURITY": len(tables["holdings"]),
                "REFERENCES": len(links),
                "HAS_COLUMN": sum(map(len, schema.values())),
                "IN_SECTOR": sum(r["sector_id"] is not None for r in tables["securities"]),
            }
            graph_name = f"pl_capital_{GRAPH_VERSION}_{stamp[:20]}"
            if not rebuild and self._graph is not None and self._graph_name == graph_name:
                self._sync_status = "unchanged"
                return
            candidate = self._db.select_graph(graph_name)
            # Only this deterministic, application-owned namespace may be rebuilt.
            # Other graph keys and every SQLite/source file remain untouched.
            if rebuild:
                candidate.query("MATCH (n) DETACH DELETE n", timeout=2000)
            # GRAPH.RO_QUERY cannot read a graph key that has never been created.
            candidate.query(
                "MERGE (s:Snapshot {fingerprint:$stamp}) ON CREATE SET s.complete=false",
                {"stamp": stamp},
                timeout=1000,
            )
            done = candidate.ro_query(
                "MATCH (s:Snapshot {fingerprint:$stamp}) RETURN s.complete",
                {"stamp": stamp},
                timeout=1000,
            ).result_set
            if done and done[0][0] is True:
                if self._counts(candidate) != self._source_counts:
                    raise ValueError(
                        "Graph completion marker disagrees with SQLite; rebuild required"
                    )
                self._graph, self._graph_name = candidate, graph_name
                self._snapshot_id, self._sync_status = stamp, "unchanged"
                return
            portfolios = [
                dict(id=r["portfolio_id"], name=r["portfolio_name"]) for r in tables["portfolios"]
            ]
            securities = [
                dict(
                    id=r["security_id"],
                    name=r["company_name"],
                    symbol=r["symbol"],
                    asset_type=r["asset_type"],
                    sector_id=r["sector_id"],
                )
                for r in tables["securities"]
            ]
            sectors = [dict(id=r["sector_id"], name=r["sector_name"]) for r in tables["sectors"]]
            holdings = [
                dict(
                    id=r["holding_id"], portfolio_id=r["portfolio_id"], security_id=r["security_id"]
                )
                for r in tables["holdings"]
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
                (
                    "UNWIND $rows AS row MATCH (p:Portfolio {id:row.portfolio_id}),"
                    "(s:Security {id:row.security_id}) MERGE (h:Holding {id:row.id}) "
                    "SET h.portfolio_id=row.portfolio_id,h.security_id=row.security_id "
                    "MERGE (p)-[:HAS_HOLDING]->(h) MERGE (h)-[:OF_SECURITY]->(s)",
                    holdings,
                ),
            ]
            for query, rows in writes:
                candidate.query(query, {"rows": rows}, timeout=2000)
            candidate.query(
                "MERGE (s:Snapshot {fingerprint:$stamp}) SET s.complete=true,s.version=$version",
                {"stamp": stamp, "version": GRAPH_VERSION},
                timeout=1000,
            )
            # Persist before publishing the completed snapshot in this context.
            self._db.client.save()
            self._graph, self._graph_name = candidate, graph_name
            self._snapshot_id, self._sync_status = stamp, "synchronized"

    def counts(self) -> dict:
        """Small diagnostic with fixed labels, never arbitrary Cypher."""
        if self._graph is None:
            return {}
        return self._counts(self._graph)

    @staticmethod
    def _counts(graph) -> dict:
        result = {}
        for label in ("Portfolio", "Holding", "Security", "Sector", "Table", "Column"):
            result[label] = graph.ro_query(
                f"MATCH (n:{label}) RETURN count(n)",
                timeout=1000,
            ).result_set[0][0]
        for label in (
            "HOLDS",
            "HAS_HOLDING",
            "OF_SECURITY",
            "IN_SECTOR",
            "HAS_COLUMN",
            "REFERENCES",
        ):
            result[label] = graph.ro_query(
                f"MATCH ()-[r:{label}]->() RETURN count(r)",
                timeout=1000,
            ).result_set[0][0]
        return result

    def health(self) -> dict:
        """JSON-safe diagnostics; readiness requires actual Cypher and useful retrieval."""
        self.ensure_started()
        try:
            installed_version = version("falkordblite")
        except PackageNotFoundError:
            installed_version = None
        result = dict(
            **self.status(),
            python_version=platform.python_version(),
            python_executable=sys.executable,
            platform=sys.platform,
            architecture=platform.machine(),
            package_version=installed_version,
            import_ok=self._package_imported,
            native_ready=False,
            graph_used=False,
            counts={},
            node_count=None,
            edge_count=None,
            sample_cypher=None,
        )
        if self._graph is None:
            return result
        try:
            result["counts"] = self.counts()
            if self._source_counts and result["counts"] != self._source_counts:
                raise ValueError("Incomplete graph; node or edge counts differ from SQLite.")
            result["node_count"] = self._graph.ro_query(
                "MATCH (n) RETURN count(n)", timeout=1000
            ).result_set[0][0]
            result["edge_count"] = self._graph.ro_query(
                "MATCH ()-[r]->() RETURN count(r)", timeout=1000
            ).result_set[0][0]
            query = (
                "MATCH (p:Portfolio)-[:HAS_HOLDING]->(h:Holding)-[:OF_SECURITY]->(s:Security) "
                "WHERE p.name=$name "
                "OPTIONAL MATCH (s)-[:IN_SECTOR]->(sec:Sector) "
                "RETURN p.name,h.id,s.symbol,sec.name ORDER BY h.id LIMIT 3"
            )
            params = {"name": "Growth Equity Fund"}
            rows = self._graph.ro_query(query, params, timeout=1000).result_set
            result["sample_cypher"] = dict(query=query, parameters=params, rows=rows)
            evidence = self.retrieve("Technology stocks held by Growth Equity Fund")
            result.update(self.status())
            result["native_ready"] = bool(rows) and evidence["used"]
            result["graph_used"] = evidence["used"]
            result["sample_retrieval"] = {
                k: evidence[k]
                for k in ("backend", "used", "entities", "joins", "useful_evidence", "retrieval_ms")
            }
        except Exception as exc:
            self._error_type = type(exc).__name__
            self._fallback(
                f"Graph health query failed ({self._error_type}); run pl-capital graph rebuild. SQLite remains operational."
            )
            result.update(self.status())
        return result

    def build(self, *, rebuild: bool = False) -> dict:
        """Synchronize derived graph only; preserve unrelated graphs and corrupt stores."""
        if (
            rebuild
            and self._db is None
            and self.settings.graph_backend != "off"
            and sys.platform in {"darwin", "linux"}
        ):
            # Recovery uses a fresh private store, leaving the damaged bytes intact.
            self._storage_name = f"graph-v2-recovery-{uuid4().hex[:12]}.rdb"
            self._closed, self._startup_attempted = False, False
        if self.ensure_started():
            try:
                self.synchronize(rebuild=rebuild)
                if "recovery" in self._storage_name:
                    pointer = self.settings.cache_dir / "graph-store.json"
                    temporary = pointer.with_suffix(f".{uuid4().hex}.tmp")
                    temporary.write_text(json.dumps({"filename": self._storage_name}))
                    temporary.replace(pointer)
            except Exception as exc:
                self._error_type = type(exc).__name__
                self._fallback(
                    f"Graph build failed ({self._error_type}); using authoritative SQLite."
                )
        return self.health()

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
