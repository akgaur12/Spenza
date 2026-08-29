"""Loads the static per-model price table (`src/config/ai_model_pricing.json`)
and estimates USD cost from a run's token counts.

Prices are not fetched live — see that file's `_meta` block for freshness
caveats. A model with no published rate (`pricing_available: false`, e.g.
`groq/compound`'s pass-through billing, or a too-new model with no price
yet) resolves to `None`, never a guessed number — callers must treat that
as "unknown", not "free". Ollama's `$0` entries are a real answer (there is
no per-token API charge for a self-hosted model), not a missing one.
"""

import json
from decimal import Decimal
from functools import lru_cache

from src.core.app_config import ROOT_DIR
from src.modules.ai_assistant.enums import LLMProvider

PRICING_FILE_PATH = ROOT_DIR / "src" / "config" / "ai_model_pricing.json"

_TOKENS_PER_UNIT = Decimal(1_000_000)


@lru_cache
def _load_pricing() -> dict[str, dict[str, dict[str, object]]]:
    with PRICING_FILE_PATH.open(encoding="utf-8") as f:
        data: dict[str, dict[str, dict[str, object]]] = json.load(f)
    return data


def get_model_price(provider: LLMProvider, model: str) -> tuple[Decimal, Decimal] | None:
    """`(input_price_per_million_tokens, output_price_per_million_tokens)`
    in USD, or `None` if this provider/model has no published rate.
    """
    entry = _load_pricing().get(provider.value, {}).get(model)
    if not entry or not entry.get("pricing_available"):
        return None
    input_price = entry.get("input_price")
    output_price = entry.get("output_price")
    if input_price is None or output_price is None:
        return None
    return Decimal(str(input_price)), Decimal(str(output_price))


def estimate_cost_usd(
    provider: LLMProvider, model: str, *, input_tokens: int | None, output_tokens: int | None
) -> Decimal | None:
    """Estimated USD cost for one run, or `None` if the price table has no
    rate for this provider/model, or the run itself didn't report both
    token counts — never estimated from a partial or guessed figure.
    """
    prices = get_model_price(provider, model)
    if prices is None or input_tokens is None or output_tokens is None:
        return None
    input_price, output_price = prices
    return (Decimal(input_tokens) / _TOKENS_PER_UNIT) * input_price + (
        Decimal(output_tokens) / _TOKENS_PER_UNIT
    ) * output_price
