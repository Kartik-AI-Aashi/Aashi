"""SQLite-backed conversation persistence for Aashi.

Provides a small, focused repository for:
- Conversations (metadata only)
- Messages (text + role, linked to conversation)
- Attachments (metadata + stored file path, linked to message)

Attachments are copied into an application-owned directory so they survive
restarts, Windows restarts, and normal application updates.
"""

from __future__ import annotations

from .database import ConversationDatabase, get_database, reset_database_for_testing
from .repository import ConversationRepository

__all__ = [
    "ConversationDatabase",
    "get_database",
    "reset_database_for_testing",
    "ConversationRepository",
]