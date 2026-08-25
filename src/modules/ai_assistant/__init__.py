"""The `ai_assistant` module: a read-only, agentic AI expense assistant.

Chats persist in `chats`/`chat_messages`/`chat_runs`. Each sent message runs
a LangGraph agent (see `agent/`) that answers using only read-only tools
(see `tools/`) backed by existing Spenza services — the agent never touches
the database or a provider SDK directly. Responses stream to the client over
SSE (see `streaming/`). Multiple LLM providers are supported behind one
abstraction (see `providers/`), selected per-chat and swappable for future
messages without rewriting history.
"""
