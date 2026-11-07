"""Bounded relationship retrieval; questions never become executable Cypher."""

import json
import re
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from pl_capital.database import TABLES, readonly, schema_context

if TYPE_CHECKING:
    from pl_capital.graph import GraphContext

STOPWORDS = frozenset(
    "what which where how many are the for from have has with total each show me "
    "find and all our that this about fund funds portfolio portfolios sector sectors "
    "holdings securities calculate breakdown exposures exposure different".split()
)
GENERIC_NAMES = frozenset({"fund", "portfolio", "inc", "corporation", "corp", "the"})


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,40}", text.lower()[:4000])


def _matches(question: str, name: str) -> bool:
    words = [w for w in _tokens(name) if w not in GENERIC_NAMES]
    return bool(words) and " ".join(words) in " ".join(_tokens(question))


def _tables(question: str, entities: list[dict]) -> list[str]:
    words = set(_tokens(question))
    selected = set()
    if words & {"portfolio", "portfolios", "fund", "funds", "aum", "active", "inactive"}:
        selected.add("portfolios")
    if words & {
        "holding",
        "holdings",
        "exposure",
        "exposures",
        "sector",
        "sectors",
        "diversification",
    }:
        selected.update(("portfolios", "holdings", "securities", "sectors"))
    if words & {"security", "securities", "stock", "stocks", "bond", "bonds", "price", "prices"}:
        selected.update(("securities", "sectors"))
    for table, hints in {
        "transactions": {"transaction", "transactions", "buy", "sell", "fees"},
        "historical_prices": {"historical", "history", "close", "volume"},
        "portfolio_performance": {
            "performance",
            "return",
            "returns",
            "nav",
            "sharpe",
            "volatility",
        },
        "risk_metrics": {"risk", "var", "cvar", "beta", "sortino", "tracking"},
        "benchmarks": {"benchmark", "benchmarks"},
    }.items():
        if words & hints:
            selected.add(table)
    if any(e["type"] == "portfolio" for e in entities):
        selected.update(("portfolios", "holdings", "securities", "sectors"))
    if not selected:
        selected.update(TABLES)
    return [t for t in TABLES if t in selected]


def _record(keys: tuple[str, ...], row) -> dict:
    return {k: v[:200] if isinstance(v, str) else v for k, v in zip(keys, row, strict=True)}


def retrieve(context: "GraphContext", question: str) -> dict:
    """Return graph evidence or explicit introspected SQLite evidence on outage."""
    queries: list[str] = []
    parameters: list[dict] = []
    if context.status()["backend"] == "falkordblite" and context._graph is not None:
        try:
            result = _native(context, question, queries, parameters)
        except Exception as exc:
            context._fallback(
                f"Graph retrieval failed ({type(exc).__name__}); using authoritative SQLite metadata."
            )
            result = _sqlite(context, question, queries, parameters)
    else:
        result = _sqlite(context, question, queries, parameters)
    # Keep complete schema/queries; trim only optional discovery hints if needed.
    while len(json.dumps(result, ensure_ascii=False)) >= 20_000 and result["entities"]:
        result["entities"].pop()
    return result


def _native(context, question, queries, parameters):
    graph = context._graph
    terms = list(dict.fromkeys(w for w in _tokens(question) if w not in STOPWORDS))[:16]

    def run(query, params, keys):
        queries.append(query)
        parameters.append(params)
        rows = graph.ro_query(query, params=params, timeout=1000).result_set
        return [_record(keys, row) for row in rows]

    portfolios = run(
        "MATCH (p:Portfolio) WHERE any(term IN $terms WHERE toLower(p.name) CONTAINS term) "
        "RETURN p.id,p.name ORDER BY p.name LIMIT 30",
        {"terms": terms},
        ("id", "name"),
    )
    sectors = run(
        "MATCH (s:Sector) WHERE any(term IN $terms WHERE toLower(s.name) CONTAINS term) "
        "RETURN s.id,s.name ORDER BY s.name LIMIT 20",
        {"terms": terms},
        ("id", "name"),
    )
    portfolios = [p for p in portfolios if _matches(question, p["name"])]
    sectors = [s for s in sectors if _matches(question, s["name"])]
    entities = [dict(type="portfolio", **p) for p in portfolios]
    entities += [dict(type="sector", **s) for s in sectors]
    if portfolios:
        links = run(
            "MATCH (p:Portfolio)-[:HOLDS]->(s:Security)-[:IN_SECTOR]->(sec:Sector) "
            "WHERE p.id IN $ids RETURN p.name,s.symbol,s.asset_type,sec.name "
            "ORDER BY p.name,s.symbol LIMIT 32",
            {"ids": [p["id"] for p in portfolios]},
            ("portfolio", "symbol", "asset_type", "sector"),
        )
        entities.extend(dict(type="holding", **row) for row in links)
    if sectors:
        securities = run(
            "MATCH (s:Security)-[:IN_SECTOR]->(sec:Sector) WHERE sec.id IN $ids "
            "RETURN s.symbol,s.name,s.asset_type,sec.name ORDER BY s.symbol LIMIT 32",
            {"ids": [s["id"] for s in sectors]},
            ("symbol", "name", "asset_type", "sector"),
        )
        entities.extend(dict(type="security", **row) for row in securities)
    tables = _tables(question, entities)
    columns = run(
        "MATCH (t:Table)-[:HAS_COLUMN]->(c:Column) WHERE t.name IN $tables "
        "RETURN t.name,c.name,c.data_type ORDER BY t.name,c.name LIMIT 160",
        {"tables": tables},
        ("table", "column", "data_type"),
    )
    schema = {}
    for column in columns:
        schema.setdefault(column["table"], {})[column["column"]] = column["data_type"]
    if set(schema) != set(tables):
        raise ValueError("Graph schema metadata is incomplete")
    joins = run(
        "MATCH (t:Table)-[r:REFERENCES]->(u:Table) "
        "WHERE t.name IN $tables AND u.name IN $tables "
        "RETURN t.name,r.column,u.name,r.target_column ORDER BY t.name,r.column LIMIT 30",
        {"tables": tables},
        ("source", "column", "target", "target_column"),
    )
    return {
        "backend": "falkordblite",
        "used": True,
        "reason": context.status()["reason"],
        "queries": queries,
        "query_parameters": parameters,
        "entities": entities[:64],
        "relevant_tables": tables,
        "schema": schema,
        "joins": joins,
    }


def _sqlite(context, question, queries, parameters):
    path = context.settings.db_path
    full_schema = schema_context(path)
    entities = []
    portfolios = []
    with readonly(path) as conn:
        for sql, kind in (
            (
                "SELECT portfolio_id,portfolio_name FROM portfolios ORDER BY portfolio_name LIMIT 50",
                "portfolio",
            ),
            ("SELECT sector_id,sector_name FROM sectors ORDER BY sector_name LIMIT 30", "sector"),
        ):
            queries.append(sql)
            parameters.append({})
            for row in conn.execute(sql):
                if _matches(question, row[1]):
                    entity = {"type": kind, "id": row[0], "name": row[1][:200]}
                    entities.append(entity)
                    if kind == "portfolio":
                        portfolios.append(entity)
        for p in portfolios[:3]:
            sql = (
                "SELECT s.symbol,s.asset_type,sec.sector_name FROM holdings h "
                "JOIN securities s USING(security_id) LEFT JOIN sectors sec USING(sector_id) "
                "WHERE h.portfolio_id=:portfolio_id ORDER BY s.symbol LIMIT 32"
            )
            queries.append(sql)
            parameters.append({"portfolio_id": p["id"]})
            entities.extend(
                dict(
                    type="holding",
                    portfolio=p["name"],
                    **_record(("symbol", "asset_type", "sector"), row),
                )
                for row in conn.execute(sql, {"portfolio_id": p["id"]})
            )
    tables = _tables(question, entities)
    joins = []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        for table in tables:
            sql = f'PRAGMA foreign_key_list("{table}")'
            queries.append(sql)
            parameters.append({})
            joins.extend(
                {"source": table, "column": row[3], "target": row[2], "target_column": row[4]}
                for row in conn.execute(sql)
                if row[2] in tables
            )
    return {
        "backend": "sqlite",
        "used": False,
        "reason": context.status()["reason"],
        "queries": queries,
        "query_parameters": parameters,
        "entities": entities[:64],
        "relevant_tables": tables,
        "schema": {t: full_schema[t] for t in tables},
        "joins": joins,
    }
