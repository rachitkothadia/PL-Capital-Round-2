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
    finally:
        context.close()
