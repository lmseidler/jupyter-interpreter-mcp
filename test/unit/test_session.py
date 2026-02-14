"""Unit tests for session management utilities."""

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from jupyter_interpreter_mcp.session import (
    Session,
    detect_content_type,
    generate_session_id,
    get_allowed_upload_dirs,
    is_sensitive_file,
    validate_host_path,
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


class TestGetAllowedUploadDirs:
    """Test allowed upload directory configuration."""

    def test_defaults_to_cwd_when_env_unset(self):
        """Should return CWD when ALLOWED_UPLOAD_DIRS is not set."""
        import os

        with patch.dict("os.environ", {}, clear=True):
            dirs = get_allowed_upload_dirs()
            assert len(dirs) == 1
            assert dirs[0] == os.path.realpath(os.getcwd())

    def test_reads_single_directory_from_env(self):
        """Should parse a single directory from the environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                dirs = get_allowed_upload_dirs()
                assert len(dirs) == 1
                import os

                assert dirs[0] == os.path.realpath(tmpdir)

    def test_reads_multiple_directories_from_env(self):
        """Should parse colon-separated directories."""
        with tempfile.TemporaryDirectory() as d1:
            with tempfile.TemporaryDirectory() as d2:
                with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": f"{d1}:{d2}"}):
                    dirs = get_allowed_upload_dirs()
                    assert len(dirs) == 2

    def test_empty_env_var_defaults_to_cwd(self):
        """Empty env var should fallback to CWD."""
        with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": ""}):
            dirs = get_allowed_upload_dirs()
            assert len(dirs) == 1

    def test_ignores_empty_segments(self):
        """Should ignore empty segments from double colons."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": f"{tmpdir}::"}):
                dirs = get_allowed_upload_dirs()
                assert len(dirs) == 1


class TestValidateHostPath:
    """Test host path validation for allowed directories."""

    def test_valid_path_within_allowed_dir(self):
        """Path within allowed directory should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "data.csv"
            test_file.write_text("a,b,c")

            result = validate_host_path(str(test_file), [tmpdir])
            import os

            assert result == os.path.realpath(str(test_file))

    def test_relative_path_raises(self):
        """Relative path should raise ValueError."""
        with pytest.raises(ValueError, match="must be absolute"):
            validate_host_path("relative/path.txt", ["/tmp"])

    def test_path_outside_allowed_dirs_raises(self):
        """Path outside all allowed directories should raise ValueError."""
        with tempfile.TemporaryDirectory() as allowed:
            with tempfile.TemporaryDirectory() as outside:
                test_file = Path(outside) / "secret.txt"
                test_file.write_text("secret")

                with pytest.raises(ValueError, match="outside allowed"):
                    validate_host_path(str(test_file), [allowed])

    def test_traversal_attempt_raises(self):
        """Path with .. that escapes allowed dir should raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = f"{tmpdir}/../../../etc/passwd"
            with pytest.raises(ValueError, match="outside allowed"):
                validate_host_path(bad_path, [tmpdir])

    def test_symlink_outside_allowed_raises(self):
        """Symlink resolving outside allowed dir should raise."""
        with tempfile.TemporaryDirectory() as allowed:
            with tempfile.TemporaryDirectory() as outside:
                outside_file = Path(outside) / "data.txt"
                outside_file.write_text("data")

                link = Path(allowed) / "link.txt"
                link.symlink_to(outside_file)

                with pytest.raises(ValueError, match="outside allowed"):
                    validate_host_path(str(link), [allowed])

    def test_multiple_allowed_dirs(self):
        """Path in any of the allowed directories should pass."""
        with tempfile.TemporaryDirectory() as d1:
            with tempfile.TemporaryDirectory() as d2:
                test_file = Path(d2) / "file.txt"
                test_file.write_text("ok")

                result = validate_host_path(str(test_file), [d1, d2])
                import os

                assert result == os.path.realpath(str(test_file))

    def test_defaults_to_env_allowed_dirs(self):
        """Should use get_allowed_upload_dirs when allowed_dirs is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "file.txt"
            test_file.write_text("ok")

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = validate_host_path(str(test_file))
                import os

                assert result == os.path.realpath(str(test_file))


class TestIsSensitiveFile:
    """Test sensitive file detection utility."""

    def test_env_file_is_sensitive(self):
        """`.env` files should be detected as sensitive."""
        assert is_sensitive_file(".env") is True
        assert is_sensitive_file("/project/.env") is True
        assert is_sensitive_file("/project/.env.local") is True
        assert is_sensitive_file("/project/.env.production") is True

    def test_ssh_files_are_sensitive(self):
        """Files in `.ssh/` should be detected as sensitive."""
        assert is_sensitive_file("/home/user/.ssh/id_rsa") is True
        assert is_sensitive_file("/home/user/.ssh/config") is True
        assert is_sensitive_file(".ssh/known_hosts") is True

    def test_credentials_files_are_sensitive(self):
        """Credential files should be detected as sensitive."""
        assert is_sensitive_file("credentials.json") is True
        assert is_sensitive_file("/path/credentials.yaml") is True
        assert is_sensitive_file("credentials.yml") is True
        assert is_sensitive_file("credentials") is True

    def test_aws_files_are_sensitive(self):
        """`.aws/` files should be detected as sensitive."""
        assert is_sensitive_file("/home/user/.aws/credentials") is True
        assert is_sensitive_file(".aws/config") is True

    def test_netrc_is_sensitive(self):
        """`.netrc` should be detected as sensitive."""
        assert is_sensitive_file("/home/user/.netrc") is True
        assert is_sensitive_file(".netrc") is True

    def test_npmrc_is_sensitive(self):
        """`.npmrc` should be detected as sensitive."""
        assert is_sensitive_file(".npmrc") is True
        assert is_sensitive_file("/home/user/.npmrc") is True

    def test_pypirc_is_sensitive(self):
        """`.pypirc` should be detected as sensitive."""
        assert is_sensitive_file(".pypirc") is True

    def test_git_credentials_is_sensitive(self):
        """`.git-credentials` should be detected as sensitive."""
        assert is_sensitive_file(".git-credentials") is True
        assert is_sensitive_file("/home/user/.git-credentials") is True

    def test_secret_files_are_sensitive(self):
        """Files named secret/secrets should be detected as sensitive."""
        assert is_sensitive_file("secret.json") is True
        assert is_sensitive_file("secrets.yaml") is True
        assert is_sensitive_file("/path/to/secrets.txt") is True

    def test_token_files_are_sensitive(self):
        """Files named token/tokens should be detected as sensitive."""
        assert is_sensitive_file("token.json") is True
        assert is_sensitive_file("tokens.yaml") is True

    def test_normal_files_are_not_sensitive(self):
        """Normal files should not be flagged as sensitive."""
        assert is_sensitive_file("data.csv") is False
        assert is_sensitive_file("/home/user/project/main.py") is False
        assert is_sensitive_file("README.md") is False
        assert is_sensitive_file("/tmp/report.pdf") is False
        assert is_sensitive_file("config.py") is False
        assert is_sensitive_file("environment.yml") is False

    def test_docker_config_is_sensitive(self):
        """Docker config.json should be detected as sensitive."""
        assert is_sensitive_file("/home/user/.docker/config.json") is True

    def test_gnupg_files_are_sensitive(self):
        """`.gnupg/` files should be detected as sensitive."""
        assert is_sensitive_file("/home/user/.gnupg/pubring.gpg") is True

    def test_ssh_key_files_are_sensitive(self):
        """SSH key files by name should be detected as sensitive."""
        assert is_sensitive_file("id_rsa") is True
        assert is_sensitive_file("id_ed25519") is True
        assert is_sensitive_file("id_ecdsa") is True
        assert is_sensitive_file("id_rsa.pub") is True
