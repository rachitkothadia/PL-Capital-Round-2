"""Cross-platform CLI. Financial questions always use the shared portfolio agent."""

import argparse
import importlib.metadata
import json
import platform
import re
import sys
from contextlib import suppress
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from pl_capital import __version__
from pl_capital.agent import PortfolioAgent
from pl_capital.config import MODELS, Settings
from pl_capital.database import diagnostics, initialize
from pl_capital.errors import CapitalError
from pl_capital.graph import GraphContext


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auditable portfolio analytics over a historical snapshot.")
    parser.add_argument("--version", action="version", version=f"pl-capital {__version__}")
    parser.add_argument("--model", choices=MODELS, dest="root_model", help="Groq planner model")
    commands = parser.add_subparsers(dest="command")
    ask = commands.add_parser("ask", help="Ask the real Groq-backed portfolio agent")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="Return the typed answer as JSON")
    ask.add_argument("--trace", action="store_true", help="Show actual operational events")
    ask.add_argument("--model", choices=MODELS)
    init = commands.add_parser("init-db", help="Atomically initialize the supplied SQLite snapshot")
    init.add_argument("--rebuild", action="store_true", help="Explicitly replace a changed snapshot after validation")
    init.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Diagnose data, dependencies, key presence and graph status")
    doctor.add_argument("--json", action="store_true")
    graph = commands.add_parser("graph", help="Inspect the actual optional graph backend")
    graph.add_argument("action", nargs="?", choices=["status"], default="status")
    graph.add_argument("--json", action="store_true")
    evaluation = commands.add_parser("eval", help="Evaluate all supplied questions through the real agent")
    evaluation.add_argument("--live", action="store_true", help="Explicitly permit real Groq requests")
    evaluation.add_argument("--report", type=Path, help="Write an auditable JSON evaluation report")
    evaluation.add_argument("--json", action="store_true")
    evaluation.add_argument("--model", choices=MODELS)
    return parser


def _text(value: object, secret: str = "") -> str:
    value = str(value)
    if secret:
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?:gsk_|gh[pousr]_|sk-proj-)[A-Za-z0-9_-]{20,}", "[REDACTED]", value)
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)


def _scrub(value, secret: str = ""):
    if isinstance(value, dict):
        return {_text(k, secret): _scrub(v, secret) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v, secret) for v in value]
    return _text(value, secret) if isinstance(value, str) else value


def _json(value, secret: str = "") -> None:
    print(json.dumps(_scrub(value, secret), ensure_ascii=True, allow_nan=False, indent=2))


def _error(console: Console, message: str, *, as_json: bool, secret: str = "") -> int:
    if as_json:
        _json({"error": message}, secret)
    else:
        console.print(_text(message, secret), style="bold red", markup=False)
    return 1


def _graph_status(settings: Settings) -> dict:
    context = GraphContext(settings)
    try:
        status = context.status()
        try:
            status["counts"] = context.counts()
        except Exception:
            status.update(backend="sqlite", status="fallback", counts={},
                          reason="Graph diagnostics unavailable; SQLite analytics remain operational.")
        return status
    finally:
        context.close()


def _doctor(settings: Settings) -> dict:
    initialize(settings.data_root, settings.db_path)
    versions = {}
    for package in ("groq", "textual", "sqlglot", "pydantic", "falkordblite"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed (optional)" if package == "falkordblite" else "not installed"
    return {
        "application": __version__, "python": platform.python_version(),
        "platform": platform.system(), "architecture": platform.machine(),
        "groq_api_key": "SET" if settings.api_key else "NOT SET",
        "groq_model": settings.model, "ready_for_live_agent": bool(settings.api_key),
        "dependencies": versions, "dataset": diagnostics(settings.db_path),
        "graph": _graph_status(settings),
        "notes": ["No API request is made by doctor.", "SQLite is authoritative; optional graph failure does not block analytics."],
    }


def _render_answer(console: Console, answer, *, trace: bool, secret: str) -> None:
    console.print("PL Capital · historical snapshot analytics", style="bold cyan", markup=False)
    if answer.message or answer.error:
        console.print(_text(answer.error or answer.message, secret), markup=False)
    result = answer.result
    if result.get("columns"):
        table = Table(show_header=True, header_style="bold cyan")
        for column in result["columns"]:
            table.add_column(_text(column, secret))
        for row in result.get("rows", [])[:50]:
            table.add_row(*[_text("NULL" if value is None else value, secret) for value in row])
        console.print(table)
        if len(result.get("rows", [])) > 50:
            console.print("Showing first 50 returned rows; --json contains the complete bounded result.", markup=False)
        console.print(f"Returned rows: {result.get('row_count', len(result.get('rows', [])))} · {answer.elapsed_ms:.1f} ms", markup=False)
    if "sectors" in result:
        table = Table("Sector", "Whole portfolio (%)", "Equity normalized (%)", header_style="bold cyan")
        for sector in result["sectors"]:
            table.add_row(_text(sector["sector"], secret), f"{sector['whole_portfolio_pct']:.6f}",
                          f"{sector['equity_normalized_pct']:.6f}")
        console.print(table)
        console.print(
            f"Equity weight: {result['equity_weight_total']} · Bond weight: {result['bond_weight_total']} · "
            f"All recorded weights: {result['all_recorded_weights_total']}\n"
            f"{result['equity_holding_count']} stock holdings; {result['bond_exclusion_count']} bond holdings excluded.\n"
            "Whole = sector stock weight × 100; normalized = sector stock weight / total stock weight × 100.", markup=False,
        )
    if answer.sql:
        console.print("Executed SQL" if result.get("columns") else "Proposed SQL", style="bold", markup=False)
        console.print(Syntax(_text(answer.sql, secret), "sql", word_wrap=True))
        console.print("Bound parameters: " + json.dumps(_scrub(answer.parameters, secret)), markup=False)
        if result.get("source_tables"):
            console.print("Sources: " + ", ".join(result["source_tables"]), markup=False)
    for warning in dict.fromkeys(answer.warnings):
        console.print("Note: " + _text(warning, secret), style="yellow", markup=False)
    if trace:
        console.print("Execution trace · operational events only", style="bold cyan", markup=False)
        for index, event in enumerate(answer.trace, 1):
            console.print(_text(f"{index:02d}. {event.stage} · {event.elapsed_ms:.1f} ms · {event.detail}", secret), markup=False)
            if event.data:
                console.print(Syntax(json.dumps(_scrub(event.data, secret), indent=2), "json", word_wrap=True))


def _render_evaluation(console: Console, result: dict) -> None:
    table = Table("Question", "Type", "Difficulty", "Result", "Reason", header_style="bold cyan")
    for item in result["questions"]:
        table.add_row(str(item["id"]), item["type"], item["difficulty"],
                      "PASS" if item["passed"] else "FAIL", _text(item["reason"]))
    console.print(table)
    console.print(f"Live agent accuracy: {result['passed']}/{result['total']} ({result['accuracy']:.1%})", markup=False)


def main(argv: list[str] | None = None) -> int:
    console = Console(markup=False)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    as_json = getattr(args, "json", False)
    settings, agent = None, None
    try:
        if args.command == "eval" and not args.live:
            return _error(console, "Use eval --live to run the supplied questions through the real Groq agent.", as_json=as_json)
        if args.command is None and not sys.stdin.isatty():
            return _error(console, "The TUI requires an interactive terminal. Run uv run pl-capital ask \"your question\" or uv run pl-capital --help.", as_json=False)
        settings = Settings.from_env(model=getattr(args, "model", None) or args.root_model)
        if args.command == "init-db":
            result = initialize(settings.data_root, settings.db_path, rebuild=args.rebuild)
            if as_json:
                _json(result, settings.api_key)
            else:
                console.print("SQLite snapshot initialized and validated.", markup=False)
                console.print(json.dumps(result["counts"], sort_keys=True), markup=False)
            return 0
        if args.command in {"doctor", "graph"}:
            if args.command == "doctor":
                result = _doctor(settings)
            else:
                initialize(settings.data_root, settings.db_path)
                result = _graph_status(settings)
            if as_json:
                _json(result, settings.api_key)
            else:
                console.print(Syntax(json.dumps(_scrub(result, settings.api_key), indent=2), "json", word_wrap=True))
            return 0
        agent = PortfolioAgent(settings)
        if args.command == "ask":
            answer = agent.answer_question(args.question)
            if as_json:
                _json(answer.model_dump(mode="json"), settings.api_key)
            else:
                _render_answer(console, answer, trace=args.trace, secret=settings.api_key)
            return 1 if answer.error else 0
        if args.command == "eval":
            from pl_capital.evaluator import evaluate

            report = args.report or settings.cache_dir / "evaluation.json"
            result = evaluate(agent, settings.data_root, report=report, live=True)
            if as_json:
                _json(result, settings.api_key)
            else:
                _render_evaluation(console, result)
            return 0 if result["total"] and result["passed"] == result["total"] else 1
        from pl_capital.tui.app import CapitalApp

        CapitalApp(agent).run()
        return 0
    except KeyboardInterrupt:
        return 130
    except CapitalError as exc:
        return _error(console, str(exc), as_json=as_json, secret=settings.api_key if settings else "")
    except Exception as exc:
        return _error(console, f"Operation unavailable ({type(exc).__name__}); run pl-capital doctor and retry.",
                      as_json=as_json, secret=settings.api_key if settings else "")
    finally:
        if agent is not None:
            # Cleanup must never corrupt an already emitted machine-readable response.
            with suppress(Exception):
                agent.close()


if __name__ == "__main__":
    raise SystemExit(main())
