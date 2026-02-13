"""Unit tests for server module argument parsing."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from jupyter_interpreter_mcp.remote import JupyterAuthError, JupyterConnectionError
from jupyter_interpreter_mcp.session import Session


class TestArgumentParsing:
    """Test argument parsing functionality."""

    def test_help_flag(self):
        """Test --help flag displays usage information."""
        with patch("sys.argv", ["jupyter-interpreter-mcp", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                from jupyter_interpreter_mcp.server import main

                main()
            assert exc_info.value.code == 0

    def test_version_flag(self):
        """Test --version flag displays version."""
        with patch("sys.argv", ["jupyter-interpreter-mcp", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                from jupyter_interpreter_mcp.server import main

                main()
            assert exc_info.value.code == 0

    def test_version_short_flag(self):
        """Test -v flag displays version."""
        with patch("sys.argv", ["jupyter-interpreter-mcp", "-v"]):
            with pytest.raises(SystemExit) as exc_info:
                from jupyter_interpreter_mcp.server import main

                main()
            assert exc_info.value.code == 0


class TestConfigurationPrecedence:
    """Test configuration hierarchy: CLI args > env vars > defaults."""

    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    @patch("jupyter_interpreter_mcp.server.mcp")
    def test_cli_args_override_env_vars(self, mock_mcp, mock_client_class):
        """Test CLI arguments override environment variables."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict(
            "os.environ",
            {
                "JUPYTER_BASE_URL": "http://env-url:8888",
                "JUPYTER_TOKEN": "env-token",
                "SESSIONS_DIR": "/env/notebooks",
            },
        ):
            with patch(
                "sys.argv",
                [
                    "jupyter-interpreter-mcp",
                    "--jupyter-base-url",
                    "http://cli-url:9999",
                    "--jupyter-token",
                    "cli-token",
                    "--sessions-dir",
                    "/cli/notebooks",
                ],
            ):
                from jupyter_interpreter_mcp.server import main

                main()

        # Verify CLI args were used (not env vars)
        mock_client_class.assert_called_once_with(
            base_url="http://cli-url:9999", auth_token="cli-token"
        )

    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    @patch("jupyter_interpreter_mcp.server.mcp")
    def test_env_vars_used_when_no_cli_args(self, mock_mcp, mock_client_class):
        """Test environment variables are used when CLI args are not provided."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict(
            "os.environ",
            {
                "JUPYTER_BASE_URL": "http://env-url:8888",
                "JUPYTER_TOKEN": "env-token",
                "SESSIONS_DIR": "/env/notebooks",
            },
        ):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                from jupyter_interpreter_mcp.server import main

                main()

        # Verify env vars were used
        mock_client_class.assert_called_once_with(
            base_url="http://env-url:8888", auth_token="env-token"
        )

    @patch("jupyter_interpreter_mcp.server.load_dotenv")
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    @patch("jupyter_interpreter_mcp.server.mcp")
    def test_defaults_used_when_no_args_or_env(
        self, mock_mcp, mock_client_class, mock_load_dotenv
    ):
        """Test defaults are used when neither CLI args nor env vars are provided."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict("os.environ", {"JUPYTER_TOKEN": "test-token"}, clear=True):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                from jupyter_interpreter_mcp.server import main

                main()

        # Verify defaults were used for base_url
        mock_client_class.assert_called_once_with(
            base_url="http://localhost:8888", auth_token="test-token"
        )

    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    @patch("jupyter_interpreter_mcp.server.mcp")
    def test_partial_cli_args_with_env_fallback(self, mock_mcp, mock_client_class):
        """Test partial CLI args with environment variable fallback."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict(
            "os.environ",
            {
                "JUPYTER_BASE_URL": "http://env-url:8888",
                "JUPYTER_TOKEN": "env-token",
            },
        ):
            with patch(
                "sys.argv",
                [
                    "jupyter-interpreter-mcp",
                    "--jupyter-token",
                    "cli-token",
                ],
            ):
                from jupyter_interpreter_mcp.server import main

                main()

        # Verify CLI token was used, but env base_url was used
        mock_client_class.assert_called_once_with(
            base_url="http://env-url:8888", auth_token="cli-token"
        )


class TestErrorHandling:
    """Test error handling in main function."""

    @patch("jupyter_interpreter_mcp.server.load_dotenv")
    def test_missing_token_error(self, mock_load_dotenv, capsys):
        """Test error when no token is provided anywhere."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                with pytest.raises(SystemExit) as exc_info:
                    from jupyter_interpreter_mcp.server import main

                    main()

                assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "JUPYTER_TOKEN is required" in captured.err

    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    def test_connection_error(self, mock_client_class, capsys):
        """Test connection error handling."""
        mock_client_class.side_effect = JupyterConnectionError("Connection refused")

        with patch.dict("os.environ", {"JUPYTER_TOKEN": "test-token"}):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                with pytest.raises(SystemExit) as exc_info:
                    from jupyter_interpreter_mcp.server import main

                    main()

                assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Failed to connect to Jupyter server" in captured.err

    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    def test_auth_error(self, mock_client_class, capsys):
        """Test authentication error handling."""
        mock_client = Mock()
        mock_client.validate_connection.side_effect = JupyterAuthError("Invalid token")
        mock_client_class.return_value = mock_client

        with patch.dict("os.environ", {"JUPYTER_TOKEN": "bad-token"}):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                with pytest.raises(SystemExit) as exc_info:
                    from jupyter_interpreter_mcp.server import main

                    main()

                assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Failed to connect to Jupyter server" in captured.err


class TestDotEnvLoading:
    """Test .env file loading."""

    @patch("jupyter_interpreter_mcp.server.load_dotenv")
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    @patch("jupyter_interpreter_mcp.server.mcp")
    def test_dotenv_loaded_before_parsing(
        self, mock_mcp, mock_client_class, mock_load_dotenv
    ):
        """Test that .env file is loaded before argument parsing."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict("os.environ", {"JUPYTER_TOKEN": "test-token"}):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                from jupyter_interpreter_mcp.server import main

                main()

        # Verify load_dotenv was called
        mock_load_dotenv.assert_called()


class TestLazySessionRestore:
    """Test on-demand session restoration behavior."""

    @pytest.mark.asyncio
    @patch(
        "jupyter_interpreter_mcp.server.restore_sessions_from_disk",
        new_callable=AsyncMock,
    )
    async def test_execute_code_restores_missing_session_on_demand(self, mock_restore):
        """Test execute_code lazily restores missing sessions."""
        from jupyter_interpreter_mcp import server

        session_id = "restored-session"
        current_time = 123.0

        mock_notebook = Mock()
        mock_notebook.execute_new_code = AsyncMock(
            return_value={"error": [], "result": ["ok\n"]}
        )
        mock_notebook.dump_to_file = AsyncMock()

        async def restore_side_effect(target_session_id=None):
            if target_session_id == session_id:
                server.sessions[session_id] = Session(
                    id=session_id,
                    kernel_id="kernel-1",
                    created_at=current_time,
                    last_access=current_time,
                    directory=f"/sessions/{session_id}",
                )
                server.notebooks[session_id] = mock_notebook
                return 1
            return 0

        mock_restore.side_effect = restore_side_effect

        server.sessions = {}
        server.notebooks = {}
        server.remote_client = Mock()
        server.remote_client.update_session_metadata = AsyncMock()

        result = await server.execute_code("print('ok')", session_id)

        assert result["error"] == []
        assert result["session_id"] == session_id
        mock_restore.assert_awaited_once_with(session_id)
        server.remote_client.update_session_metadata.assert_awaited_once()
        mock_notebook.dump_to_file.assert_awaited_once()


class TestStartupRestoreConfiguration:
    """Test startup restore configuration for performance tuning."""

    @patch(
        "jupyter_interpreter_mcp.server.restore_sessions_from_disk",
        new_callable=AsyncMock,
    )
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    @patch("jupyter_interpreter_mcp.server.mcp")
    def test_skips_eager_restore_by_default(
        self, mock_mcp, mock_client_class, mock_restore
    ):
        """Test startup skips full restore unless explicitly enabled."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict("os.environ", {"JUPYTER_TOKEN": "test-token"}):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                from jupyter_interpreter_mcp.server import main

                main()

        mock_restore.assert_not_awaited()
        mock_mcp.run.assert_called_once()

    @patch(
        "jupyter_interpreter_mcp.server.restore_sessions_from_disk",
        new_callable=AsyncMock,
    )
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    @patch("jupyter_interpreter_mcp.server.mcp")
    def test_can_enable_eager_restore(self, mock_mcp, mock_client_class, mock_restore):
        """Test eager restore can still be enabled via CLI flag."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict("os.environ", {"JUPYTER_TOKEN": "test-token"}):
            with patch(
                "sys.argv",
                ["jupyter-interpreter-mcp", "--restore-sessions-on-startup"],
            ):
                from jupyter_interpreter_mcp.server import main

                main()

        mock_restore.assert_awaited_once_with()
        mock_mcp.run.assert_called_once()


class TestListDirTool:
    """Test list_dir tool functionality.

    NOTE: These tests are obsolete after the session-based refactor.
    The list_dir function now requires a session_id and uses kernel execution
    instead of the Jupyter Contents API. These tests are marked as skipped
    and should be rewritten or removed.
    """

    @pytest.mark.skip(reason="Obsolete after session-based refactor")
    @pytest.mark.skip(reason="Obsolete after session-based refactor")
    @pytest.mark.asyncio
    async def test_list_dir_success(self):
        """Test successful directory listing."""
        from jupyter_interpreter_mcp import server

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            return_value={
                "name": "",
                "path": ".",
                "type": "directory",
                "content": [
                    {
                        "name": "file1.txt",
                        "path": "file1.txt",
                        "type": "file",
                        "size": 1024,
                        "last_modified": "2024-01-29T12:00:00Z",
                    },
                    {
                        "name": "data.csv",
                        "path": "data.csv",
                        "type": "file",
                        "size": 2048000,
                        "last_modified": "2024-01-29T11:30:00Z",
                    },
                    {
                        "name": "subdir",
                        "path": "subdir",
                        "type": "directory",
                        "size": None,
                        "last_modified": "2024-01-29T11:00:00Z",
                    },
                ],
            }
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            assert result["error"] == ""
            assert len(result["result"]) == 3
            assert "file file1.txt (1.0 KB)" in result["result"][0]
            assert "file data.csv (2.0 MB)" in result["result"][1]
            assert "directory subdir (directory)" in result["result"][2]
            mock_remote_client.get_contents.assert_called_once_with(".")

    @pytest.mark.skip(reason="Obsolete after session-based refactor")
    @pytest.mark.asyncio
    async def test_list_dir_empty_directory(self):
        """Test listing an empty directory."""
        from jupyter_interpreter_mcp import server

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            return_value={
                "name": "",
                "path": ".",
                "type": "directory",
                "content": [],
            }
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            assert result["error"] == ""
            assert len(result["result"]) == 1
            assert result["result"][0] == "(empty directory)"
            mock_remote_client.get_contents.assert_called_once_with(".")

    @pytest.mark.skip(reason="Obsolete after session-based refactor")
    @pytest.mark.asyncio
    async def test_list_dir_connection_error(self):
        """Test connection error handling."""
        from jupyter_interpreter_mcp import server

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            side_effect=JupyterConnectionError("Connection refused")
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            assert "error" in result
            assert "Connection refused" in result["error"]
            assert result["result"] == []
            mock_remote_client.get_contents.assert_called_once_with(".")

    @pytest.mark.skip(reason="Obsolete after session-based refactor")
    @pytest.mark.asyncio
    async def test_list_dir_path_not_found(self):
        """Test 404 path not found error handling."""
        from jupyter_interpreter_mcp import server

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            side_effect=JupyterConnectionError("Path not found: .")
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            assert "error" in result
            assert "Path not found" in result["error"]
            assert result["result"] == []
            mock_remote_client.get_contents.assert_called_once_with(".")

    @pytest.mark.skip(reason="Obsolete after session-based refactor")
    @pytest.mark.asyncio
    async def test_list_dir_permission_denied(self):
        """Test 403 permission denied error handling."""
        from jupyter_interpreter_mcp import server

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            side_effect=JupyterAuthError("Authorization failed: 403")
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            assert "error" in result
            assert "Authorization failed" in result["error"]
            assert result["result"] == []
            mock_remote_client.get_contents.assert_called_once_with(".")

    @pytest.mark.skip(reason="Obsolete after session-based refactor")
    @pytest.mark.asyncio
    async def test_list_dir_unexpected_exception(self):
        """Test unexpected exception handling."""
        from jupyter_interpreter_mcp import server

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(side_effect=RuntimeError("boom"))

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            assert "error" in result
            assert "RuntimeError" in result["error"]
            assert "boom" in result["error"]
            assert result["result"] == []
            mock_remote_client.get_contents.assert_called_once_with(".")
