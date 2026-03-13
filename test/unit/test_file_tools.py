"""Unit tests for the upload_file_path and download_file tools."""

import base64
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

import jupyter_interpreter_mcp.session as session_module
from jupyter_interpreter_mcp import server
from jupyter_interpreter_mcp.remote import JupyterConnectionError
from jupyter_interpreter_mcp.session import Session


class TestUploadFilePath:
    """Test upload_file_path tool functionality."""

    def setup_method(self):
        """Reset global allowed upload dirs before each test to avoid state leakage."""
        session_module._configured_allowed_dirs = None

    def _setup_server(self, server, session_dir: str, session_id: str = "test-session"):
        """Set up server module state for testing."""
        import time

        session = Session(
            id=session_id,
            kernel_id="kernel-1",
            created_at=time.time(),
            last_access=time.time(),
            directory=session_dir,
        )
        server.sessions = {session_id: session}
        server.session_ttl = 0
        # jupyter_root is the parent of session_dir so relpath works correctly
        server.jupyter_root = str(Path(session_dir).parent)

        mock_remote = Mock()
        mock_remote.update_session_metadata = AsyncMock()
        mock_remote.check_exists = Mock(return_value=False)
        mock_remote.create_directory = Mock()
        mock_remote.put_contents = Mock(return_value={})
        server.remote_client = mock_remote

        # Populate notebooks so ensure_session_available short-circuits
        # without calling restore_sessions_from_disk (which requires AsyncMock)
        server.notebooks = {session_id: Mock()}

        return mock_remote

    @pytest.mark.asyncio
    async def test_successful_upload(self):
        """6.1 - Successful upload scenario."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a host file to upload
            host_file = Path(tmpdir) / "data.csv"
            host_file.write_text("a,b,c\n1,2,3\n")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=str(host_file),
                    destination_path="data.csv",
                )

            assert "error" not in result
            assert result["status"] == "success"
            assert "sandbox_path" in result
            assert result["size"] == str(host_file.stat().st_size)
            # Verify put_contents was called (Contents API upload)
            server.remote_client.put_contents.assert_called_once()  # type: ignore [attr-defined]

    @pytest.mark.asyncio
    async def test_host_file_not_found(self):
        """6.2 - Host file not found scenario."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            nonexistent = str(Path(tmpdir) / "nonexistent.csv")

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=nonexistent,
                    destination_path="data.csv",
                )

            assert "error" in result
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_permission_denied(self):
        """6.3 - Permission denied scenario."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            host_file = Path(tmpdir) / "restricted.txt"
            host_file.write_text("secret")
            host_file.chmod(0o000)

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            try:
                with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                    result = await server.upload_file_path(
                        session_id="test-session",
                        host_path=str(host_file),
                        destination_path="data.txt",
                    )

                assert "error" in result
                assert "Permission denied" in result["error"]
            finally:
                host_file.chmod(0o644)

    @pytest.mark.asyncio
    async def test_destination_path_validation(self):
        """6.4 - Destination path traversal validation."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            host_file = Path(tmpdir) / "data.csv"
            host_file.write_text("a,b,c")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=str(host_file),
                    destination_path="../../../etc/passwd",
                )

            assert "error" in result
            assert "escapes session directory" in result["error"]

    @pytest.mark.asyncio
    async def test_overwrite_false_existing_file(self):
        """6.5 - Overwrite=False with existing file."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            host_file = Path(tmpdir) / "data.csv"
            host_file.write_text("a,b,c")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            mock_remote = self._setup_server(server, session_dir)

            # Simulate that destination exists via Contents API check
            mock_remote.check_exists = Mock(return_value=True)

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=str(host_file),
                    destination_path="data.csv",
                    overwrite=False,
                )

            assert "error" in result
            assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_overwrite_true_existing_file(self):
        """6.6 - Overwrite=True with existing file succeeds."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            host_file = Path(tmpdir) / "data.csv"
            host_file.write_text("a,b,c")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=str(host_file),
                    destination_path="data.csv",
                    overwrite=True,
                )

            assert "error" not in result
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_path_security_outside_allowed_dirs(self):
        """6.7 - Path outside allowed directories is rejected."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as allowed:
            with tempfile.TemporaryDirectory() as outside:
                host_file = Path(outside) / "data.csv"
                host_file.write_text("a,b,c")

                session_dir = str(Path(allowed) / "session")
                Path(session_dir).mkdir()

                self._setup_server(server, session_dir)

                with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": allowed}):
                    result = await server.upload_file_path(
                        session_id="test-session",
                        host_path=str(host_file),
                        destination_path="data.csv",
                    )

                assert "error" in result
                assert "outside allowed" in result["error"]

    @pytest.mark.asyncio
    async def test_sensitive_file_detection(self):
        """6.8 - Sensitive file patterns are blocked."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("SECRET=abc123")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=str(env_file),
                    destination_path=".env",
                )

            assert "error" in result
            assert "sensitive" in result["error"]

    @pytest.mark.asyncio
    async def test_default_allows_only_cwd(self):
        """6.9 - By default, uploads are restricted to CWD only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file outside CWD (tmpdir is different from CWD)
            host_file = Path(tmpdir) / "data.csv"
            host_file.write_text("a,b,c")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            # Simulate default CWD-only behavior by setting CWD as allowed
            # This is what server.py does when no --allowed-dirs or env var is set
            original_config = session_module._configured_allowed_dirs
            try:
                session_module._configured_allowed_dirs = [str(Path.cwd().resolve())]
                with patch.dict("os.environ", {}, clear=True):
                    result = await server.upload_file_path(
                        session_id="test-session",
                        host_path=str(host_file),
                        destination_path="data.csv",
                    )

                assert "error" in result
                assert "outside allowed" in result["error"]
            finally:
                session_module._configured_allowed_dirs = original_config

    @pytest.mark.asyncio
    async def test_allow_uploads_from_env_configured_dirs(self):
        """6.10 - Allow uploads from env-configured directories."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file to upload
            host_file = Path(tmpdir) / "data.csv"
            host_file.write_text("a,b,c")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            self._setup_server(server, session_dir)

            # Use ALLOWED_UPLOAD_DIRS with tmpdir to allow uploads from there
            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=str(host_file),
                    destination_path="data.csv",
                )

            assert "error" not in result
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_upload_uses_put_contents_not_kernel(self):
        """Verify upload uses Contents API (put_contents), not kernel execution."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            host_file = Path(tmpdir) / "data.txt"
            host_file.write_text("hello")

            session_dir = str(Path(tmpdir) / "session")
            Path(session_dir).mkdir()

            mock_remote = self._setup_server(server, session_dir)

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
                result = await server.upload_file_path(
                    session_id="test-session",
                    host_path=str(host_file),
                    destination_path="data.txt",
                )

            assert "error" not in result
            mock_remote.put_contents.assert_called_once()
            # Verify format is base64
            call_kwargs = mock_remote.put_contents.call_args
            assert call_kwargs[1].get("format") == "base64" or (
                len(call_kwargs[0]) >= 3 and call_kwargs[0][2] == "base64"
            )


class TestDownloadFile:
    """Test download_file tool using Contents API."""

    def setup_method(self):
        """Reset global state before each test."""
        session_module._configured_allowed_dirs = None

    def _setup_server(
        self, tmpdir: str, session_id: str = "test-session"
    ) -> tuple[str, Mock]:
        """Set up server module state for download tests.

        Returns (session_dir, mock_remote_client).
        """
        import time

        session_dir = str(Path(tmpdir) / "session")
        Path(session_dir).mkdir(exist_ok=True)

        session = Session(
            id=session_id,
            kernel_id="kernel-1",
            created_at=time.time(),
            last_access=time.time(),
            directory=session_dir,
        )
        server.sessions = {session_id: session}
        server.session_ttl = 0
        server.jupyter_root = tmpdir  # root is the tmpdir

        mock_remote = Mock()
        mock_remote.update_session_metadata = AsyncMock()
        server.remote_client = mock_remote

        # Populate notebooks so ensure_session_available short-circuits
        # without calling restore_sessions_from_disk (which requires AsyncMock)
        server.notebooks = {session_id: Mock()}

        return session_dir, mock_remote

    @pytest.mark.asyncio
    async def test_download_text_file_success(self):
        """Download a text file returns content with encoding='text'."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = self._setup_server(tmpdir)

            mock_remote.get_file_contents = Mock(
                return_value={
                    "name": "hello.txt",
                    "format": "text",
                    "content": "hello world\n",
                }
            )

            result = await server.download_file(
                session_id="test-session", path="hello.txt"
            )

        assert "error" not in result
        assert result["encoding"] == "text"
        assert result["content"] == "hello world\n"
        assert result["filename"] == "hello.txt"

    @pytest.mark.asyncio
    async def test_download_binary_file_returns_base64(self):
        """Download a binary file returns base64 encoding."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = self._setup_server(tmpdir)

            # PNG magic bytes encoded as base64
            png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
            b64_content = base64.b64encode(png_bytes).decode("ascii")

            mock_remote.get_file_contents = Mock(
                return_value={
                    "name": "image.png",
                    "format": "base64",
                    "content": b64_content,
                }
            )

            result = await server.download_file(
                session_id="test-session", path="image.png"
            )

        assert "error" not in result
        assert result["encoding"] == "base64"
        assert result["content"] == b64_content
        assert result["filename"] == "image.png"

    @pytest.mark.asyncio
    async def test_download_file_not_found(self):
        """Download returns error when Contents API raises JupyterConnectionError."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = self._setup_server(tmpdir)

            mock_remote.get_file_contents = Mock(
                side_effect=JupyterConnectionError(
                    "File not found: sessions/test-session/missing.txt"
                )
            )

            result = await server.download_file(
                session_id="test-session", path="missing.txt"
            )

        assert "error" in result
        assert "File not found" in result["error"]
        # Error message should use the user-facing path, not an internal API path
        assert "missing.txt" in result["error"]
        assert "sessions/" not in result["error"]

    @pytest.mark.asyncio
    async def test_download_path_traversal_blocked(self):
        """Download rejects paths that escape the session directory."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_server(tmpdir)

            result = await server.download_file(
                session_id="test-session", path="../../../etc/passwd"
            )

        assert "error" in result
        assert "escapes session directory" in result["error"]

    @pytest.mark.asyncio
    async def test_download_uses_contents_api_not_kernel(self):
        """Verify download_file calls get_file_contents, not kernel execution."""
        from jupyter_interpreter_mcp import server

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = self._setup_server(tmpdir)

            mock_remote.get_file_contents = Mock(
                return_value={
                    "name": "data.csv",
                    "format": "text",
                    "content": "a,b\n1,2\n",
                }
            )

            result = await server.download_file(
                session_id="test-session", path="data.csv"
            )

        assert "error" not in result
        mock_remote.get_file_contents.assert_called_once()
        # Verify the API path was derived correctly (relative to jupyter_root)
        call_args = mock_remote.get_file_contents.call_args[0][0]
        assert "session" in call_args
        assert "data.csv" in call_args
        # Verify remote_client.execute was NOT called (no kernel interaction)
        mock_remote.execute.assert_not_called()
