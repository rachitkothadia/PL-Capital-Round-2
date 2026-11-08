from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["sql_query", "exposure_calculator", "clarification_needed", "out_of_scope"]


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    # Groq rejects an integer|number union as overlapping JSON Schema types.
    value: str | float | bool | None


class Plan(BaseModel):
    """All fields required for Groq strict structured outputs."""

    model_config = ConfigDict(extra="forbid")
    intent: Intent
    sql: str | None
    parameters: list[Parameter]
    portfolio: str | None
    message: str | None


class TraceEvent(BaseModel):
    stage: str
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: float = 0


class Answer(BaseModel):
    question: str = ""
    intent: Intent = "clarification_needed"
    tool: str | None = None
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    sql: str | None = None
    executed_sql: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    executed_parameters: dict[str, Any] = Field(default_factory=dict)
    trace: list[TraceEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    elapsed_ms: float = 0
    assumptions: list[str] = Field(default_factory=list)
    source_dates: dict[str, list[str | None]] = Field(default_factory=dict)
    currency: str | None = None


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    source_tables: list[str]
    elapsed_ms: float


class SectorExposure(BaseModel):
    sector: str
    weight: str
    whole_portfolio_pct: float
    equity_normalized_pct: float


class ExposureResult(BaseModel):
    portfolio_id: int
    portfolio_name: str
    status: Literal["ok", "no_equity_holdings"]
    sectors: list[SectorExposure]
    equity_weight_total: str
    bond_weight_total: str
    all_recorded_weights_total: str
    equity_holding_count: int
    bond_exclusion_count: int
    warnings: list[str]
    formula: str = "whole = SUM(stock current_weight)*100; normalized = sector stock weight / total stock weight*100"
