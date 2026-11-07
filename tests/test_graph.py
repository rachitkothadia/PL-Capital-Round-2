"""Graph tests distinguish real native traversal from portable fallback."""

import importlib.util
import sys
from pathlib import Path

import pytest

from pl_capital.config import Settings
from pl_capital.database import initialize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path):
    result = Settings(ROOT, tmp_path, graph_backend="auto")
    initialize(result.data_root, result.db_path)
    return result


def test_graph_off_never_imports_native(settings, monkeypatch):
    from dataclasses import replace

    from pl_capital import graph

    def forbidden():
        raise AssertionError("Native backend must not load when off")

    monkeypatch.setattr(graph, "_load_lite", forbidden)
    context = graph.GraphContext(replace(settings, graph_backend="off"))
    assert context.status()["backend"] == "sqlite"
    assert "disabled" in context.status()["reason"].lower()
    context.close()


def test_unavailable_native_is_actionable_and_safe(settings, monkeypatch):
    from dataclasses import replace

    from pl_capital import graph

    def unavailable():
        raise ImportError("simulated missing optional dependency")

    monkeypatch.setattr(graph, "_load_lite", unavailable)
    for backend in ("auto", "lite"):
        context = graph.GraphContext(replace(settings, graph_backend=backend))
        status = context.status()
        assert status["backend"] == "sqlite"
        assert status["status"] == "fallback"
        assert "--extra graph" in status["reason"]
        assert status["requested"] == backend
        context.close()


def test_native_windows_uses_explicit_sqlite_fallback(settings, monkeypatch):
    from pl_capital import graph

    monkeypatch.setattr(graph.sys, "platform", "win32")
    context = graph.GraphContext(settings)
    assert "Windows" in context.status()["reason"]
    assert context.status()["backend"] == "sqlite"


def test_sqlite_retrieval_has_real_schema_entities_and_no_graph_claim(settings):
    import json
    from dataclasses import replace

    from pl_capital.graph import GraphContext

    context = GraphContext(replace(settings, graph_backend="off"))
    data = context.retrieve("Sector exposures for international equity")
    assert data["used"] is False
    assert data["backend"] == "sqlite"
    assert "disabled" in data["reason"].lower()
    assert any(e.get("name") == "International Equity Fund" for e in data["entities"])
    assert data["schema"]["holdings"]["current_weight"] == "REAL"
    assert set(data["relevant_tables"]) >= {"holdings", "securities", "sectors", "portfolios"}
    assert len(json.dumps(data)) < 20_000
    assert data["queries"]


@pytest.mark.graph
def test_native_retrieval_targets_entity_sector_and_schema(settings):
    from pl_capital.graph import GraphContext

    if sys.platform == "win32" or importlib.util.find_spec("redislite") is None:
        pytest.skip("Optional FalkorDBLite dependency unavailable on this platform")
    context = GraphContext(settings)
    try:
        assert context.status()["backend"] == "falkordblite", context.status()["reason"]
        entity = context.retrieve("What are sector exposures for International Equity Fund?")
        assert entity["used"] is True
        assert entity["backend"] == "falkordblite"
        assert any(e.get("name") == "International Equity Fund" for e in entity["entities"])
        assert any(e.get("sector") == "Energy" for e in entity["entities"])
        assert entity["schema"]["securities"]["current_price"] == "REAL"
        assert any("HAS_COLUMN" in q for q in entity["queries"])
        assert entity["joins"]
        sector = context.retrieve("Which securities are in the Technology sector?")
        assert sector["used"] is True
        assert any(e.get("name") == "Technology" for e in sector["entities"])
        assert any(e.get("symbol") == "AAPL" for e in sector["entities"])
        assert all("MERGE" not in q and "CREATE" not in q for q in sector["queries"])
    finally:
        context.close()


@pytest.mark.graph
def test_midquery_graph_outage_falls_back_and_sql_still_works(settings, monkeypatch):
    from pl_capital.graph import GraphContext
    from pl_capital.sql_tool import execute

    if sys.platform == "win32" or importlib.util.find_spec("redislite") is None:
        pytest.skip("Optional FalkorDBLite dependency unavailable on this platform")
    context = GraphContext(settings)
    try:
        assert context.status()["backend"] == "falkordblite", context.status()["reason"]

        def down(*args, **kwargs):
            raise ConnectionError("simulated graph transport outage")

        monkeypatch.setattr(context._graph, "ro_query", down)
        result = context.retrieve("Technology holdings for International Equity Fund")
        assert result["used"] is False
        assert result["backend"] == "sqlite"
        assert "ConnectionError" in result["reason"]
        assert result["schema"]["portfolios"]["portfolio_name"] == "TEXT"
        assert execute(settings.db_path, "SELECT COUNT(*) FROM portfolios", {}).rows == [[13]]
        assert context.status()["backend"] == "sqlite"
    finally:
        context.close()


@pytest.mark.graph
def test_user_cypher_text_cannot_mutate_graph_or_escape_context_budget(settings):
    import json

    from pl_capital.graph import GraphContext

    if sys.platform == "win32" or importlib.util.find_spec("redislite") is None:
        pytest.skip("Optional FalkorDBLite dependency unavailable on this platform")
    context = GraphContext(settings)
    try:
        assert context.status()["backend"] == "falkordblite", context.status()["reason"]
        before = context.counts()
        question = "Technology'; MATCH (n) DETACH DELETE n // " + "Technology " * 1000
        result = context.retrieve(question)
        assert result["used"] is True
        assert all("DELETE" not in q and "DETACH" not in q for q in result["queries"])
        assert context.counts() == before
        assert len(json.dumps(result)) < 20_000
        assert max(len(p.get("terms", [])) for p in result["query_parameters"]) <= 16
    finally:
        context.close()


@pytest.mark.graph
def test_real_graph_traversal_and_repeat_ingestion_are_idempotent(settings):
    from pl_capital.graph import GraphContext

    if sys.platform == "win32" or importlib.util.find_spec("redislite") is None:
        pytest.skip("Optional FalkorDBLite dependency unavailable on this platform")
    context = GraphContext(settings)
    try:
        assert context.status()["backend"] == "falkordblite", context.status()["reason"]
        first = context.counts()
        assert first["Portfolio"] == 13
        assert first["Security"] == 30
        assert first["Sector"] == 10
        assert first["HOLDS"] == 95
        rows = context.portfolio_links("International Equity Fund")
        assert rows
        assert {r["sector"] for r in rows} >= {"Technology", "Energy", "Automotive"}
        assert all(r["portfolio"] == "International Equity Fund" for r in rows)
        context.synchronize()
        assert context.counts() == first
        context.close()
        assert context.status()["backend"] == "sqlite"
        fallback = context.retrieve("International Equity Fund")
        assert fallback["used"] is False
        assert "closed" in fallback["reason"]
    finally:
        context.close()
