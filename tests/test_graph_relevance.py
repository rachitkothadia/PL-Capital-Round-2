"""Graph context must help the question, not merely report a running backend."""

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from pl_capital.config import Settings
from pl_capital.database import initialize
from pl_capital.graph import GraphContext

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def graph_settings(tmp_path):
    settings = Settings(ROOT, tmp_path, graph_backend="auto")
    initialize(settings.data_root, settings.db_path)
    return settings


def test_noisy_simple_count_never_starts_graph(graph_settings, monkeypatch):
    from pl_capital import graph

    def forbidden():
        raise AssertionError("Simple counts do not need a native graph")

    monkeypatch.setattr(graph, "_load_lite", forbidden)
    context = GraphContext(graph_settings, lazy=True)
    result = context.retrieve("how maby portfolios do we have?")
    assert result["used"] is False
    assert result["attempted"] is False
    assert result["backend"] == "sqlite"
    assert result["relevant_tables"] == ["portfolios"]
    assert "simple" in result["reason"].lower()
    assert not {"maby", "do", "we"}.intersection(result["terms"])
    assert context.status()["startup_attempted"] is False
    assert result["retrieval_ms"] >= 0


def test_unrelated_question_has_no_useful_graph_claim(graph_settings, monkeypatch):
    from pl_capital import graph

    def forbidden():
        raise AssertionError("Unrelated prose must not start a graph")

    monkeypatch.setattr(graph, "_load_lite", forbidden)
    context = GraphContext(graph_settings, lazy=True)
    for question in (
        "What is the meaning of a birthday cake?",
        "Tell me about biotechnology cupcakes",
    ):
        result = context.retrieve(question)
        assert result["used"] is False
        assert result["attempted"] is False
        assert result["useful_evidence"] == []
        assert result["entities"] == []
        assert not result["normalizations"]


def test_fuzzy_repair_requires_one_unique_known_token():
    from pl_capital.retrieval import _repair_tokens

    assert _repair_tokens(["alphx"], {"alpha", "alphi"}) == (["alphx"], [])
    assert _repair_tokens(["maby"], {"nav", "market", "portfolio"}) == (["maby"], [])
    tokens, changes = _repair_tokens(["tecnology"], {"technology", "energy"})
    assert tokens == ["technology"]
    assert changes == [{"input": "tecnology", "matched": "technology"}]


def test_typo_normalization_evidence_is_bounded():
    from pl_capital.retrieval import _repair_tokens

    vocabulary = {"portfolio", "technology", "automotive", "consumer", "international", "innovation",
                  "dividend", "balanced", "conservative", "growth", "allocation", "benchmark"}
    words = sorted(vocabulary)
    tokens, changes = _repair_tokens([word + "z" for word in words], vocabulary)
    assert len(changes) <= 8
    assert len(tokens) == len(words)


def test_known_company_in_nonanalytical_question_does_not_start_graph(graph_settings, monkeypatch):
    from pl_capital import graph

    def forbidden():
        raise AssertionError("A company name alone is not useful graph context")

    monkeypatch.setattr(graph, "_load_lite", forbidden)
    context = GraphContext(graph_settings, lazy=True)
    result = context.retrieve("Who founded Apple and what is its logo color?")
    assert result["attempted"] is False
    assert result["used"] is False


def test_graph_without_entity_or_join_evidence_is_not_claimed_used(graph_settings):
    from types import SimpleNamespace

    from pl_capital.database import schema_context

    schema = schema_context(graph_settings.db_path)

    class MetadataOnlyGraph:
        def ro_query(self, query, params, timeout):
            assert 0 < timeout <= 250
            rows = []
            if "HAS_COLUMN" in query:
                rows = [[t, c, kind] for t in params["tables"] for c, kind in schema[t].items()]
            return SimpleNamespace(result_set=rows)

    context = GraphContext(graph_settings, lazy=True)
    context._graph = MetadataOnlyGraph()  # Explicit local test double, never live graph evidence.
    context._backend = "falkordblite"
    result = context.retrieve("Sector exposures for International Equity Fund")
    assert result["attempted"] is True
    assert result["used"] is False
    assert result["backend"] == "sqlite"
    assert result["useful_evidence"] == []
    assert "no useful" in result["reason"].lower()


def test_simple_count_keeps_platform_fallback_and_skip_reason(graph_settings, monkeypatch):
    from pl_capital import graph

    monkeypatch.setattr(graph.sys, "platform", "win32")
    context = GraphContext(graph_settings, lazy=True)
    result = context.retrieve("How many portfolios do we have?")
    assert result["attempted"] is False
    assert "simple" in result["reason"].lower()
    assert "Windows" in result["reason"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Average current prices of equities in each industry", {"securities", "sectors"}),
        ("Historical equity closing-price returns", {"historical_prices", "securities"}),
        ("High target risk AUM for active funds", {"portfolios"}),
        ("Compare risk_metrics with portfolio_performance by portfolio_id", {"risk_metrics", "portfolio_performance", "portfolios"}),
        (
            "Recorded sells and cash proceeds per portfolio",
            {"transactions", "portfolios", "securities"},
        ),
    ],
)
def test_schema_synonyms_do_not_add_unrelated_tables(graph_settings, question, expected):
    context = GraphContext(replace(graph_settings, graph_backend="off"), lazy=True)
    result = context.retrieve(question)
    assert set(result["schema"]) == expected
    assert result["used"] is False


def test_off_backend_reports_relevance_without_native_attempt(graph_settings):
    context = GraphContext(replace(graph_settings, graph_backend="off"), lazy=True)
    result = context.retrieve("Latest common performance and risk date for every portfolio")
    assert result["attempted"] is False
    assert result["used"] is False
    assert {"portfolio_performance", "risk_metrics", "portfolios"} <= set(result["schema"])
    assert "disabled" in result["reason"].lower()
    assert len(json.dumps(result)) < 20_000


@pytest.mark.graph
def test_native_entity_typo_and_join_only_context_are_useful(graph_settings):
    if sys.platform == "win32" or importlib.util.find_spec("redislite") is None:
        pytest.skip("Optional FalkorDBLite dependency unavailable on this platform")
    context = GraphContext(graph_settings, lazy=True)
    try:
        first = context.retrieve("Which securities are in the Tecnology sector?")
        assert first["used"] is True, first["reason"]
        assert first["attempted"] is True
        assert any(e.get("symbol") == "AAPL" for e in first["entities"])
        assert first["normalizations"] == [{"input": "tecnology", "matched": "technology"}]
        assert first["useful_evidence"]
        assert context.status()["startup_attempted"] is True
        second = context.retrieve("Latest common risk and performance date for each portfolio")
        assert second["used"] is True
        assert not second["entities"]
        assert second["joins"]
        assert any("join" in s.lower() for s in second["useful_evidence"])
        assert len(json.dumps(second)) < 20_000
        assert all("MERGE" not in q for q in second["queries"])
    finally:
        context.close()


@pytest.mark.graph
def test_exhausted_graph_budget_returns_sqlite_without_partial_success(graph_settings, monkeypatch):
    from pl_capital import retrieval

    if sys.platform == "win32" or importlib.util.find_spec("redislite") is None:
        pytest.skip("Optional FalkorDBLite dependency unavailable on this platform")
    context = GraphContext(graph_settings)
    try:
        monkeypatch.setattr(retrieval, "RETRIEVAL_BUDGET_SECONDS", 0.0)
        result = context.retrieve("Technology sector holdings")
        assert result["used"] is False
        assert result["attempted"] is True
        assert result["backend"] == "sqlite"
        assert "budget" in result["reason"].lower()
        assert result["schema"]["securities"]["current_price"] == "REAL"
    finally:
        context.close()


@pytest.mark.graph
def test_slow_supported_startup_does_not_spend_read_query_budget(graph_settings, monkeypatch):
    import time

    from pl_capital import graph

    if sys.platform == "win32" or importlib.util.find_spec("redislite") is None:
        pytest.skip("Optional FalkorDBLite dependency unavailable on this platform")
    factory = graph._load_lite()

    def delayed_factory(*args, **kwargs):
        time.sleep(1.05)
        return factory(*args, **kwargs)

    monkeypatch.setattr(graph, "_load_lite", lambda: delayed_factory)
    context = GraphContext(graph_settings, lazy=True)
    try:
        result = context.retrieve("Technology sector securities")
        assert result["used"] is True, result["reason"]
        assert context.status()["startup_ms"] >= 1000
        assert result["retrieval_ms"] >= context.status()["startup_ms"]
    finally:
        context.close()
