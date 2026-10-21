from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=24, decimal_places=12),
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
]
Count = Annotated[int, Field(ge=0, strict=True)]
ModelName = Annotated[str, Field(min_length=1, max_length=200)]


class UsageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TokenUsage(UsageModel):
    input_tokens: Count
    cached_input_tokens: Count
    output_tokens: Count
    total_tokens: Count

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("Cached tokens must be a subset of input tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Total tokens must equal input plus output")
        return self


class PriceSnapshot(UsageModel):
    catalog_version: str
    currency: Literal["USD"] = "USD"
    input_per_million: Money
    cached_input_per_million: Money
    output_per_million: Money

    def estimate(self, tokens: TokenUsage) -> Decimal:
        return (
            (tokens.input_tokens - tokens.cached_input_tokens) * self.input_per_million
            + tokens.cached_input_tokens * self.cached_input_per_million
            + tokens.output_tokens * self.output_per_million
        ) / Decimal(1_000_000)


class LLMUsage(UsageModel):
    provider: Literal["openai"] = "openai"
    requested_model: ModelName
    response_model: ModelName | None = None
    service_tier: str | None = None
    started_at: AwareDatetime
    duration_ms: Count
    tokens: TokenUsage | None = None
    pricing: PriceSnapshot | None = None
    estimated_cost_usd: Money | None = None

    @model_validator(mode="after")
    def consistent_cost(self) -> Self:
        if self.estimated_cost_usd is not None:
            if self.tokens is None or self.pricing is None:
                raise ValueError("Cost requires reported tokens and a price snapshot")
            if self.estimated_cost_usd != self.pricing.estimate(self.tokens):
                raise ValueError("Cost does not match the saved price snapshot")
        return self


class UsageTotals(UsageModel):
    calls: Count = 0
    reported_calls: Count = 0
    priced_calls: Count = 0
    input_tokens: Count = 0
    cached_input_tokens: Count = 0
    output_tokens: Count = 0
    total_tokens: Count = 0
    estimated_cost_usd: Money = Decimal(0)


class UsageDay(UsageTotals):
    day: date


class LargeAnalysis(UsageModel):
    investigation_id: UUID
    service: str
    environment: str
    started_at: AwareDatetime
    duration_ms: Count
    total_tokens: Count | None
    estimated_cost_usd: Money | None


class UsageDashboard(UsageModel):
    generated_at: AwareDatetime
    start_time: AwareDatetime
    end_time: AwareDatetime
    totals: UsageTotals
    daily: list[UsageDay]
    largest: list[LargeAnalysis]


UsageSort = Literal["tokens", "cost", "duration"]


class UsageQuery(UsageModel):
    days: int = Field(default=7, ge=1, le=30)
    sort: UsageSort = "tokens"
