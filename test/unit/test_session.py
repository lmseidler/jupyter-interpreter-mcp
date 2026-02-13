"""Unit tests for session management utilities."""

import tempfile
import time
from pathlib import Path

import pytest

from jupyter_interpreter_mcp.session import (
    Session,
    detect_content_type,
    generate_session_id,
    validate_path,
)


class TestGenerateSessionId:
    """Test session ID generation."""

    def test_returns_string(self):
        """Session ID should be a string."""
        session_id = generate_session_id()
        assert isinstance(session_id, str)

    def test_uuid_format(self):
        """Session ID should be a valid UUID4 format."""
        session_id = generate_session_id()
        # UUID4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
        parts = session_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12
        assert parts[2][0] == "4"  # Version 4 UUID

    def test_uniqueness(self):
        """Multiple calls should generate different IDs."""
        ids = [generate_session_id() for _ in range(100)]
        assert len(set(ids)) == 100  # All unique


class TestValidatePath:
    """Test path validation for directory traversal prevention."""

    def test_valid_path_in_root(self):
        """Valid path in session root should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session"
            session_dir.mkdir()

            result = validate_path(str(session_dir), "file.txt")
            expected = str(session_dir / "file.txt")
            assert result == expected

    def test_valid_path_in_subdirectory(self):
        """Valid path in subdirectory should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session"
            session_dir.mkdir()

            result = validate_path(str(session_dir), "subdir/file.txt")
            expected = str(session_dir / "subdir" / "file.txt")
            assert result == expected

    def test_parent_directory_traversal_raises(self):
        """Attempt to traverse to parent directory should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session"
            session_dir.mkdir()

            with pytest.raises(ValueError, match="escapes session directory"):
                validate_path(str(session_dir), "../etc/passwd")

    def test_absolute_path_outside_raises(self):
        """Absolute path outside session directory should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session"
            session_dir.mkdir()

            with pytest.raises(ValueError, match="escapes session directory"):
                validate_path(str(session_dir), "/etc/passwd")

    def test_symlink_traversal_raises(self):
        """Symlink pointing outside session should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session"
            session_dir.mkdir()
            outside_file = Path(tmpdir) / "outside.txt"
            outside_file.write_text("secret")

            # Create symlink inside session pointing outside
            link_path = session_dir / "link.txt"
            link_path.symlink_to(outside_file)

            # validate_path should detect this and raise
            with pytest.raises(ValueError, match="escapes session directory"):
                validate_path(str(session_dir), "link.txt")

    def test_complex_traversal_attempt(self):
        """Complex traversal like subdir/../../etc should raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session"
            session_dir.mkdir()

            with pytest.raises(ValueError, match="escapes session directory"):
                validate_path(str(session_dir), "subdir/../../etc/passwd")

    def test_normalized_path_inside_session(self):
        """Path that resolves inside session after normalization should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session"
            session_dir.mkdir()

            # This looks suspicious but actually stays inside
            result = validate_path(str(session_dir), "subdir/../file.txt")
            expected = str(session_dir / "file.txt")
            assert result == expected


class TestDetectContentType:
    """Test content type detection for binary vs text files."""

    def test_python_file_is_text(self):
        """Python files should be detected as text."""
        content = b"print('hello')"
        assert detect_content_type("script.py", content) == "text"

    def test_text_file_is_text(self):
        """Plain text files should be detected as text."""
        content = b"Hello, world!"
        assert detect_content_type("file.txt", content) == "text"

    def test_json_file_is_text(self):
        """JSON files should be detected as text."""
        content = b'{"key": "value"}'
        assert detect_content_type("data.json", content) == "text"

    def test_png_file_is_binary(self):
        """PNG files should be detected as binary (by extension)."""
        # PNG magic bytes
        content = b"\x89PNG\r\n\x1a\n"
        assert detect_content_type("image.png", content) == "binary"

    def test_jpg_file_is_binary(self):
        """JPG files should be detected as binary (by extension)."""
        content = b"\xff\xd8\xff\xe0"
        assert detect_content_type("photo.jpg", content) == "binary"

    def test_binary_content_without_extension(self):
        """Binary content without known extension should be detected as binary."""
        # Write binary data that can't be decoded as UTF-8
        content = bytes(range(256))
        assert detect_content_type("datafile", content) == "binary"

    def test_utf8_text_without_extension(self):
        """UTF-8 text without extension should be detected as text."""
        content = b"This is plain text content"
        assert detect_content_type("README", content) == "text"

    def test_pickle_file_is_binary(self):
        """Pickle files should be detected as binary (by extension)."""
        content = b"pickle data"
        assert detect_content_type("model.pkl", content) == "binary"


class TestSession:
    """Test Session dataclass and methods."""

    def test_session_creation(self):
        """Session should be created with all required fields."""
        now = time.time()
        session = Session(
            id="test-id",
            kernel_id="kernel-123",
            created_at=now,
            last_access=now,
            directory="/path/to/session",
        )

        assert session.id == "test-id"
        assert session.kernel_id == "kernel-123"
        assert session.directory == "/path/to/session"
        assert isinstance(session.created_at, float)
        assert isinstance(session.last_access, float)

    def test_touch_updates_last_access(self):
        """touch() should update last_access timestamp."""
        now = time.time()
        session = Session(
            id="test-id",
            kernel_id="kernel-123",
            created_at=now,
            last_access=now - 3600,  # 1 hour ago
            directory="/path/to/session",
        )

        old_last_access = session.last_access
        time.sleep(0.01)  # Small delay to ensure time difference
        session.touch()

        assert session.last_access > old_last_access

    def test_is_expired_when_not_expired(self):
        """is_expired() should return False for active sessions."""
        now = time.time()
        session = Session(
            id="test-id",
            kernel_id="kernel-123",
            created_at=now,
            last_access=now,
            directory="/path/to/session",
        )

        # TTL of 3600 seconds (1 hour), just accessed now
        assert session.is_expired(ttl=3600) is False

    def test_is_expired_when_expired(self):
        """is_expired() should return True for expired sessions."""
        now = time.time()
        session = Session(
            id="test-id",
            kernel_id="kernel-123",
            created_at=now - 7200,  # 2 hours ago
            last_access=now - 7200,  # 2 hours ago
            directory="/path/to/session",
        )

        # TTL of 3600 seconds (1 hour), accessed 2 hours ago
        assert session.is_expired(ttl=3600) is True

    def test_is_expired_with_zero_ttl(self):
        """is_expired() should return False when TTL is 0 (never expire)."""
        now = time.time()
        session = Session(
            id="test-id",
            kernel_id="kernel-123",
            created_at=now - 31536000,  # 1 year ago
            last_access=now - 31536000,  # 1 year ago
            directory="/path/to/session",
        )

        # TTL of 0 means never expire
        assert session.is_expired(ttl=0) is False

    def test_is_expired_boundary_case(self):
        """is_expired() should handle boundary cases correctly."""
        now = time.time()
        session = Session(
            id="test-id",
            kernel_id="kernel-123",
            created_at=now - 3600,
            last_access=now - 3600,  # Exactly 1 hour ago
            directory="/path/to/session",
        )

        # Just under TTL - not expired
        assert session.is_expired(ttl=3601) is False
        # Just over TTL - expired
        assert session.is_expired(ttl=3599) is True
