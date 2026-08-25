"""Multi-provider LLM abstraction.

`LLMFactory.create()` (see `factory.py`) is the only entry point the rest of
the `ai_assistant` module (the agent/graph included) is allowed to use — it
returns a plain LangChain `Runnable`, never a provider-specific class. Each
`<name>_provider.py` file owns exactly one provider's credential lookup and
LangChain chat-model construction.
"""
