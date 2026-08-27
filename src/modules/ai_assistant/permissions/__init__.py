"""Per-user access control and usage limits for the AI assistant.

Access is opt-in: a user with no `AIAssistantPermission` row (or an
explicitly disabled one) may not create new chats or send new messages —
see `service.AIAssistantPermissionService` for where that default is
resolved, and for the enforcement checks `ai_assistant.service.ChatService`
calls before creating a chat or a message.
"""
