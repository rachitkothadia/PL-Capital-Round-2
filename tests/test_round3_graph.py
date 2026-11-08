"""Native evidence and injected failures are intentionally tested separately."""

import importlib.util
import json
import sqlite3
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pl_capital import graph
from pl_capital.sql_tool import execute


def test_missing_package_health_is_precise_and_sqlite_still_works(settings, monkeypatch):
    monkeypatch.setattr(graph.sys, "platform", "darwin")

    def missing():
        raise ModuleNotFoundError("No module named 'redislite'")

    monkeypatch.setattr(graph, "_load_lite", missing)
    context = graph.GraphContext(replace(settings, graph_backend="auto"))
    health = context.health()
    assert health["backend"] == "sqlite"
    assert health["native_ready"] is False
    assert health["error_type"] == "ModuleNotFoundError"
    assert "uv sync --locked" in health["reason"]
    assert health["graph_used"] is False
    assert execute(settings.db_path, "SELECT COUNT(*) FROM portfolios", {}).rows == [[13]]


def test_native_loader_failure_has_actionable_libomp_hint(settings, monkeypatch):
    monkeypatch.setattr(graph.sys, "platform", "darwin")

    def broken():
        raise OSError("Library not loaded: /opt/homebrew/opt/libomp/lib/libomp.dylib")

    monkeypatch.setattr(graph, "_load_lite", broken)
    context = graph.GraphContext(replace(settings, graph_backend="auto"))
    result = context.health()
    assert result["error_type"] == "OSError"
    assert "brew install libomp" in result["reason"]
    assert not result["native_ready"]


def test_fingerprint_tracks_sqlite_rows_not_only_import_manifest(settings):
    before = graph.snapshot_fingerprint(settings.db_path)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE securities SET current_price=current_price+1 WHERE security_id=1")
    assert graph.snapshot_fingerprint(settings.db_path) != before


def test_rebuild_unavailable_does_not_delete_files(settings, monkeypatch):
    monkeypatch.setattr(graph.sys, "platform", "linux")  # Exercise package failure independently of host support.
    marker = settings.cache_dir / "unrelated.rdb"
    marker.write_bytes(b"private unrelated user data")
    sqlite_bytes = settings.db_path.read_bytes()
    monkeypatch.setattr(graph, "_load_lite", lambda: (_ for _ in ()).throw(ImportError()))
    result = graph.GraphContext(replace(settings, graph_backend="auto")).build(rebuild=True)
    assert not result["native_ready"]
    assert result["error_type"] == "ImportError"
    assert marker.read_bytes() == b"private unrelated user data"
    assert settings.db_path.read_bytes() == sqlite_bytes


def test_health_read_failure_never_claims_ready(settings, monkeypatch):
    context = graph.GraphContext(replace(settings, graph_backend="off"))
    context._graph = SimpleNamespace(
        ro_query=lambda *a, **kw: (_ for _ in ()).throw(ConnectionError())
    )
    context._backend = "falkordblite"
    result = context.health()
    assert not result["native_ready"]
    assert not result["graph_used"]
    assert result["backend"] == "sqlite"


@pytest.fixture
def native_context(settings):
    if sys.platform not in {"darwin", "linux"} or importlib.util.find_spec("redislite") is None:
        pytest.skip("Supported native FalkorDBLite installation required")
    context = graph.GraphContext(replace(settings, graph_backend="auto"))
    try:
        assert context.status()["backend"] == "falkordblite", context.status()
        yield context
    finally:
        context.close()


@pytest.mark.graph
def test_real_health_holding_paths_and_cypher_read_write(native_context, settings):
    context = native_context
    before = context.counts()
    assert before["Holding"] == 95
    assert before["HOLDS"] == 95  # Preserved direct Portfolio -> Security relationship.
    assert before["HAS_HOLDING"] == before["OF_SECURITY"] == 95
    result = context._graph.query(
        "MERGE (n:HealthProbe {id:$id}) SET n.value=$value RETURN n.value",
        {"id": "round3", "value": 42},
        timeout=1000,
    )
    assert result.result_set == [[42]]
    assert context._graph.ro_query(
        "MATCH (n:HealthProbe {id:$id}) RETURN n.value",
        {"id": "round3"},
        timeout=1000,
    ).result_set == [[42]]
    context._graph.query("MATCH (n:HealthProbe {id:$id}) DELETE n", {"id": "round3"}, timeout=1000)
    health = context.health()
    assert health["native_ready"] is True
    assert health["graph_used"] is True
    assert health["sample_cypher"]["rows"]
    assert health["counts"] == before
    assert health["sync_status"] in {"synchronized", "unchanged"}
    for question in (
        "Growth Equity Fund holdings",
        "Technology stocks",
        "International Equity Fund sectors",
        "Compare portfolio risk_metrics with portfolio_performance",
    ):
        result = context.retrieve(question)
        assert result["graph_used"] and result["used"], result
        assert result["graph_backend"] == "falkordblite"
        assert result["snapshot_id"] == health["snapshot_id"]
        assert result["relationship_paths"]
        assert len(json.dumps(result)) < 20_000
    assert execute(settings.db_path, "SELECT COUNT(*) FROM portfolios", {}).rows == [[13]]


@pytest.mark.graph
def test_native_repeated_starts_refresh_rebuild_preserve_other_graphs(native_context, settings):
    context = native_context
    initial = context.counts()
    original = context.status()["snapshot_id"]
    context.synchronize()
    assert context.counts() == initial
    context._db.select_graph("unrelated_user_graph").query(
        "MERGE (:Private {value:7})", timeout=1000
    )
    context.build(rebuild=True)
    assert context.counts() == initial
    assert context._db.select_graph("unrelated_user_graph").ro_query(
        "MATCH (n:Private) RETURN n.value", timeout=1000
    ).result_set == [[7]]
    context.close()
    again = graph.GraphContext(replace(settings, graph_backend="auto"))
    try:
        assert again.status()["snapshot_id"] == original
        assert again.counts() == initial
        with sqlite3.connect(settings.db_path) as conn:
            conn.execute(
                "UPDATE sectors SET sector_name='Technology Refreshed' WHERE sector_name='Technology'"
            )
        result = again.retrieve("Technology Refreshed stocks")
        assert result["used"], result
        assert again.status()["snapshot_id"] != original
        assert any(e.get("name") == "Technology Refreshed" for e in result["entities"])
        assert again.counts() == initial
    finally:
        again.close()


@pytest.mark.graph
def test_incomplete_native_namespace_rebuilds_without_touching_sqlite(native_context, settings):
    context = native_context
    before = settings.db_path.read_bytes()
    counts = context.counts()
    context._graph.query("MATCH (h:Holding {id:$id}) DETACH DELETE h", {"id": 1}, timeout=1000)
    assert context.counts()["Holding"] == 94
    health = context.health()
    assert not health["native_ready"]
    assert health["backend"] == "sqlite"
    assert health["error_type"] == "ValueError"
    assert context.build(rebuild=True)["native_ready"]
    assert context.counts() == counts
    assert settings.db_path.read_bytes() == before


@pytest.mark.graph
def test_native_evidence_reaches_planner_and_answer_uses_sqlite(native_context, settings):
    from pl_capital.agent import PortfolioAgent
    from pl_capital.models import Parameter, Plan

    class EvidencePlanner:
        last_usage = {}

        def plan(self, question, context, **kwargs):
            retrieved = context["retrieval"]
            assert retrieved["graph_used"]
            assert retrieved["snapshot_id"] == native_context.status()["snapshot_id"]
            matched = next(e for e in retrieved["entities"] if e["type"] == "portfolio")
            assert matched["name"] == "Growth Equity Fund"
            # Graph-grounded identity controls the SQLite parameter; price/value never comes from graph.
            return Plan(
                intent="sql_query",
                sql="SELECT portfolio_name FROM portfolios WHERE portfolio_id=:id",
                parameters=[Parameter(name="id", value=matched["id"])],
                portfolio=None,
                message=None,
            )

        def close(self):
            pass

    agent = PortfolioAgent(replace(settings, graph_backend="off"), planner=EvidencePlanner())
    agent.graph.close()
    agent.graph = native_context
    try:
        answer = agent.answer_question("Show Growth Equity Fund portfolio name")
        assert answer.error is None, answer.error
        assert answer.result["rows"] == [["Growth Equity Fund"]]
        assert any(e.stage == "retrieval" and e.data["graph_used"] for e in answer.trace)
    finally:
        agent.close()
