"""Unit tests for the upload_file_path tool."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from jupyter_interpreter_mcp.session import Session


class TestUploadFilePath:
    """Test upload_file_path tool functionality."""

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

        mock_notebook = Mock()
        mock_notebook.execute_new_code = AsyncMock(
            return_value={"error": [], "result": ["OK\n"]}
        )
        server.notebooks = {session_id: mock_notebook}

        mock_remote = Mock()
        mock_remote.update_session_metadata = AsyncMock()
        server.remote_client = mock_remote

        return mock_notebook

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

            mock_notebook = self._setup_server(server, session_dir)

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
            # Verify notebook.execute_new_code was called for the upload
            assert mock_notebook.execute_new_code.await_count >= 1

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

            mock_notebook = self._setup_server(server, session_dir)

            # Simulate that destination exists
            mock_notebook.execute_new_code = AsyncMock(
                return_value={"error": [], "result": ["EXISTS\n"]}
            )

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

            mock_notebook = self._setup_server(server, session_dir)
            mock_notebook.execute_new_code = AsyncMock(
                return_value={"error": [], "result": ["OK\n"]}
            )

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
