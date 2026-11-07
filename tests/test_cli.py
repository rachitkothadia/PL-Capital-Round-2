import json
from types import SimpleNamespace

from pl_capital.models import Answer


def test_doctor_and_initialization_are_key_safe(settings, monkeypatch, capsys):
    from pl_capital.cli import main

    monkeypatch.setenv("PL_CAPITAL_DATA_DIR", str(settings.data_root))
    monkeypatch.setenv("PL_CAPITAL_CACHE_DIR", str(settings.cache_dir))
    monkeypatch.setenv("GRAPH_BACKEND", "off")
    monkeypatch.setenv("GROQ_API_KEY", "test-private-value")
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
            return Answer(intent="sql_query", tool="sql_query", result={"columns": ["count"], "rows": [[13]]}) if question == "count" else Answer(error="Groq unavailable")
        def close(self):
            pass
    monkeypatch.setattr(cli, "PortfolioAgent", Stub)
    assert cli.main(["ask", "count", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["rows"] == [[13]]
    assert cli.main(["ask", "fail", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "Groq unavailable"


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
    assert cli.main(["--model", "openai/gpt-oss-20b", "ask", "count", "--json"]) == 0
    assert cli.main(["ask", "count", "--model", "openai/gpt-oss-20b", "--json"]) == 0
    assert calls == ["openai/gpt-oss-20b", "closed", "openai/gpt-oss-20b", "closed"]
    capsys.readouterr()


def test_json_errors_do_not_expose_private_key(monkeypatch, capsys):
    from pl_capital import cli
    from pl_capital.errors import ConfigurationError

    monkeypatch.setenv("GROQ_API_KEY", "a-private-fixture-key")

    def fail(_):
        raise ConfigurationError("API request failed safely.")

    monkeypatch.setattr(cli, "PortfolioAgent", fail)
    assert cli.main(["ask", "count", "--json"]) == 1
    output = capsys.readouterr().out
    assert "a-private-fixture-key" not in output
    assert json.loads(output)["error"] == "API request failed safely."
