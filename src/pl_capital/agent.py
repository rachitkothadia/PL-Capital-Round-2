"""The CLI, TUI and live evaluator all execute this same agent boundary."""

import re
import sqlite3
import time
from dataclasses import replace

from pydantic import ValidationError

from pl_capital.config import MODELS, Settings
from pl_capital.database import initialize, readonly, schema_context
from pl_capital.errors import CapitalError, DataError, EntityError, PlanningError, QueryError
from pl_capital.exposure import calculate, resolve_portfolio
from pl_capital.gemini_client import GeminiPlanner
from pl_capital.graph import GraphContext
from pl_capital.metric_validation import verify_advanced_metrics
from pl_capital.models import Answer, TraceEvent
from pl_capital.redaction import clean_text
from pl_capital.scenario import calculate_scenario
from pl_capital.sql_safety import validate, validate_audit_projection
from pl_capital.sql_tool import execute
from pl_capital.verification import (
    market_value_sector,
    validate_average_precision,
    validate_requested_output,
    verify_market_values,
)

INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)|GEMINI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|gsk_[A-Za-z0-9]+|AIza[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_-]{20,}|"
    r"(?:reveal|print|show|read)\s+(?:the\s+)?(?:secrets?|password|api.?key|\.env)|"
    r"/etc/|load_extension|readfile|\b(?:drop|delete|update|alter|attach|detach)\s+(?:table|from|database)|"
    r"(?:run|execute)\s+(?:a\s+)?(?:shell|bash|python|command)",
    re.I,
)
ADVICE = re.compile(
    r"(?:which|what).{0,40}should\s+I.{0,30}(?:buy|sell|invest)|"
    r"should\s+I\s+(?:buy|sell|invest)|recommend.{0,30}(?:stock|investment)|"
    r"invest\s+my|best\s+stock.{0,20}buy",
    re.I,
)


class PortfolioAgent:
    def __init__(self, settings: Settings, *, planner=None):
        self.settings = settings
        initialize(settings.data_root, settings.db_path)
        self.graph = GraphContext(settings, lazy=True)
        self._planner = planner
        self.live = planner is None
        self.previous_portfolio = None

    def reset_context(self):
        self.previous_portfolio = None

    def set_model(self, model: str):
        if model not in MODELS:
            raise PlanningError("Choose a documented Gemini model.")
        if self._planner is not None:
            self._planner.set_model(model)
        self.settings = replace(self.settings, model=model)

    def _context(self, question: str) -> dict:
        retrieved = self.graph.retrieve(question)
        with readonly(self.settings.db_path) as conn:
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT portfolio_name FROM portfolios ORDER BY portfolio_name"
                )
            ]
            sectors = [
                r[0] for r in conn.execute("SELECT sector_name FROM sectors ORDER BY sector_name")
            ]
            risks = [
                r[0] for r in conn.execute("SELECT DISTINCT target_risk_level FROM portfolios")
            ]
            statuses = [r[0] for r in conn.execute("SELECT DISTINCT status FROM portfolios")]
            currencies = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT currency FROM securities WHERE currency IS NOT NULL"
                )
            ]
            source_dates = {}
            for table, column in (
                ("historical_prices", "price_date"),
                ("portfolio_performance", "performance_date"),
                ("risk_metrics", "calculation_date"),
            ):
                source_dates[table] = list(
                    conn.execute(f"SELECT MIN({column}),MAX({column}) FROM {table}").fetchone()  # noqa: S608 -- fixed schema identifiers above
                )
        return {
            "schema": schema_context(self.settings.db_path),
            "retrieval": retrieved,
            "portfolio_names": names,
            "sector_names": sectors,
            "target_risk_levels": risks,
            "portfolio_statuses": statuses,
            "asset_types": ["Stock", "Bond"],
            "currency": currencies[0] if len(currencies) == 1 else None,
            "source_dates": source_dates,
            "limitations": [
                "Historical snapshot prices",
                "Incomplete performance/risk coverage",
                "Recorded portfolio weights can be incomplete",
            ],
        }

    def answer_question(self, question: str) -> Answer:
        start = time.perf_counter()
        answer = Answer(
            question=clean_text(question, self.settings.api_key)
            if isinstance(question, str)
            else "",
            assumptions=[
                "Supplied historical snapshot; security current_price is not a live quote."
            ],
        )

        def event(stage, detail, data=None):
            answer.trace.append(
                TraceEvent(
                    stage=stage,
                    detail=detail,
                    data=data or {},
                    elapsed_ms=round((time.perf_counter() - start) * 1000, 3),
                )
            )

        try:
            if not isinstance(question, str) or not question.strip() or len(question) > 4000:
                answer.status = "needs_clarification"
                answer.message = "Enter a question between 1 and 4000 characters."
                return answer
            if INJECTION.search(question):
                answer.intent = "out_of_domain"
                answer.status = "out_of_domain"
                answer.message = "This tool supports read-only portfolio analytics. Secret access, file access and policy overrides are outside its scope."
                event("boundary", "Untrusted instruction rejected before planning.")
                return answer
            if ADVICE.search(question):
                answer.intent = "out_of_domain"
                answer.status = "out_of_domain"
                answer.message = "Personal investment recommendations are outside this tool's scope. Ask for descriptive analysis of the supplied holdings."
                event("boundary", "Personal investment advice is unsupported.")
                return answer
            # Re-check source identity but never silently replace an existing database.
            initialize(self.settings.data_root, self.settings.db_path)
            context = self._context(question)
            retrieved = context["retrieval"]
            answer.source_dates = context["source_dates"]
            answer.currency = context["currency"]
            event(
                "retrieval",
                "Relationship graph context used."
                if retrieved["used"]
                else "SQLite metadata fallback.",
                retrieved,
            )
            if not retrieved["used"] and retrieved.get("attempted"):
                answer.warnings.append(retrieved.get("reason", "Graph unavailable; SQLite used."))
            if self._planner is None:
                self._planner = GeminiPlanner(self.settings)
            event(
                "planning",
                f"Requesting typed intent and SQL plan from {self.settings.provider}."
                if self.live
                else "Offline test: injected planner.",
                {"model": self.settings.model, "provider": self.settings.provider},
            )
            plan = self._planner.plan(
                question.strip(), context, previous_portfolio=self.previous_portfolio
            )
            event("classification", "Validated structured tool selection.", {"intent": plan.intent})
            answer.intent, answer.tool = (
                plan.intent,
                plan.intent
                if plan.intent in {"sql_query", "exposure_calculator", "scenario_analysis"}
                else None,
            )
            if plan.intent in {
                "clarification_needed",
                "out_of_scope",
                "needs_clarification",
                "unsupported_analysis",
                "missing_data",
                "out_of_domain",
            }:
                answer.status = {
                    "clarification_needed": "needs_clarification",
                    "out_of_scope": "out_of_domain",
                }.get(plan.intent, plan.intent)
                answer.message = (
                    plan.message
                    or "Specify a descriptive question about the supplied portfolio dataset."
                )
                return answer
            if plan.intent == "scenario_analysis":
                if plan.scenario is None:
                    answer.status = "needs_clarification"
                    answer.message = "Specify sector price changes, such as Technology -22%, and the portfolios to analyze."
                    return answer
                answer.result = calculate_scenario(self.settings.db_path, plan.scenario)
                answer.currency = answer.result.get("currency")
                answer.assumptions = answer.result.get("assumptions", [])
                answer.warnings.extend(answer.result.get("warnings", []))
                answer.status = "success"
                answer.message = f"Hypothetical scenario: {len(answer.result['portfolios'])} portfolios calculated from supplied holdings."
                event(
                    "calculation",
                    "Deterministic Decimal price shocks; no model arithmetic or AUM denominator.",
                    answer.result,
                )
            elif plan.intent == "exposure_calculator":
                entity = plan.portfolio or self.previous_portfolio
                if not entity:
                    raise EntityError("Which portfolio should the exposure calculator analyze?")
                result = calculate(self.settings.db_path, entity)
                answer.result = result.model_dump(mode="json")
                answer.status = "success"
                answer.warnings.extend(result.warnings)
                self.previous_portfolio = result.portfolio_name
                event(
                    "calculation",
                    "Decimal stock-only aggregation; bond holdings excluded.",
                    answer.result,
                )
                answer.message = (
                    f"{result.portfolio_name}: {len(result.sectors)} equity sectors; "
                    f"recorded equity weight {float(result.equity_weight_total) * 100:.2f}%. "
                    "Whole-portfolio contribution and equity-normalized exposure use separate denominators."
                    if result.status == "ok"
                    else f"{result.portfolio_name} has no positive-weight equity holdings. Bonds are excluded."
                )
            elif plan.intent == "sql_query":
                for attempt in range(2):
                    try:
                        if plan.intent != "sql_query" or not plan.sql:
                            raise QueryError("A SQL correction must remain a SELECT plan.")
                        params = {p.name: p.value for p in plan.parameters}
                        if len(params) != len(plan.parameters):
                            raise QueryError("Duplicate SQL parameter names are not permitted.")
                        answer.sql, answer.parameters = plan.sql, params
                        # A SQL plan can compare several named funds; the optional
                        # context label must not turn that set into a single entity.
                        named_portfolios = [
                            name
                            for name in context["portfolio_names"]
                            if plan.portfolio and name.casefold() in plan.portfolio.casefold()
                        ]
                        resolved_portfolio = (
                            resolve_portfolio(self.settings.db_path, plan.portfolio)[1]
                            if plan.portfolio and len(named_portfolios) < 2
                            else None
                        )
                        event(
                            "sql_generation",
                            "Model-generated SQL received as untrusted data.",
                            {"sql": plan.sql, "parameters": params},
                        )
                        sql, tables = validate(plan.sql, params, context["schema"])
                        validate_average_precision(sql, question)
                        validate_requested_output(sql, question)
                        if market_value_sector(question, context["sector_names"]) is not None:
                            validate_audit_projection(sql, question=question)
                        event(
                            "validation",
                            "Single SELECT, schema, functions and bindings validated.",
                            {"source_tables": tables},
                        )
                        result = execute(self.settings.db_path, sql, params)
                        event(
                            "execution",
                            "Read-only SQLite query executed; acceptance checks follow.",
                            {"sql": sql, "parameters": params, **result.model_dump(mode="json")},
                        )
                        checked = verify_market_values(
                            self.settings.db_path,
                            question,
                            context["sector_names"],
                            result.model_dump(mode="json"),
                        )
                        if checked:
                            event(
                                "metric_verification",
                                "Sector market values, all-holding denominator, percentage units and portfolio membership independently checked.",
                            )
                        metric_checks = verify_advanced_metrics(
                            self.settings.db_path, question, result.model_dump(mode="json")
                        )
                        if metric_checks:
                            event(
                                "metric_verification",
                                "Independent raw-source financial checks passed.",
                                {"checks": metric_checks},
                            )
                        answer.result = result.model_dump(mode="json")
                        answer.status = "success" if result.rows else "empty_result"
                        answer.sql = answer.executed_sql = sql
                        answer.executed_parameters = dict(params)
                        if "transactions" in result.source_tables:
                            answer.assumptions.append(
                                "Recorded transaction cash movement is not verified realized P&L; tax-lot accounting evidence is not supplied."
                            )
                        if "portfolio_performance" in result.source_tables:
                            answer.assumptions.append(
                                "Observed NAV change is not necessarily total investment return; missing observations are not filled."
                            )
                        if result.truncated:
                            answer.warnings.append(
                                "Result truncated at the configured row cap; narrow your query."
                            )
                        if not result.rows:
                            answer.message = "No matching records exist in the supplied snapshot."
                        elif len(result.rows) == len(result.columns) == 1:
                            answer.message = f"{result.columns[0]}: {result.rows[0][0] if result.rows[0][0] is not None else 'No data'}"
                        else:
                            answer.message = f"Found {result.row_count} matching record{'s' if result.row_count != 1 else ''} in the supplied snapshot."
                        observation_tables = set(result.source_tables) & {
                            "portfolio_performance",
                            "risk_metrics",
                        }
                        requested_names = [
                            name
                            for name in context["portfolio_names"]
                            if name.casefold() in question.casefold()
                        ]
                        if resolved_portfolio and resolved_portfolio not in requested_names:
                            requested_names.append(resolved_portfolio)
                        if (
                            observation_tables
                            and requested_names
                            and re.search(
                                r"latest|nav|sharpe|beta|volatil|performance|value.at.risk",
                                question,
                                re.I,
                            )
                            and not re.search(r"missing|coverage|count|how many", question, re.I)
                        ):
                            unavailable = []
                            with readonly(self.settings.db_path) as conn:
                                for table in sorted(observation_tables):
                                    for name in requested_names:
                                        # Table identifiers are a fixed allowlist; fund names remain bound values.
                                        count = conn.execute(
                                            f"SELECT COUNT(*) FROM {table} o JOIN portfolios p USING(portfolio_id) WHERE p.portfolio_name=?",  # noqa: S608 -- fixed table allowlist above
                                            (name,),
                                        ).fetchone()[0]
                                        if not count:
                                            unavailable.append(f"{table}: {name}")
                            if unavailable:
                                answer.status = "missing_data"
                                answer.message = (
                                    "Requested observations are absent from the supplied snapshot: "
                                    + "; ".join(unavailable)
                                    + ". Missing observations are not zero."
                                )
                                event("coverage", answer.message, {"unavailable": unavailable})
                        if resolved_portfolio:
                            self.previous_portfolio = resolved_portfolio
                        break
                    except QueryError as exc:
                        event(
                            "validation_error",
                            "Query failed validation or execution limits; no result accepted.",
                            {"error": str(exc), "attempt": attempt + 1},
                        )
                        if attempt:
                            raise
                        plan = self._planner.plan(
                            question.strip(),
                            context,
                            previous_portfolio=self.previous_portfolio,
                            correction={
                                "sql": plan.sql,
                                "error": str(exc),
                                "instruction": "Correct the SELECT once. Preserve requested intent and result columns.",
                            },
                        )
            usage = getattr(self._planner, "last_usage", {})
            event(
                "verification",
                "Answer values come from deterministic tools, not model arithmetic.",
                {"token_usage": usage},
            )
            return answer
        except ValidationError:
            answer.status = "needs_clarification"
            answer.message = "Invalid scenario inputs: use finite fractional shocks between -1 and 10, valid names and no executable expressions."
            return answer
        except DataError as exc:
            answer.status = (
                "missing_data"
                if re.search(r"missing|unavailable|lacks|cannot read", str(exc), re.I)
                else "tool_error"
            )
            answer.message = str(exc)
            answer.error = str(exc) if answer.status == "tool_error" else None
            return answer
        except EntityError as exc:
            answer.status = "needs_clarification"
            answer.intent, answer.tool = "clarification_needed", None
            answer.message = str(exc)
            event(
                "clarification",
                "Portfolio resolution requires clarification.",
                {"message": str(exc)},
            )
            return answer
        except CapitalError as exc:
            answer.status = "tool_error"
            answer.error = answer.message = str(exc)
            event(
                "error",
                "Analysis stopped safely.",
                {"error": str(exc), "provider_failure": getattr(self._planner, "last_failure", {})},
            )
            return answer
        except (sqlite3.Error, OSError, ValueError, TypeError, RuntimeError) as exc:
            answer.status = "tool_error"
            answer.error = answer.message = (
                f"Analysis unavailable ({type(exc).__name__}); run doctor and retry."
            )
            event("error", "Unexpected boundary failure; internal details withheld.")
            return answer
        finally:
            if answer.status == "needs_clarification" and answer.error:
                answer.status = "tool_error"
            if answer.status not in {"success", "empty_result"}:
                answer.next_step = {
                    "needs_clarification": "Specify the missing portfolio, dates or fractional shock parameters.",
                    "missing_data": "Use available snapshot observations or supply the missing source data.",
                    "unsupported_analysis": "Use supported SQL, recorded exposure or sector price-shock analysis.",
                    "out_of_domain": "Ask a descriptive question about the supplied portfolio snapshot.",
                    "tool_error": "Check doctor and the recorded validation error; retry after correcting the service or input issue.",
                }.get(answer.status, "Review the request and retry.")
            event(
                "outcome",
                "Canonical execution outcome.",
                {"status": answer.status, "next_step": answer.next_step},
            )
            answer.elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

    def close(self):
        self.graph.close()
        if self._planner is not None:
            self._planner.close()
