import json
from types import SimpleNamespace

from pl_capital.models import Answer


def test_doctor_and_initialization_are_key_safe(settings, monkeypatch, capsys):
    from pl_capital.cli import main

    monkeypatch.setenv("PL_CAPITAL_DATA_DIR", str(settings.data_root))
    monkeypatch.setenv("PL_CAPITAL_CACHE_DIR", str(settings.cache_dir))
    monkeypatch.setenv("GRAPH_BACKEND", "off")
    monkeypatch.setenv("GEMINI_API_KEY", "test-private-value")
    assert main(["doctor", "--json"]) == 0
    text = capsys.readouterr().out
    assert "test-private-value" not in text
    assert json.loads(text)["dataset"]["counts"]["portfolios"] == 13
    assert main(["init-db"]) == 0


def test_json_ask_uses_agent_and_nonzero_on_error(monkeypatch, capsys):
    from pl_capital import cli

    class Stub:
        def __init__(self, settings):
            self.settings = settings
        def answer_question(self, question):
            return Answer(intent="sql_query", tool="sql_query", result={"columns": ["count"], "rows": [[13]]}) if question == "count" else Answer(error="Gemini unavailable")
        def close(self):
            pass
    monkeypatch.setattr(cli, "PortfolioAgent", Stub)
    assert cli.main(["ask", "count", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["rows"] == [[13]]
    assert cli.main(["ask", "fail", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "Gemini unavailable"


def test_eval_requires_explicit_live(monkeypatch, capsys):
    from pl_capital.cli import main

    assert main(["eval"]) == 1
    assert "--live" in capsys.readouterr().out


def test_help_and_noninteractive_default(monkeypatch, capsys):
    from pl_capital import cli

    assert cli.main(["--help"]) == 0
    assert "init-db" in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert cli.main([]) == 1
    assert "interactive terminal" in capsys.readouterr().out


def test_model_switch_before_or_after_command(monkeypatch, capsys):
    from pl_capital import cli

    calls = []

    class Stub:
        def __init__(self, settings):
            calls.append(settings.model)
        def answer_question(self, question):
            return Answer(intent="sql_query", tool="sql_query", message="Recorded data")
        def close(self):
            calls.append("closed")

    monkeypatch.setattr(cli, "PortfolioAgent", Stub)
    assert cli.main(["--model", "gemini-2.5-flash", "ask", "count", "--json"]) == 0
    assert cli.main(["ask", "count", "--model", "gemini-2.5-flash", "--json"]) == 0
    assert calls == ["gemini-2.5-flash", "closed", "gemini-2.5-flash", "closed"]
    capsys.readouterr()


def test_challenge_references_never_construct_an_agent(settings, monkeypatch, capsys, tmp_path):
    from pl_capital import cli

    monkeypatch.setenv("PL_CAPITAL_DATA_DIR", str(settings.data_root))
    monkeypatch.setenv("PL_CAPITAL_CACHE_DIR", str(settings.cache_dir))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    def forbidden(_):
        raise AssertionError("Reference mode must not construct a model client")
    monkeypatch.setattr(cli, "PortfolioAgent", forbidden)
    report = tmp_path / "references.json"
    assert cli.main(["challenges", "--references", "--json", "--report", str(report)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] == result["total"] == 20
    assert json.loads(report.read_text())["passed"] == 20


def test_human_cli_answer_precedes_evidence_and_raw_json(capsys):
    from rich.console import Console

    from pl_capital.cli import _render_answer
    answer = Answer(
        executed_sql="SELECT COUNT(*) AS portfolio_count FROM portfolios",
        result={"columns": ["portfolio_count"], "rows": [[13]], "row_count": 1,
                "source_tables": ["portfolios"]},
    )
    _render_answer(Console(width=100, markup=False), answer, trace=True, secret="")
    output = capsys.readouterr().out
    assert output.index("13 portfolios") < output.index("Executed SQL")
    assert "secret_schema" not in output
    assert "portfolio_count = 13" in output


def test_json_errors_do_not_expose_private_key(monkeypatch, capsys):
    from pl_capital import cli
    from pl_capital.errors import ConfigurationError

    monkeypatch.setenv("GEMINI_API_KEY", "a-private-fixture-key")

    def fail(_):
        raise ConfigurationError("API request failed safely.")

    monkeypatch.setattr(cli, "PortfolioAgent", fail)
    assert cli.main(["ask", "count", "--json"]) == 1
    output = capsys.readouterr().out
    assert "a-private-fixture-key" not in output
    assert json.loads(output)["error"] == "API request failed safely."
