"""Useful, bounded relationship context; untrusted prose is never Cypher."""

import json
import re
import sqlite3
import sys
from contextlib import closing
from time import perf_counter
from typing import TYPE_CHECKING

from pl_capital.database import TABLES, readonly, schema_context

if TYPE_CHECKING:
    from pl_capital.graph import GraphContext

RETRIEVAL_BUDGET_SECONDS = 1.0
QUERY_TIMEOUT_MS = 250
MAX_CONTEXT_CHARS = 18_000
STOPWORDS = frozenset(
    "what which where when why how many much are is was were be been being the a an "
    "for from to of in on at by as it its do does did we you i my your our us have has "
    "with without total each show me find and or all that this these those about please "
    "fund funds portfolio portfolios sector sectors holdings securities calculate breakdown "
    "exposures exposure different current name names id date dates number count maybe maby".split()
)
GENERIC_NAMES = frozenset({"fund", "portfolio", "inc", "corporation", "corp", "the"})
TABLE_HINTS = {
    "portfolios": {
        "portfolio",
        "portfolios",
        "fund",
        "funds",
        "aum",
        "strategy",
        "active",
        "inactive",
        "status",
    },
    "holdings": {
        "holding",
        "holdings",
        "held",
        "weight",
        "weights",
        "allocation",
        "allocations",
        "exposure",
        "exposures",
        "overlap",
        "diversification",
        "concentration",
        "jaccard",
    },
    "securities": {
        "security",
        "securities",
        "stock",
        "stocks",
        "equity",
        "equities",
        "bond",
        "bonds",
        "symbol",
        "symbols",
        "shares",
        "coupon",
        "maturity",
        "price",
        "prices",
        "valuation",
    },
    "sectors": {"sector", "sectors", "industry", "industries"},
    "transactions": {
        "transaction",
        "transactions",
        "buy",
        "buys",
        "bought",
        "sell",
        "sells",
        "sold",
        "fees",
        "cash",
        "proceeds",
    },
    "historical_prices": {
        "historical",
        "history",
        "close",
        "closing",
        "intraday",
        "open",
        "volume",
        "streak",
        "decline",
        "declines",
    },
    "portfolio_performance": {
        "performance",
        "return",
        "returns",
        "nav",
        "sharpe",
        "volatility",
        "drawdown",
    },
    "risk_metrics": {"risk", "var", "cvar", "beta", "sortino", "correlation", "tracking"},
    "benchmarks": {"benchmark", "benchmarks"},
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"\b[a-z0-9]{2,40}\b", text.lower().replace("_", " ")[:4000])[:128]


def _one_edit(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
        return len(differences) == 1 or (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]]
        )
    longer, shorter = (left, right) if len(left) > len(right) else (right, left)
    index = next(
        (i for i, (a, b) in enumerate(zip(longer, shorter, strict=False)) if a != b), len(shorter)
    )
    return longer[:index] + longer[index + 1 :] == shorter


def _repair_tokens(tokens: list[str], vocabulary: set[str]) -> tuple[list[str], list[dict]]:
    repaired, changes = [], []
    for token in tokens:
        matches = (
            []
            if token in vocabulary or token in STOPWORDS or len(token) < 5
            else [word for word in vocabulary if len(word) >= 4 and _one_edit(token, word)]
        )
        if len(matches) == 1:
            change = {"input": token, "matched": matches[0]}
            if change not in changes and len(changes) >= 8:
                repaired.append(token)
                continue
            repaired.append(matches[0])
            if change not in changes:
                changes.append(change)
        else:
            repaired.append(token)
    return repaired, changes


def _matches(question: str, name: str) -> bool:
    words = [word for word in _tokens(name) if word not in GENERIC_NAMES]
    return bool(words) and " " + " ".join(words) + " " in " " + " ".join(_tokens(question)) + " "


def _record(keys: tuple[str, ...], row) -> dict:
    return {
        key: value[:200] if isinstance(value, str) else value
        for key, value in zip(keys, row, strict=True)
    }


def _catalog(path):
    schema = schema_context(path)
    entities, queries = [], []
    with readonly(path) as conn:
        for sql, kind, keys in (
            (
                "SELECT portfolio_id,portfolio_name FROM portfolios ORDER BY portfolio_name LIMIT 100",
                "portfolio",
                ("id", "name"),
            ),
            (
                "SELECT sector_id,sector_name FROM sectors ORDER BY sector_name LIMIT 100",
                "sector",
                ("id", "name"),
            ),
            (
                "SELECT security_id,company_name,symbol,asset_type FROM securities ORDER BY symbol LIMIT 100",
                "security",
                ("id", "name", "symbol", "asset_type"),
            ),
        ):
            queries.append(sql)
            entities.extend(dict(type=kind, **_record(keys, row)) for row in conn.execute(sql))
    return schema, entities, queries


def _request(question, schema, catalog):
    vocabulary = {word for hints in TABLE_HINTS.values() for word in hints}
    vocabulary.update(
        word
        for table, columns in schema.items()
        for name in [table, *columns]
        for word in _tokens(name.replace("_", " "))
    )
    vocabulary.update(
        word
        for entity in catalog
        for value in (entity["name"], entity.get("symbol", ""))
        for word in _tokens(value)
        if word not in GENERIC_NAMES
    )
    tokens, changes = _repair_tokens(_tokens(question), vocabulary)
    normalized, words = " ".join(tokens), set(tokens)
    entities = [
        e
        for e in catalog
        if _matches(normalized, e["name"]) or e.get("symbol", "").lower() in words
    ]
    primary = {table for table, hints in TABLE_HINTS.items() if words & hints}
    if (
        "risk" in words
        and words & {"high", "low", "target", "level"}
        and not words & {"var", "cvar", "beta", "sortino", "correlation", "tracking"}
    ):
        primary.discard("risk_metrics")
        primary.add("portfolios")
    if "historical_prices" in primary and not words & {
        "performance",
        "nav",
        "sharpe",
        "volatility",
        "drawdown",
    }:
        primary.discard("portfolio_performance")
    analytical = bool(primary) or any(e["type"] in {"portfolio", "sector"} for e in entities)
    primary.update(
        {"portfolio": "portfolios", "sector": "sectors", "security": "securities"}[e["type"]]
        for e in entities
    )
    tables = set(primary)
    if "holdings" in tables:
        tables.update(("portfolios", "securities"))
    if "transactions" in tables:
        tables.update(("portfolios", "securities"))
    if "historical_prices" in tables or "sectors" in tables:
        tables.add("securities")
    if tables & {"portfolio_performance", "risk_metrics"}:
        tables.add("portfolios")
    if any(e["type"] == "portfolio" for e in entities):
        tables.update(("portfolios", "holdings", "securities", "sectors"))
    if any(e["type"] == "security" for e in entities):
        tables.add("sectors")
    eligible = analytical and (bool(entities) or len(primary) > 1)
    return {
        "entities": entities,
        "tables": [t for t in TABLES if t in tables] or list(TABLES),
        "terms": list(
            dict.fromkeys(
                t for t in tokens if t in vocabulary and t not in STOPWORDS and not t.isdigit()
            )
        )[:16],
        "normalizations": changes,
        "eligible": eligible,
        "skip_reason": "SQLite schema is sufficient for this simple lookup; graph retrieval skipped."
        if analytical
        else "No recognized analytical context; used SQLite schema without graph retrieval.",
    }


def retrieve(context: "GraphContext", question: str) -> dict:
    started = perf_counter()
    schema, catalog, lookup_queries = _catalog(context.settings.db_path)
    request = _request(question, schema, catalog)
    queries: list[str] = []
    parameters: list[dict] = []
    attempted = False
    if (
        request["eligible"]
        and context.settings.graph_backend != "off"
        and sys.platform != "win32"
        and not context._closed
    ):
        attempted = True
        if context.ensure_started():
            try:
                result = _native(
                    context,
                    request,
                    schema,
                    queries,
                    parameters,
                    perf_counter() + RETRIEVAL_BUDGET_SECONDS,
                )
                if not result["useful_evidence"]:
                    result = _sqlite(
                        context,
                        request,
                        schema,
                        queries,
                        parameters,
                        lookup_queries,
                        "Graph retrieved no useful entity or join context; used SQLite schema fallback.",
                    )
            except Exception as exc:
                context._error_type = type(exc).__name__
                reason = (
                    "Graph retrieval time budget exhausted"
                    if isinstance(exc, TimeoutError)
                    else f"Graph retrieval failed ({type(exc).__name__})"
                )
                context._fallback(reason + "; using authoritative SQLite metadata.")
                result = _sqlite(context, request, schema, queries, parameters, lookup_queries)
        else:
            result = _sqlite(context, request, schema, queries, parameters, lookup_queries)
    else:
        reason = request["skip_reason"] if not request["eligible"] else None
        if reason and context.status()["status"] == "fallback":
            reason += " " + context.status()["reason"]
        result = _sqlite(context, request, schema, queries, parameters, lookup_queries, reason)
    result.update(
        attempted=attempted,
        retrieval_ms=round((perf_counter() - started) * 1000, 3),
        terms=request["terms"],
        normalizations=request["normalizations"],
        graph_backend=result["backend"],
        graph_used=result["used"],
        snapshot_id=context.status().get("snapshot_id") if result["used"] else None,
        fallback_reason=None if result["used"] else result["reason"],
        relationship_paths=[
            f"{j['source']}.{j['column']} -> {j['target']}.{j['target_column']}"
            for j in result["joins"]
        ]
        if result["used"]
        else [],
    )
    if result["used"] and any(e["type"] == "holding" for e in result["entities"]):
        result["relationship_paths"].insert(
            0, "Portfolio-HAS_HOLDING-Holding-OF_SECURITY-Security-IN_SECTOR-Sector"
        )
    elif result["used"] and any(e["type"] in {"sector", "security"} for e in result["entities"]):
        result["relationship_paths"].insert(0, "Security-IN_SECTOR-Sector")
    while len(json.dumps(result, ensure_ascii=False)) >= MAX_CONTEXT_CHARS and result["entities"]:
        result["entities"].pop()
    return result


def _native(context, request, full_schema, queries, parameters, deadline):
    def run(query, params, keys):
        remaining = int((deadline - perf_counter()) * 1000)
        if remaining <= 0:
            raise TimeoutError("Graph retrieval budget exhausted")
        queries.append(query)
        parameters.append(params)
        rows = context._graph.ro_query(
            query, params=params, timeout=min(QUERY_TIMEOUT_MS, remaining)
        ).result_set
        if perf_counter() > deadline:
            raise TimeoutError("Graph retrieval budget exhausted")
        return [_record(keys, row) for row in rows]

    entities = []
    for kind, label in (("portfolio", "Portfolio"), ("sector", "Sector"), ("security", "Security")):
        matches = [e for e in request["entities"] if e["type"] == kind]
        if matches:
            # Labels are fixed application constants; all request values are bound IDs.
            rows = run(
                f"MATCH (n:{label}) WHERE n.id IN $ids RETURN n.id,n.name ORDER BY n.name LIMIT 30",
                {"ids": [e["id"] for e in matches]},
                ("id", "name"),
            )
            expected = {e["id"]: e["name"] for e in matches}
            entities.extend(
                dict(type=kind, **row) for row in rows if expected.get(row["id"]) == row["name"]
            )
    portfolios = [e for e in entities if e["type"] == "portfolio"]
    sectors = [e for e in entities if e["type"] == "sector"]
    securities = [e for e in entities if e["type"] == "security"]
    if portfolios:
        rows = run(
            "MATCH (p:Portfolio)-[:HAS_HOLDING]->(h:Holding)-[:OF_SECURITY]->(s:Security) "
            "WHERE p.id IN $ids OPTIONAL MATCH (s)-[:IN_SECTOR]->(sec:Sector) "
            "RETURN p.name,h.id,s.id,s.symbol,s.asset_type,sec.name ORDER BY p.name,s.symbol LIMIT 32",
            {"ids": [p["id"] for p in portfolios]},
            ("portfolio", "holding_id", "security_id", "symbol", "asset_type", "sector"),
        )
        entities.extend(dict(type="holding", **row) for row in rows)
    if sectors or securities:
        rows = run(
            "MATCH (s:Security)-[:IN_SECTOR]->(sec:Sector) WHERE sec.id IN $sector_ids OR s.id IN $security_ids "
            "RETURN s.symbol,s.name,s.asset_type,sec.name ORDER BY s.symbol LIMIT 32",
            {
                "sector_ids": [s["id"] for s in sectors],
                "security_ids": [s["id"] for s in securities],
            },
            ("symbol", "name", "asset_type", "sector"),
        )
        entities.extend(dict(type="security", **row) for row in rows)
    tables = request["tables"]
    columns = run(
        "MATCH (t:Table)-[:HAS_COLUMN]->(c:Column) WHERE t.name IN $tables "
        "RETURN t.name,c.name,c.data_type ORDER BY t.name,c.name LIMIT 160",
        {"tables": tables},
        ("table", "column", "data_type"),
    )
    schema = {}
    for column in columns:
        schema.setdefault(column["table"], {})[column["column"]] = column["data_type"]
    if schema != {t: full_schema[t] for t in tables}:
        raise ValueError("Graph schema metadata is incomplete or inconsistent")
    joins = run(
        "MATCH (t:Table)-[r:REFERENCES]->(u:Table) WHERE t.name IN $tables AND u.name IN $tables "
        "RETURN t.name,r.column,u.name,r.target_column ORDER BY t.name,r.column LIMIT 30",
        {"tables": tables},
        ("source", "column", "target", "target_column"),
    )
    evidence = [
        f"Matched {e['type']}: {e['name']}"
        for e in entities
        if e["type"] in {"portfolio", "sector"}
    ]
    if securities:
        evidence.extend(f"Matched security: {e['name']}" for e in securities)
    if joins:
        evidence.append(f"Retrieved {len(joins)} foreign-key joins across recognized tables.")
    return {
        "backend": "falkordblite",
        "used": bool(evidence),
        "reason": "Used graph entity relationships and/or foreign-key join context.",
        "queries": queries,
        "query_parameters": parameters,
        "entities": entities[:64],
        "relevant_tables": tables,
        "schema": schema,
        "joins": joins,
        "useful_evidence": evidence[:12],
    }


def _sqlite(context, request, full_schema, queries, parameters, lookup_queries, reason=None):
    entities = list(request["entities"])
    with readonly(context.settings.db_path) as conn:
        for portfolio in [e for e in entities if e["type"] == "portfolio"][:3]:
            sql = (
                "SELECT s.symbol,s.asset_type,sec.sector_name FROM holdings h "
                "JOIN securities s USING(security_id) LEFT JOIN sectors sec USING(sector_id) "
                "WHERE h.portfolio_id=:portfolio_id ORDER BY s.symbol LIMIT 32"
            )
            queries.append(sql)
            parameters.append({"portfolio_id": portfolio["id"]})
            entities.extend(
                dict(
                    type="holding",
                    portfolio=portfolio["name"],
                    **_record(("symbol", "asset_type", "sector"), row),
                )
                for row in conn.execute(sql, {"portfolio_id": portfolio["id"]})
            )
    tables, joins = request["tables"], []
    with closing(
        sqlite3.connect(context.settings.db_path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
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
        "reason": reason or context.status()["reason"],
        "queries": queries,
        "query_parameters": parameters,
        "lookup_queries": lookup_queries,
        "entities": entities[:64],
        "relevant_tables": tables,
        "schema": {t: full_schema[t] for t in tables},
        "joins": joins,
        "useful_evidence": [],
    }
