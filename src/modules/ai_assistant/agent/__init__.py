"""The LangGraph agent: `load context -> LLM -> tool call? -> execute tool
-> back to LLM -> response -> END` (see `graph.py`).

Provider-specific classes never appear here — `agent.runner` gets a
provider-agnostic `Runnable` from `providers.factory.LLMFactory` and passes
it into `graph.build_graph()`, which only ever calls `.ainvoke()` on it.
"""
