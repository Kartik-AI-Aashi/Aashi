"""High-level repository for conversation operations.

Wraps the low-level database with domain-specific methods for the chat window.
Handles attachment file copying to the app-owned storage directory.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from aashi.paths import AashiPaths

from .database import ConversationDatabase, get_database

__all__ = ["ConversationRepository"]

_logger = logging.getLogger(__name__)

ATTACHMENTS_DIR_NAME: str = "attachments"
"""Subdirectory under user_data_dir where attachment files are stored."""


class ConversationRepository:
    """Application-level operations for conversations, messages, and attachments."""

    def __init__(self, db: ConversationDatabase, paths: AashiPaths) -> None:
        self._db = db
        self._paths = paths
        self._attachments_dir = paths.user_data_dir / ATTACHMENTS_DIR_NAME
        self._attachments_dir.mkdir(parents=True, exist_ok=True)

    # --- Users ---

    def get_or_create_default_user(self) -> int:
        """Get the default user ID, creating if necessary."""
        return self._db.get_or_create_default_user()

    def get_user(self, user_id: int) -> dict | None:
        """Fetch a user by ID."""
        return self._db.get_user(user_id)

    def list_users(self) -> list[dict]:
        """List all users."""
        return self._db.list_users()

    # --- Projects ---

    def create_project(self, user_id: int, name: str = "", description: str = "") -> int:
        """Create a new project and return its ID."""
        return self._db.create_project(user_id, name, description)

    def get_project(self, project_id: int) -> dict | None:
        """Fetch a project by ID."""
        return self._db.get_project(project_id)

    def list_projects(self, user_id: int | None = None) -> list[dict]:
        """List projects, optionally filtered by user."""
        return self._db.list_projects(user_id)

    def update_project(self, project_id: int, name: str | None = None, description: str | None = None) -> None:
        """Update project fields."""
        self._db.update_project(project_id, name, description)

    def delete_project(self, project_id: int) -> bool:
        """Delete a project; its chats move to the default project, not away.

        The default project (the oldest one) is never deleted.

        Returns:
            ``True`` if the project was deleted, ``False`` if it is the default.
        """
        project = self._db.get_project(project_id)
        if project is None:
            return False
        default_id = self._db.get_or_create_default_project(project["user_id"])
        if default_id == project_id:
            return False
        self._db.reassign_project_conversations(project_id, default_id)
        self._db.delete_project(project_id)
        return True

    def get_or_create_default_project(self, user_id: int) -> int:
        """Get the default project ID for a user, creating if necessary."""
        return self._db.get_or_create_default_project(user_id)

    # --- Conversation lifecycle ---

    def create_conversation(self, title: str = "", project_id: int | None = None) -> int:
        """Create a new empty conversation."""
        return self._db.create_conversation(title, project_id)

    def get_conversation(self, conversation_id: int) -> dict | None:
        """Get conversation metadata."""
        return self._db.get_conversation(conversation_id)

    def list_conversations(
        self,
        limit: int = 50,
        project_id: int | None = None,
        non_empty_only: bool = False,
    ) -> list[dict]:
        """List recent conversations, optionally filtered by project.

        ``non_empty_only`` hides conversations that have no messages yet.
        """
        return self._db.list_conversations(limit, project_id, non_empty_only)

    def update_conversation_title(
        self, conversation_id: int, title: str, touch: bool = True
    ) -> None:
        """Rename a conversation (``touch=False`` keeps its place in the list)."""
        self._db.update_conversation_title(conversation_id, title, touch)

    def move_conversation(self, conversation_id: int, project_id: int) -> None:
        """Move a conversation into another project."""
        self._db.move_conversation(conversation_id, project_id)

    def delete_empty_conversations(self, keep_id: int | None = None) -> int:
        """Remove conversations that never received a message."""
        return self._db.delete_empty_conversations(keep_id)

    def delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation and all its data (including attachment files)."""
        # First, get all attachments for this conversation so we can delete files
        messages = self._db.get_messages(conversation_id)
        for msg in messages:
            attachments = self._db.get_attachments_for_message(msg["id"])
            for att in attachments:
                stored_path = Path(att["stored_path"])
                try:
                    if stored_path.exists():
                        stored_path.unlink()
                except Exception as exc:
                    _logger.warning("Failed to delete attachment file %s: %s", stored_path, exc)

        # Then cascade-delete the conversation from the database
        self._db.delete_conversation(conversation_id)

    # --- Messages ---

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        attachment_paths: list[str] | None = None,
    ) -> tuple[int, list[dict]]:
        """Add a message with optional attachments.

        Args:
            conversation_id: The conversation to add to.
            role: 'user' or 'assistant'.
            content: The message text.
            attachment_paths: Optional list of file paths to attach. These will be
                copied to the app-owned attachments directory.

        Returns:
            A tuple of (message_id, list_of_attachment_dicts).
        """
        message_id = self._db.add_message(conversation_id, role, content)

        attachments = []
        if attachment_paths:
            for path in attachment_paths:
                attachment = self._store_attachment(message_id, path)
                if attachment:
                    attachments.append(attachment)

        return message_id, attachments

    def get_messages(self, conversation_id: int) -> list[dict]:
        """Get all messages with their attachments."""
        messages = self._db.get_messages(conversation_id)
        for msg in messages:
            msg["attachments"] = self._db.get_attachments_for_message(msg["id"])
        return messages

    def get_recent_messages(self, conversation_id: int, limit: int = 12) -> list[dict]:
        """Get recent messages with attachments for context window."""
        messages = self._db.get_recent_messages(conversation_id, limit)
        for msg in messages:
            msg["attachments"] = self._db.get_attachments_for_message(msg["id"])
        return messages

    # --- Attachments ---

    def _store_attachment(self, message_id: int, source_path: str) -> dict | None:
        """Copy an attachment to the app-owned directory and record it.

        Returns the attachment record dict, or None if the source file
        doesn't exist or can't be copied.
        """
        source = Path(source_path)
        if not source.exists():
            _logger.warning("Attachment source not found: %s", source_path)
            return None

        # Generate a unique stored filename: timestamp + original name
        timestamp = int(time.time() * 1000)
        stored_name = f"{timestamp}_{source.name}"
        stored_path = self._attachments_dir / stored_name

        try:
            shutil.copy2(source, stored_path)
        except Exception as exc:
            _logger.error("Failed to copy attachment %s: %s", source_path, exc)
            return None

        # Determine MIME type from extension
        mime_type = self._guess_mime_type(source.suffix)

        attachment_id = self._db.add_attachment(
            message_id=message_id,
            original_filename=source.name,
            mime_type=mime_type,
            stored_path=str(stored_path),
        )

        return {
            "id": attachment_id,
            "message_id": message_id,
            "original_filename": source.name,
            "mime_type": mime_type,
            "stored_path": str(stored_path),
        }

    def _guess_mime_type(self, suffix: str) -> str:
        """Guess MIME type from file extension."""
        suffix = suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".txt": "text/plain",
        }
        return mime_map.get(suffix, "application/octet-stream")

    def get_attachment(self, attachment_id: int) -> dict | None:
        """Get attachment record by ID."""
        return self._db.get_attachment(attachment_id)

    def get_attachments_for_message(self, message_id: int) -> list[dict]:
        """Get all attachments for a message."""
        return self._db.get_attachments_for_message(message_id)

    def resolve_attachment_path(self, attachment: dict) -> Path | None:
        """Resolve an attachment record to its stored file path.

        Returns the Path if it exists, None otherwise.
        """
        stored_path = Path(attachment["stored_path"])
        if stored_path.exists():
            return stored_path
        _logger.warning("Attachment file missing: %s", stored_path)
        return None