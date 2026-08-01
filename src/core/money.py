"""Decimal-safe coercion for raw SQL aggregate results.

Shared by any repository that runs a `SUM()` over `Expense.amount`
(`NUMERIC(12,2)`) — the raw driver value differs by dialect (`None`, `int`,
`float`, or `Decimal`) and PostgreSQL's exact `NUMERIC` arithmetic can still
surface via a dialect (like SQLite in tests) that computes the sum in
floating point, so every result is funneled through here to normalize to a
clean 2-decimal-place `Decimal`.
"""

from decimal import ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")


def to_money(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)
