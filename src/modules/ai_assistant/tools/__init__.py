"""Read-only tools the agent may call, grouped by domain.

Every tool function is built for one specific run via a closure over a
`ToolContext` (see `context.py`) carrying the trusted, server-resolved
`user` and `session` — never an LLM-fillable parameter. Each tool's
`args_schema` (see `schemas.py`) declares only business parameters
(category, date range, period, search term); the LLM can never supply
`user`/`user_id`.

Tools call existing Spenza services only — never the database or raw SQL
directly (see each domain file's docstring for exactly which service
methods it reuses, and how any gap not covered by an existing method is
closed by pure-Python composition rather than a new service/repository
method).
"""
