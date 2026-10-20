"""SQLite database connection and schema for Aashi conversation persistence.

Schema:
- conversations: id, title, created_at, updated_at
- messages: id, conversation_id, role, content, created_at
- attachments: id, message_id, original_filename, mime_type, stored_path, created_at

Attachments are stored as files in the app-owned attachments directory
(r"%LOCALAPPDATA%\Aashi\attachments" on Windows), not as blobs in the DB.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Final

from aashi.paths import AashiPaths

__all__ = ["ConversationDatabase", "get_database"]

_logger = logging.getLogger(__name__)

_SCHEMA_VERSION: Final[int] = 2
"""Schema version for future migrations."""

_DB_FILENAME: Final[str] = "conversations.sqlite"
"""Database file name under the user data directory."""

# Base schema (v2) - includes all tables; migration handles upgrade from v1
_SCHEMA_SQL: Final[str] = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT 'User',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
"""

# Thread-local storage for the single database instance
_database_instance: ConversationDatabase | None = None
_database_lock = threading.Lock()


class ConversationDatabase:
    """Thread-safe SQLite database for conversation persistence.

    Uses WAL mode for better concurrency. Connections are opened on demand
    and closed when the database is shut down (which happens at app exit).
    """

    def __init__(self, paths: AashiPaths) -> None:
        self._paths = paths
        self._db_path = paths.user_data_dir / _DB_FILENAME
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Create the database file and run schema initialization."""
        self._paths.ensure_user_directories()
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)

        # Set or verify schema version, run migrations if needed
        cursor = self._conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        if row is None:
            self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
        elif row["version"] < _SCHEMA_VERSION:
            self._run_migrations(row["version"])
        elif row["version"] > _SCHEMA_VERSION:
            _logger.warning("Schema version mismatch: expected %d, found %d", _SCHEMA_VERSION, row["version"])
        self._conn.commit()

    def _run_migrations(self, from_version: int) -> None:
        """Run database migrations from the given version to current."""
        if from_version < 2:
            self._migrate_to_v2()
        # Add future migrations here as elif blocks

    def _migrate_to_v2(self) -> None:
        """Migrate from schema v1 to v2: add project_id to conversations and create default user/project."""
        _logger.info("Migrating database from v1 to v2")
        with self.transaction() as conn:
            # Check if project_id column exists in conversations (v1 doesn't have it)
            cursor = conn.execute("PRAGMA table_info(conversations)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "project_id" not in columns:
                conn.execute("ALTER TABLE conversations ADD COLUMN project_id INTEGER")
            # Create indexes (may already exist from base schema on new DBs)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)")
            # Create a default user and project for existing conversations
            now = time.time()
            cursor = conn.execute("INSERT INTO users (name, created_at, updated_at) VALUES (?, ?, ?)", ("User", now, now))
            default_user_id = cursor.lastrowid
            cursor = conn.execute(
                "INSERT INTO projects (user_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (default_user_id, "Default Project", "Default project for existing conversations", now, now)
            )
            default_project_id = cursor.lastrowid
            # Assign all existing conversations to the default project
            conn.execute("UPDATE conversations SET project_id = ? WHERE project_id IS NULL", (default_project_id,))
            # Update schema version
            conn.execute("UPDATE schema_version SET version = 2")

    def _ensure_connection(self) -> sqlite3.Connection:
        """Return the connection, reopening if it was closed."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @contextlib.contextmanager
    def transaction(self):
        """Context manager for a database transaction."""
        conn = self._ensure_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- Conversations ---

    def create_conversation(self, title: str = "") -> int:
        """Create a new conversation and return its ID."""
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
                (title, now, now),
            )
            return cursor.lastrowid

    def get_conversation(self, conversation_id: int) -> dict | None:
        """Fetch a conversation by ID."""
        cursor = self._ensure_connection().execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """List recent conversations, newest first."""
        cursor = self._ensure_connection().execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def update_conversation_title(self, conversation_id: int, title: str) -> None:
        """Update conversation title and updated_at timestamp."""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, time.time(), conversation_id),
            )

    def delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation and all its messages/attachments (cascades)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    # --- Users ---

    def get_or_create_default_user(self) -> int:
        """Get the default user ID, creating if necessary."""
        cursor = self._ensure_connection().execute("SELECT id FROM users LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row["id"]
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO users (name, created_at, updated_at) VALUES (?, ?, ?)",
                ("User", now, now),
            )
            return cursor.lastrowid

    def get_user(self, user_id: int) -> dict | None:
        """Fetch a user by ID."""
        cursor = self._ensure_connection().execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        """List all users."""
        cursor = self._ensure_connection().execute("SELECT * FROM users ORDER BY created_at ASC")
        return [dict(row) for row in cursor.fetchall()]

    # --- Projects ---

    def create_project(self, user_id: int, name: str = "", description: str = "") -> int:
        """Create a new project and return its ID."""
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO projects (user_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, description, now, now),
            )
            return cursor.lastrowid

    def get_project(self, project_id: int) -> dict | None:
        """Fetch a project by ID."""
        cursor = self._ensure_connection().execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_projects(self, user_id: int | None = None) -> list[dict]:
        """List projects, optionally filtered by user."""
        if user_id is not None:
            cursor = self._ensure_connection().execute(
                "SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
            )
        else:
            cursor = self._ensure_connection().execute("SELECT * FROM projects ORDER BY updated_at DESC")
        return [dict(row) for row in cursor.fetchall()]

    def update_project(self, project_id: int, name: str | None = None, description: str | None = None) -> None:
        """Update project fields."""
        now = time.time()
        with self.transaction() as conn:
            if name is not None:
                conn.execute(
                    "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
                    (name, now, project_id),
                )
            if description is not None:
                conn.execute(
                    "UPDATE projects SET description = ?, updated_at = ? WHERE id = ?",
                    (description, now, project_id),
                )

    def delete_project(self, project_id: int) -> None:
        """Delete a project. Conversations will have project_id set to NULL."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def get_or_create_default_project(self, user_id: int) -> int:
        """Get the default project ID for a user, creating if necessary."""
        cursor = self._ensure_connection().execute(
            "SELECT id FROM projects WHERE user_id = ? ORDER BY created_at ASC LIMIT 1", (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return row["id"]
        return self.create_project(user_id, "Default Project", "Default project for conversations")

    # --- Conversations (updated with project_id) ---

    def create_conversation(self, title: str = "", project_id: int | None = None) -> int:
        """Create a new conversation and return its ID."""
        if project_id is None:
            # Auto-assign to default project for default user
            user_id = self.get_or_create_default_user()
            project_id = self.get_or_create_default_project(user_id)
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (project_id, title, now, now),
            )
            return cursor.lastrowid

    def get_conversation(self, conversation_id: int) -> dict | None:
        """Fetch a conversation by ID."""
        cursor = self._ensure_connection().execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_conversations(
        self,
        limit: int = 50,
        project_id: int | None = None,
        non_empty_only: bool = False,
    ) -> list[dict]:
        """List recent conversations, newest first, optionally filtered by project.

        Args:
            limit: Maximum rows returned.
            project_id: Restrict to one project when given.
            non_empty_only: Hide conversations that have no messages yet, the
                way a chat app only lists a chat once something was said.
        """
        clauses: list[str] = []
        params: list = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if non_empty_only:
            clauses.append("EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = conversations.id)")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        cursor = self._ensure_connection().execute(
            "SELECT conversations.*, "
            "(SELECT content FROM messages m WHERE m.conversation_id = conversations.id "
            "AND m.role = 'user' ORDER BY m.id LIMIT 1) AS first_user_message "
            f"FROM conversations {where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_empty_conversations(self, keep_id: int | None = None) -> int:
        """Delete conversations without messages; return how many were removed."""
        with self.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM conversations WHERE id IS NOT ? AND NOT EXISTS "
                "(SELECT 1 FROM messages m WHERE m.conversation_id = conversations.id)",
                (keep_id,),
            )
            return cursor.rowcount

    def update_conversation_title(
        self, conversation_id: int, title: str, touch: bool = True
    ) -> None:
        """Update a conversation's title.

        ``touch`` also bumps ``updated_at`` (moving the chat to the top of the
        list); a manual rename passes ``False`` so the order stays put.
        """
        with self.transaction() as conn:
            if touch:
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (title, time.time(), conversation_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (title, conversation_id),
                )

    def move_conversation(self, conversation_id: int, project_id: int) -> None:
        """Move a conversation into another project (its order is unchanged)."""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET project_id = ? WHERE id = ?",
                (project_id, conversation_id),
            )

    def reassign_project_conversations(self, from_project_id: int, to_project_id: int) -> None:
        """Move every conversation of one project into another."""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET project_id = ? WHERE project_id = ?",
                (to_project_id, from_project_id),
            )

    def delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation and all its messages/attachments (cascades)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    # --- Messages ---

    def add_message(
        self, conversation_id: int, role: str, content: str
    ) -> int:
        """Add a message to a conversation and return its ID."""
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            # Update conversation's updated_at
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            return cursor.lastrowid

    def get_messages(self, conversation_id: int) -> list[dict]:
        """Get all messages for a conversation in chronological order."""
        cursor = self._ensure_connection().execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_messages(
        self, conversation_id: int, limit: int = 12
    ) -> list[dict]:
        """Get the most recent messages for a conversation (for context window)."""
        cursor = self._ensure_connection().execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows = cursor.fetchall()
        # Return in chronological order (oldest first)
        return [dict(row) for row in reversed(rows)]

    # --- Attachments ---

    def add_attachment(
        self,
        message_id: int,
        original_filename: str,
        mime_type: str,
        stored_path: str,
    ) -> int:
        """Record an attachment for a message and return its ID."""
        now = time.time()
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO attachments (message_id, original_filename, mime_type, stored_path, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, original_filename, mime_type, stored_path, now),
            )
            return cursor.lastrowid

    def get_attachments_for_message(self, message_id: int) -> list[dict]:
        """Get all attachments for a message."""
        cursor = self._ensure_connection().execute(
            "SELECT * FROM attachments WHERE message_id = ? ORDER BY created_at ASC",
            (message_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_attachment(self, attachment_id: int) -> dict | None:
        """Fetch a single attachment by ID."""
        cursor = self._ensure_connection().execute(
            "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_database(paths: AashiPaths | None = None) -> ConversationDatabase:
    """Get the singleton database instance for the given paths.

    If paths is None, uses the default paths from aashi.paths.resolve_paths().
    The instance is cached in a thread-local to support multi-threaded access.
    """
    global _database_instance

    # In a single-process Qt app, we only need one instance
    with _database_lock:
        if _database_instance is None:
            if paths is None:
                from aashi.paths import resolve_paths

                paths = resolve_paths()
            _database_instance = ConversationDatabase(paths)
        return _database_instance


def reset_database_for_testing() -> None:
    """Reset the singleton for testing purposes. Not for production use."""
    global _database_instance
    with _database_lock:
        if _database_instance is not None:
            _database_instance.close()
            _database_instance = None