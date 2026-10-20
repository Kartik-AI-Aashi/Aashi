"""Tests for the conversation persistence layer.

Covers database schema, repository operations, and attachment storage.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from aashi.paths import AashiPaths, resolve_paths
from aashi.storage import ConversationRepository, get_database, reset_database_for_testing


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure each test gets a fresh database."""
    from aashi.storage import reset_database_for_testing
    reset_database_for_testing()
    yield
    # Close any open connection before resetting
    reset_database_for_testing()
    # Small delay to allow Windows to release file locks
    import time
    time.sleep(0.01)


@pytest.fixture
def temp_paths():
    """Create a temporary AashiPaths for isolated testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        paths = resolve_paths(
            user_data_dir=tmp_path,
            bundle_root=tmp_path,
            config_dir=tmp_path,
        )
        paths.ensure_user_directories()
        yield paths


@pytest.fixture
def db(temp_paths):
    """Create a database instance for testing."""
    database = get_database(temp_paths)
    yield database
    database.close()


@pytest.fixture
def repo(temp_paths, db):
    """Create a repository instance for testing."""
    return ConversationRepository(db, temp_paths)


class TestDatabaseSchema:
    def test_schema_created(self, db):
        """Verify all tables exist."""
        conn = db._ensure_connection()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor.fetchall()}
        expected = {"conversations", "messages", "attachments", "schema_version"}
        assert expected.issubset(tables)

    def test_foreign_keys_enabled(self, db):
        """Verify foreign keys are enforced."""
        conn = db._ensure_connection()
        cursor = conn.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1


class TestConversationOperations:
    def test_create_conversation(self, repo):
        """Create and retrieve a conversation."""
        conv_id = repo.create_conversation("Test Chat")
        assert conv_id > 0

        conv = repo.get_conversation(conv_id)
        assert conv is not None
        assert conv["title"] == "Test Chat"
        assert conv["id"] == conv_id

    def test_list_conversations(self, repo):
        """List conversations ordered by updated_at descending."""
        id1 = repo.create_conversation("First")
        time.sleep(0.01)  # Ensure different timestamps
        id2 = repo.create_conversation("Second")
        time.sleep(0.01)
        id3 = repo.create_conversation("Third")

        conversations = repo.list_conversations()
        assert len(conversations) == 3
        # Most recent first
        assert conversations[0]["id"] == id3
        assert conversations[1]["id"] == id2
        assert conversations[2]["id"] == id1

    def test_delete_conversation_cascades(self, repo):
        """Deleting a conversation removes its messages and attachments."""
        conv_id = repo.create_conversation("To Delete")
        msg_id, _ = repo.add_message(conv_id, "user", "Hello")
        repo.add_message(conv_id, "assistant", "Hi there")

        repo.delete_conversation(conv_id)

        conv = repo.get_conversation(conv_id)
        assert conv is None

        # Messages should be cascade-deleted
        messages = repo.get_messages(conv_id)
        assert len(messages) == 0

    def test_delete_conversation_removes_attachment_files(self, repo, temp_paths):
        """Deleting a conversation also removes stored attachment files from disk."""
        conv_id = repo.create_conversation("With Attachments")

        # Create attachment files
        img1 = temp_paths.user_data_dir / "delete1.png"
        img1.write_bytes(b"data1")
        img2 = temp_paths.user_data_dir / "delete2.pdf"
        img2.write_bytes(b"data2")

        msg_id, attachments = repo.add_message(
            conv_id, "user", "Files", [str(img1), str(img2)]
        )
        assert len(attachments) == 2

        # Verify files were copied to the attachments dir
        stored_paths = [Path(att["stored_path"]) for att in attachments]
        for p in stored_paths:
            assert p.exists()

        repo.delete_conversation(conv_id)

        # The stored attachment files should be deleted
        for p in stored_paths:
            assert not p.exists()


class TestMessageOperations:
    def test_add_message(self, repo):
        """Add and retrieve a message."""
        conv_id = repo.create_conversation("Test")
        msg_id, attachments = repo.add_message(conv_id, "user", "Hello world")

        assert msg_id > 0
        assert attachments == []

        messages = repo.get_messages(conv_id)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello world"
        assert messages[0]["attachments"] == []

    def test_message_order(self, repo):
        """Messages returned in chronological order."""
        conv_id = repo.create_conversation("Test")
        repo.add_message(conv_id, "user", "First")
        time.sleep(0.01)
        repo.add_message(conv_id, "assistant", "Second")
        time.sleep(0.01)
        repo.add_message(conv_id, "user", "Third")

        messages = repo.get_messages(conv_id)
        assert len(messages) == 3
        assert messages[0]["content"] == "First"
        assert messages[1]["content"] == "Second"
        assert messages[2]["content"] == "Third"

    def test_recent_messages_limit(self, repo):
        """get_recent_messages respects the limit."""
        conv_id = repo.create_conversation("Test")
        for i in range(20):
            repo.add_message(conv_id, "user", f"Message {i}")

        recent = repo.get_recent_messages(conv_id, limit=5)
        assert len(recent) == 5
        # Should be the last 5 in chronological order
        assert recent[0]["content"] == "Message 15"
        assert recent[-1]["content"] == "Message 19"


class TestAttachmentOperations:
    def test_add_attachment_image(self, repo, temp_paths):
        """Attach an image file and verify it's copied."""
        conv_id = repo.create_conversation("Test")

        # Create a dummy image file
        source = temp_paths.user_data_dir / "test.png"
        source.write_bytes(b"fake png content")

        msg_id, attachments = repo.add_message(
            conv_id, "user", "Here's an image", [str(source)]
        )

        assert len(attachments) == 1
        att = attachments[0]
        assert att["original_filename"] == "test.png"
        assert att["mime_type"] == "image/png"
        assert att["message_id"] == msg_id

        # File should be copied to attachments directory
        stored_path = Path(att["stored_path"])
        assert stored_path.exists()
        assert stored_path.read_bytes() == b"fake png content"
        assert "attachments" in str(stored_path)

    def test_add_multiple_attachments(self, repo, temp_paths):
        """Attach multiple files at once."""
        conv_id = repo.create_conversation("Test")

        img = temp_paths.user_data_dir / "img.png"
        img.write_bytes(b"img")
        pdf = temp_paths.user_data_dir / "doc.pdf"
        pdf.write_bytes(b"pdf")

        msg_id, attachments = repo.add_message(
            conv_id, "user", "Two files", [str(img), str(pdf)]
        )

        assert len(attachments) == 2
        assert {a["original_filename"] for a in attachments} == {"img.png", "doc.pdf"}

    def test_attachment_retrieved_with_message(self, repo, temp_paths):
        """Attachments are included when fetching messages."""
        conv_id = repo.create_conversation("Test")
        img = temp_paths.user_data_dir / "photo.jpg"
        img.write_bytes(b"jpg")

        repo.add_message(conv_id, "user", "Photo", [str(img)])

        messages = repo.get_messages(conv_id)
        assert len(messages) == 1
        assert len(messages[0]["attachments"]) == 1
        assert messages[0]["attachments"][0]["original_filename"] == "photo.jpg"

    def test_missing_source_file_handled(self, repo):
        """Missing source file returns None attachment, doesn't crash."""
        conv_id = repo.create_conversation("Test")
        msg_id, attachments = repo.add_message(
            conv_id, "user", "Missing file", ["/nonexistent/path.png"]
        )

        assert len(attachments) == 0
        # Message still created
        messages = repo.get_messages(conv_id)
        assert len(messages) == 1

    def test_resolve_attachment_path(self, repo, temp_paths):
        """Resolve attachment record to actual file path."""
        conv_id = repo.create_conversation("Test")
        img = temp_paths.user_data_dir / "resolve.png"
        img.write_bytes(b"data")

        msg_id, attachments = repo.add_message(conv_id, "user", "Test", [str(img)])
        attachment = attachments[0]

        resolved = repo.resolve_attachment_path(attachment)
        assert resolved is not None
        assert resolved.exists()
        assert resolved.read_bytes() == b"data"

    def test_resolve_missing_attachment_file(self, repo, temp_paths):
        """Resolve returns None if stored file was deleted."""
        conv_id = repo.create_conversation("Test")
        img = temp_paths.user_data_dir / "temp.png"
        img.write_bytes(b"temp")

        msg_id, attachments = repo.add_message(conv_id, "user", "Test", [str(img)])
        attachment = attachments[0]

        # Delete the stored file
        Path(attachment["stored_path"]).unlink()

        resolved = repo.resolve_attachment_path(attachment)
        assert resolved is None


class TestMimeTypeGuessing:
    def test_image_mime_types(self, repo):
        assert repo._guess_mime_type(".png") == "image/png"
        assert repo._guess_mime_type(".jpg") == "image/jpeg"
        assert repo._guess_mime_type(".jpeg") == "image/jpeg"
        assert repo._guess_mime_type(".webp") == "image/webp"
        assert repo._guess_mime_type(".gif") == "image/gif"
        assert repo._guess_mime_type(".bmp") == "image/bmp"

    def test_document_mime_types(self, repo):
        assert repo._guess_mime_type(".pdf") == "application/pdf"
        assert repo._guess_mime_type(".docx") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert repo._guess_mime_type(".doc") == "application/msword"
        assert repo._guess_mime_type(".txt") == "text/plain"

    def test_unknown_defaults(self, repo):
        assert repo._guess_mime_type(".xyz") == "application/octet-stream"
        assert repo._guess_mime_type("") == "application/octet-stream"