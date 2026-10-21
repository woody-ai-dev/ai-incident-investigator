from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from ai_incident_investigator.usage.models import LLMUsage, PriceSnapshot, TokenUsage

# Versioned standard-tier text rates. Unknown models or tiers stay unpriced.
PRICES = {
    "gpt-4.1-mini-2025-04-14": PriceSnapshot(
        catalog_version="openai-text-standard-2026-10-21",
        input_per_million=Decimal("0.40"),
        cached_input_per_million=Decimal("0.10"),
        output_per_million=Decimal("1.60"),
    )
}


def capture_usage(
    body: object, *, requested_model: str, started_at: datetime, duration_ms: int
) -> LLMUsage:
    payload = body if isinstance(body, dict) else {}
    raw_model = payload.get("model")
    model = raw_model if isinstance(raw_model, str) and 0 < len(raw_model) <= 200 else None
    raw_tier = payload.get("service_tier")
    tier = raw_tier if isinstance(raw_tier, str) else None
    tokens = None
    raw_usage = payload.get("usage")
    if isinstance(raw_usage, dict):
        details = raw_usage.get("input_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        try:
            tokens = TokenUsage.model_validate(
                {
                    "input_tokens": raw_usage.get("input_tokens"),
                    "cached_input_tokens": cached,
                    "output_tokens": raw_usage.get("output_tokens"),
                    "total_tokens": raw_usage.get("total_tokens"),
                }
            )
        except ValidationError:
            pass
    price = PRICES.get(model) if model is not None and tier == "default" else None
    return LLMUsage(
        requested_model=requested_model,
        response_model=model,
        service_tier=tier,
        started_at=started_at,
        duration_ms=duration_ms,
        tokens=tokens,
        pricing=price,
        estimated_cost_usd=price.estimate(tokens)
        if price is not None and tokens is not None
        else None,
    )
