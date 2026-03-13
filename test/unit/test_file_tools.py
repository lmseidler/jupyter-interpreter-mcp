"""Unit tests for the read_file, write_file, and edit_file MCP tools."""

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import jupyter_interpreter_mcp.session as session_module
from jupyter_interpreter_mcp import server
from jupyter_interpreter_mcp.remote import JupyterConnectionError
from jupyter_interpreter_mcp.session import Session

# ---------------------------------------------------------------------------
# Shared setup helper
# ---------------------------------------------------------------------------


def _setup_server(
    tmpdir: str,
    session_id: str = "test-session",
    *,
    jupyter_root: str | None = None,
) -> tuple[str, Mock]:
    """Populate server module globals for testing.

    Creates a real session directory inside *tmpdir*, registers a Session
    object in ``server.sessions``, and wires up a :class:`~unittest.mock.Mock`
    remote client.  The mock's ``update_session_metadata`` method is an
    :class:`~unittest.mock.AsyncMock`.

    :param tmpdir: Temporary directory to create the session under.
    :param session_id: Session identifier to register.
    :param jupyter_root: Override for ``server.jupyter_root``.  Defaults to
        *tmpdir*.
    :return: ``(session_dir, mock_remote_client)``
    """
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
    server.jupyter_root = jupyter_root if jupyter_root is not None else tmpdir

    mock_remote = Mock()
    mock_remote.update_session_metadata = AsyncMock()
    mock_remote.put_contents = Mock(return_value={})
    mock_remote.create_directory = Mock()
    server.remote_client = mock_remote

    # Populate notebooks so ensure_session_available short-circuits without
    # calling restore_sessions_from_disk (which requires a live Jupyter server).
    server.notebooks = {session_id: Mock()}

    return session_dir, mock_remote


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    """Test read_file tool."""

    def setup_method(self):
        session_module._configured_allowed_dirs = None

    @pytest.mark.asyncio
    async def test_read_full_text_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)
            mock_remote.get_file_contents = Mock(
                return_value={"format": "text", "content": "line1\nline2\nline3\n"}
            )

            result = await server.read_file(session_id="test-session", path="file.txt")

        assert "error" not in result
        assert result["total_lines"] == 3
        assert result["truncated"] is False
        assert result["offset"] == 1
        assert result["limit"] == 200
        lines = result["lines"]
        assert lines[0] == "1: line1"
        assert lines[1] == "2: line2"
        assert lines[2] == "3: line3"

    @pytest.mark.asyncio
    async def test_read_with_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={
                    "format": "text",
                    "content": "\n".join(f"line{i}" for i in range(1, 11)),
                }
            )

            result = await server.read_file(
                session_id="test-session", path="big.txt", offset=4
            )

        assert "error" not in result
        assert result["total_lines"] == 10
        assert result["offset"] == 4
        # Lines should start at line 4
        assert result["lines"][0] == "4: line4"

    @pytest.mark.asyncio
    async def test_read_with_limit_truncates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={
                    "format": "text",
                    "content": "\n".join(f"row{i}" for i in range(1, 201)),
                }
            )

            result = await server.read_file(
                session_id="test-session", path="data.csv", limit=5
            )

        assert "error" not in result
        assert len(result["lines"]) == 5
        assert result["truncated"] is True
        assert result["total_lines"] == 200

    @pytest.mark.asyncio
    async def test_read_offset_and_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={
                    "format": "text",
                    "content": "\n".join(str(i) for i in range(1, 21)),
                }
            )

            result = await server.read_file(
                session_id="test-session", path="f.txt", offset=5, limit=3
            )

        assert "error" not in result
        assert len(result["lines"]) == 3
        assert result["lines"][0] == "5: 5"
        assert result["lines"][2] == "7: 7"

    @pytest.mark.asyncio
    async def test_read_binary_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={"format": "base64", "content": "SGVsbG8="}
            )

            result = await server.read_file(session_id="test-session", path="image.png")

        assert "error" in result
        assert "Binary" in result["error"]

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                side_effect=JupyterConnectionError("File not found")
            )

            result = await server.read_file(
                session_id="test-session", path="missing.txt"
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_read_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.read_file(
                session_id="test-session", path="../../etc/passwd"
            )

        assert "error" in result
        assert "escapes" in result["error"]

    @pytest.mark.asyncio
    async def test_read_sensitive_file_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.read_file(session_id="test-session", path=".env")

        assert "error" in result
        assert "sensitive" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_read_invalid_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.read_file(
                session_id="test-session", path="f.txt", offset=0
            )

        assert "error" in result
        assert "offset" in result["error"]

    @pytest.mark.asyncio
    async def test_read_offset_beyond_file_length_returns_empty(self):
        """offset past the end of the file returns empty lines, not an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={
                    "format": "text",
                    "content": "line1\nline2\nline3\n",
                }
            )

            result = await server.read_file(
                session_id="test-session", path="f.txt", offset=1000
            )

        assert "error" not in result
        assert result["total_lines"] == 3
        assert result["lines"] == []
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_read_limit_zero_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.read_file(
                session_id="test-session", path="f.txt", limit=0
            )

        assert "error" in result
        assert "limit" in result["error"]

    @pytest.mark.asyncio
    async def test_read_uses_contents_api_not_kernel(self):
        """Verify read_file calls get_file_contents, not kernel execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)
            mock_remote.get_file_contents = Mock(
                return_value={"format": "text", "content": "hello\n"}
            )

            result = await server.read_file(session_id="test-session", path="hello.txt")

        assert "error" not in result
        mock_remote.get_file_contents.assert_called_once()
        # Verify the API path is relative (no direct fs path passed)
        call_arg = mock_remote.get_file_contents.call_args[0][0]
        assert "session" in call_arg
        assert "hello.txt" in call_arg
        mock_remote.execute.assert_not_called()


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    """Test write_file tool."""

    def setup_method(self):
        session_module._configured_allowed_dirs = None

    @pytest.mark.asyncio
    async def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)

            result = await server.write_file(
                session_id="test-session",
                path="output.txt",
                content="hello world\n",
            )

        assert "error" not in result
        assert result["status"] == "ok"
        assert result["bytes_written"] == len(b"hello world\n")
        mock_remote.put_contents.assert_called_once()
        # Verify text format is used
        call_args = mock_remote.put_contents.call_args
        assert "text" in str(call_args)

    @pytest.mark.asyncio
    async def test_write_reports_bytes_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            content = "café\n"  # multibyte UTF-8

            result = await server.write_file(
                session_id="test-session", path="unicode.txt", content=content
            )

        assert "error" not in result
        assert result["bytes_written"] == len(content.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_write_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.write_file(
                session_id="test-session",
                path="../../../tmp/evil.sh",
                content="rm -rf /",
            )

        assert "error" in result
        assert "escapes" in result["error"]

    @pytest.mark.asyncio
    async def test_write_sensitive_file_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.write_file(
                session_id="test-session",
                path=".env",
                content="SECRET=hacked",
            )

        assert "error" in result
        assert "sensitive" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_write_uses_put_contents_not_kernel(self):
        """Verify write_file calls put_contents (Contents API), not kernel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)

            result = await server.write_file(
                session_id="test-session", path="data.txt", content="data\n"
            )

        assert "error" not in result
        mock_remote.put_contents.assert_called_once()
        mock_remote.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_creates_parent_directory(self):
        """Verify create_directory is called for the parent path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)

            result = await server.write_file(
                session_id="test-session",
                path="subdir/deep/file.txt",
                content="nested\n",
            )

        assert "error" not in result
        mock_remote.create_directory.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_empty_path_resolves_to_session_dir(self):
        """write_file with path='' targets the session directory itself.

        The session directory is a valid target from the sandbox perspective
        (validate_path allows it), so the call reaches put_contents.  This
        test documents the current behavior: the write is not blocked by
        path validation and succeeds (the remote Jupyter server would
        ultimately reject writing a file at a directory path, but that is
        outside the scope of the unit test).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)

            result = await server.write_file(
                session_id="test-session",
                path="",
                content="data\n",
            )

        # No path-traversal or sensitive-file error is raised; the call
        # propagates to put_contents as documented above.
        assert "error" not in result
        mock_remote.put_contents.assert_called_once()


# ---------------------------------------------------------------------------
# edit_file
# ---------------------------------------------------------------------------


class TestEditFile:
    """Test edit_file tool."""

    def setup_method(self):
        session_module._configured_allowed_dirs = None

    @pytest.mark.asyncio
    async def test_edit_simple_replacement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)
            mock_remote.get_file_contents = Mock(
                return_value={"format": "text", "content": "foo = 1\nbar = 2\n"}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="config.py",
                old_string="foo = 1",
                new_string="foo = 42",
            )

        assert "error" not in result
        assert result["status"] == "ok"
        assert result["replacements"] == 1
        # Verify write-back was called
        mock_remote.put_contents.assert_called_once()
        written_content = mock_remote.put_contents.call_args[0][1]
        assert "foo = 42" in written_content
        assert "bar = 2" in written_content

    @pytest.mark.asyncio
    async def test_edit_multiline_replacement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={
                    "format": "text",
                    "content": "def old():\n    return 1\n",
                }
            )

            result = await server.edit_file(
                session_id="test-session",
                path="module.py",
                old_string="def old():\n    return 1\n",
                new_string="def new():\n    return 99\n",
            )

        assert "error" not in result
        written = server.remote_client.put_contents.call_args[0][1]  # type: ignore[attr-defined]
        assert "new()" in written
        assert "old()" not in written

    @pytest.mark.asyncio
    async def test_edit_not_found_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={"format": "text", "content": "something else\n"}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="f.txt",
                old_string="does not exist",
                new_string="replacement",
            )

        assert "error" in result
        assert "not found" in result["error"]
        server.remote_client.put_contents.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_edit_ambiguous_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={"format": "text", "content": "x = 1\nx = 1\n"}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="f.py",
                old_string="x = 1",
                new_string="x = 2",
            )

        assert "error" in result
        assert "occurrences" in result["error"]
        server.remote_client.put_contents.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_edit_replace_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={"format": "text", "content": "x = 1\nx = 1\nx = 1\n"}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="f.py",
                old_string="x = 1",
                new_string="x = 99",
                replace_all=True,
            )

        assert "error" not in result
        assert result["replacements"] == 3
        written = server.remote_client.put_contents.call_args[0][1]  # type: ignore[attr-defined]
        assert written.count("x = 99") == 3
        assert "x = 1" not in written

    @pytest.mark.asyncio
    async def test_edit_binary_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={"format": "base64", "content": "SGVsbG8="}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="image.png",
                old_string="foo",
                new_string="bar",
            )

        assert "error" in result
        assert "Binary" in result["error"]
        server.remote_client.put_contents.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                side_effect=JupyterConnectionError("File not found")
            )

            result = await server.edit_file(
                session_id="test-session",
                path="missing.py",
                old_string="foo",
                new_string="bar",
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_edit_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.edit_file(
                session_id="test-session",
                path="../../etc/hosts",
                old_string="localhost",
                new_string="evil",
            )

        assert "error" in result
        assert "escapes" in result["error"]

    @pytest.mark.asyncio
    async def test_edit_sensitive_file_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)

            result = await server.edit_file(
                session_id="test-session",
                path=".env",
                old_string="SECRET=old",
                new_string="SECRET=new",
            )

        assert "error" in result
        assert "sensitive" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_edit_line_trimmed_fallback(self):
        """edit_file should succeed via line-trimmed strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            # Content has trailing spaces; old_string does not.
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={
                    "format": "text",
                    "content": "value = 1   \nother = 2\n",
                }
            )

            result = await server.edit_file(
                session_id="test-session",
                path="f.py",
                old_string="value = 1",
                new_string="value = 99",
            )

        assert "error" not in result
        assert result["replacements"] == 1

    @pytest.mark.asyncio
    async def test_edit_indentation_flexible_fallback(self):
        """edit_file should succeed via indentation-flexible strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={
                    "format": "text",
                    "content": "    def foo():\n        return 1\n",
                }
            )

            # old_string uses 2-space indent; file uses 4-space.
            result = await server.edit_file(
                session_id="test-session",
                path="module.py",
                old_string="  def foo():\n    return 1",
                new_string="    def foo():\n        return 42\n",
            )

        assert "error" not in result
        assert result["replacements"] == 1

    @pytest.mark.asyncio
    async def test_edit_empty_old_string_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={"format": "text", "content": "stuff\n"}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="f.txt",
                old_string="",
                new_string="new",
            )

        assert "error" in result
        server.remote_client.put_contents.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_edit_identical_old_and_new_string_is_noop(self):
        """edit_file with old_string == new_string succeeds as a no-op.

        The replacement count is 1 and the file content is written back
        unchanged.  This is expected behavior: callers should not assume the
        tool short-circuits when the strings are identical.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_server(tmpdir)
            original = "value = 1\n"
            server.remote_client.get_file_contents = Mock(  # type: ignore[method-assign]
                return_value={"format": "text", "content": original}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="f.py",
                old_string="value = 1",
                new_string="value = 1",
            )

        assert "error" not in result
        assert result["status"] == "ok"
        assert result["replacements"] == 1
        # The file is written back (no short-circuit for identical strings).
        server.remote_client.put_contents.assert_called_once()  # type: ignore[attr-defined]
        written_content = server.remote_client.put_contents.call_args[0][1]  # type: ignore[attr-defined]
        assert written_content == original

    @pytest.mark.asyncio
    async def test_edit_uses_contents_api_not_kernel(self):
        """Verify edit_file uses get_file_contents + put_contents, not kernel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir, mock_remote = _setup_server(tmpdir)
            mock_remote.get_file_contents = Mock(
                return_value={"format": "text", "content": "alpha\n"}
            )

            result = await server.edit_file(
                session_id="test-session",
                path="f.txt",
                old_string="alpha",
                new_string="beta",
            )

        assert "error" not in result
        mock_remote.get_file_contents.assert_called_once()
        mock_remote.put_contents.assert_called_once()
        mock_remote.execute.assert_not_called()
