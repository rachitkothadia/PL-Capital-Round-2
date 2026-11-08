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
    parser.add_argument("--model", choices=MODELS, dest="root_model", help="Planner model (selects Groq or Gemini)")
    commands = parser.add_subparsers(dest="command")
    ask = commands.add_parser("ask", help="Ask the real model-backed portfolio agent")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="Return the typed answer as JSON")
    ask.add_argument("--trace", action="store_true", help="Show actual operational events")
    ask.add_argument("--debug", action="store_true", help="Explicitly show redacted raw diagnostics")
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
    evaluation.add_argument("--live", action="store_true", help="Explicitly permit real provider requests")
    evaluation.add_argument("--report", type=Path, help="Write an auditable JSON evaluation report")
    evaluation.add_argument("--json", action="store_true")
    evaluation.add_argument("--model", choices=MODELS)
    challenges = commands.add_parser("challenges", help="Check twenty additional challenges separately from official ground truth")
    mode = challenges.add_mutually_exclusive_group(required=True)
    mode.add_argument("--references", action="store_true", help="Compare SQL references with independent Python, without Groq")
    mode.add_argument("--live", action="store_true", help="Run the real agent, with at most twenty questions")
    challenges.add_argument("--ids", help="Comma-separated distinct question IDs, 1 through 20")
    challenges.add_argument("--limit", type=int, choices=range(21), default=20)
    challenges.add_argument("--report", type=Path)
    challenges.add_argument("--json", action="store_true")
    challenges.add_argument("--model", choices=MODELS)
    return parser


def _text(value: object, secret: str = "") -> str:
    value = str(value)
    if secret:
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?:gsk_|gh[pousr]_|sk-proj-|AIza|AQ\.)[A-Za-z0-9_-]{20,}", "[REDACTED]", value)
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
    for package in ("groq", "httpx", "textual", "sqlglot", "pydantic", "falkordblite"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed (optional)" if package == "falkordblite" else "not installed"
    return {
        "application": __version__, "python": platform.python_version(),
        "platform": platform.system(), "architecture": platform.machine(),
        "provider": settings.provider, "model": settings.model,
        "api_key": "SET" if settings.api_key else "NOT SET",
        "groq_api_key": ("SET" if settings.api_key else "NOT SET") if settings.provider == "groq" else "NOT ACTIVE",
        "gemini_api_key": ("SET" if settings.api_key else "NOT SET") if settings.provider == "gemini" else "NOT ACTIVE",
        "groq_model": settings.model if settings.provider == "groq" else None, "ready_for_live_agent": bool(settings.api_key),
        "dependencies": versions, "dataset": diagnostics(settings.db_path),
        "graph": _graph_status(settings),
        "notes": ["No API request is made by doctor; readiness indicates configuration only, not live quota or billing availability.", "SQLite is authoritative; optional graph failure does not block analytics."],
    }


def _render_answer(console: Console, answer, *, trace: bool, secret: str) -> None:
    from pl_capital.presentation import build_answer_view

    view = build_answer_view(answer)
    console.print(_text(view.headline, secret), style="bold cyan", markup=False)
    if view.table:
        table = Table(show_header=True, header_style="bold cyan")
        for column in view.table.columns:
            table.add_column(_text(column, secret), overflow="fold")
        for row in view.table.rows:
            table.add_row(*[_text(value, secret) for value in row])
        console.print(table)
        if view.table.total_rows > len(view.table.rows):
            console.print("Showing the first 8 returned rows; --json preserves the full bounded result.", markup=False)
    console.print("How this was calculated", style="bold", markup=False)
    for step in view.steps:
        console.print("• " + _text(step, secret), markup=False)
    console.print(_text(view.provenance, secret), style="dim", markup=False)
    for warning in view.warnings:
        console.print("Note: " + _text(warning, secret), style="yellow", markup=False)
    if trace:
        for section in view.sections:
            console.print(_text(section.title, secret), style="bold cyan", markup=False)
            for line in section.lines:
                console.print(_text(line, secret), markup=False)
            if section.code:
                console.print(Syntax(_text(section.code, secret), section.language, word_wrap=True))


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
            return _error(console, "Use eval --live to run the supplied questions through the real model-backed agent.", as_json=as_json)
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
        if args.command == "challenges":
            from pl_capital.challenges import _save, evaluate_challenges, verify_references
            from pl_capital.errors import ConfigurationError

            initialize(settings.data_root, settings.db_path)
            if args.references:
                result = verify_references(settings.data_root, settings.db_path)
            else:
                try:
                    ids = [int(item.strip()) for item in args.ids.split(",")] if args.ids else None
                except ValueError as exc:
                    raise ConfigurationError("Use comma-separated question IDs from 1 through 20.") from exc
                agent = PortfolioAgent(settings)
                result = evaluate_challenges(agent, live=True, ids=ids, max_questions=args.limit)
            if args.report:
                _save(args.report, result)
            if as_json:
                _json(result, settings.api_key)
            else:
                console.print(result.get("mode", "Advanced challenges"), markup=False)
                for item in result["questions"]:
                    console.print(f"{item['id']:02d} {item['status']}: {item['reason']}", markup=False)
                console.print(f"Verified passes: {result['passed']}/{result['total']}", markup=False)
                if "counts" in result:
                    console.print(json.dumps(result["counts"], sort_keys=True), markup=False)
            return 0 if result["passed"] == result["total"] else 1
        agent = PortfolioAgent(settings)
        if args.command == "ask":
            answer = agent.answer_question(args.question)
            if as_json:
                _json(answer.model_dump(mode="json"), settings.api_key)
            else:
                _render_answer(console, answer, trace=args.trace, secret=settings.api_key)
                if args.debug:
                    from pl_capital.presentation import diagnostic_payload

                    console.print(Syntax(json.dumps(diagnostic_payload(answer, settings.api_key), indent=2), "json", word_wrap=True))
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
