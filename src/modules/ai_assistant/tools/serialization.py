"""JSON serialization for tool results returned to the LLM as `ToolMessage`
content — every tool returns a plain `dict`, serialized here so `Decimal`/
`date`/`datetime`/`UUID` values round-trip as plain JSON scalars.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")


def to_tool_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_default)
