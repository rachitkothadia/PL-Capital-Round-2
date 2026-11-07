"""The CLI, TUI and live evaluator all execute this same agent boundary."""

import re
import sqlite3
import time
from dataclasses import replace

from pl_capital.config import MODELS, Settings
from pl_capital.database import initialize, readonly, schema_context
from pl_capital.errors import CapitalError, EntityError, PlanningError, QueryError
from pl_capital.exposure import calculate, resolve_portfolio
from pl_capital.graph import GraphContext
from pl_capital.groq_client import GroqPlanner
from pl_capital.models import Answer, TraceEvent
from pl_capital.sql_safety import validate
from pl_capital.sql_tool import execute

INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)|GROQ_API_KEY|gsk_[A-Za-z0-9]+|"
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
        self.graph = GraphContext(settings)
        self._planner = planner
        self.live = planner is None
        self.previous_portfolio = None

    def reset_context(self):
        self.previous_portfolio = None

    def set_model(self, model: str):
        if model not in MODELS:
            raise PlanningError("Choose openai/gpt-oss-120b or openai/gpt-oss-20b.")
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
        return {
            "schema": schema_context(self.settings.db_path),
            "retrieval": retrieved,
            "portfolio_names": names,
            "sector_names": sectors,
            "target_risk_levels": risks,
            "portfolio_statuses": statuses,
            "asset_types": ["Stock", "Bond"],
            "limitations": [
                "Historical snapshot prices",
                "Incomplete performance/risk coverage",
                "Recorded portfolio weights can be incomplete",
            ],
        }

    def answer_question(self, question: str) -> Answer:
        start = time.perf_counter()
        answer = Answer(warnings=["Historical snapshot analytics; prices are not live quotes."])

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
                raise PlanningError("Enter a question between 1 and 4000 characters.")
            if INJECTION.search(question):
                answer.intent = "out_of_scope"
                answer.message = "This tool supports read-only portfolio analytics. Secret access, file access and policy overrides are outside its scope."
                event("boundary", "Untrusted instruction rejected before planning.")
                return answer
            if ADVICE.search(question):
                answer.intent = "out_of_scope"
                answer.message = "Personal investment recommendations are outside this tool's scope. Ask for descriptive analysis of the supplied holdings."
                event("boundary", "Personal investment advice is unsupported.")
                return answer
            # Re-check source identity but never silently replace an existing database.
            initialize(self.settings.data_root, self.settings.db_path)
            context = self._context(question)
            retrieved = context["retrieval"]
            event(
                "retrieval",
                "Relationship graph context used."
                if retrieved["used"]
                else "SQLite metadata fallback.",
                retrieved,
            )
            if not retrieved["used"]:
                answer.warnings.append(retrieved.get("reason", "Graph unavailable; SQLite used."))
            if self._planner is None:
                self._planner = GroqPlanner(self.settings)
            event(
                "planning",
                "Requesting typed intent and SQL plan from Groq."
                if self.live
                else "Offline test: injected planner.",
                {"model": self.settings.model},
            )
            plan = self._planner.plan(
                question.strip(), context, previous_portfolio=self.previous_portfolio
            )
            event("classification", "Validated structured tool selection.", {"intent": plan.intent})
            answer.intent, answer.tool = (
                plan.intent,
                plan.intent if plan.intent in {"sql_query", "exposure_calculator"} else None,
            )
            if plan.intent in {"clarification_needed", "out_of_scope"}:
                answer.message = (
                    plan.message
                    or "Specify a descriptive question about the supplied portfolio dataset."
                )
                return answer
            if plan.intent == "exposure_calculator":
                entity = plan.portfolio or self.previous_portfolio
                if not entity:
                    raise EntityError("Which portfolio should the exposure calculator analyze?")
                result = calculate(self.settings.db_path, entity)
                answer.result = result.model_dump(mode="json")
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
                        event(
                            "sql_generation",
                            "Model-generated SQL received as untrusted data.",
                            {"sql": plan.sql, "parameters": params},
                        )
                        sql, tables = validate(plan.sql, params, context["schema"])
                        event(
                            "validation",
                            "Single SELECT, schema, functions and bindings validated.",
                            {"source_tables": tables},
                        )
                        result = execute(self.settings.db_path, sql, params)
                        answer.result = result.model_dump(mode="json")
                        event(
                            "execution",
                            "Read-only SQLite execution completed within resource limits.",
                            answer.result,
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
                        if plan.portfolio:
                            _, self.previous_portfolio = resolve_portfolio(
                                self.settings.db_path, plan.portfolio
                            )
                        break
                    except QueryError as exc:
                        event(
                            "validation_error",
                            "Rejected query; unsafe SQL was not executed.",
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
        except EntityError as exc:
            answer.intent, answer.tool = "clarification_needed", None
            answer.message = str(exc)
            event(
                "clarification",
                "Portfolio resolution requires clarification.",
                {"message": str(exc)},
            )
            return answer
        except CapitalError as exc:
            answer.error = answer.message = str(exc)
            event("error", "Analysis stopped safely.", {"error": str(exc)})
            return answer
        except (sqlite3.Error, OSError, ValueError, TypeError, RuntimeError) as exc:
            answer.error = answer.message = (
                f"Analysis unavailable ({type(exc).__name__}); run doctor and retry."
            )
            event("error", "Unexpected boundary failure; internal details withheld.")
            return answer
        finally:
            answer.elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

    def close(self):
        self.graph.close()
        if self._planner is not None:
            self._planner.close()
