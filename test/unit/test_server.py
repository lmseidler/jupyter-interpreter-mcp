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
    """Test list_dir tool functionality."""

    @pytest.mark.asyncio
    @patch("jupyter_interpreter_mcp.server.ensure_session_available")
    @patch("jupyter_interpreter_mcp.server.remote_client")
    @patch("jupyter_interpreter_mcp.server.sessions", new_callable=dict)
    @patch("jupyter_interpreter_mcp.server.sessions_dir", "/home/jovyan/sessions")
    @patch("jupyter_interpreter_mcp.server.os.getcwd", return_value="/home/jovyan")
    async def test_list_dir_success(
        self, mock_getcwd, mock_sessions, mock_remote_client, mock_ensure
    ):
        """Test successful directory listing."""
        import time

        from jupyter_interpreter_mcp import server

        mock_session = Mock(spec=Session)
        mock_session.directory = "/home/jovyan/sessions/test-session"
        mock_session.kernel_id = "test-kernel"
        mock_session.last_access = time.time()
        mock_session.is_expired.return_value = False
        mock_sessions["test-session"] = mock_session

        mock_remote_client.get_contents.return_value = {
            "type": "directory",
            "content": [
                {
                    "name": "file1.txt",
                    "type": "file",
                    "size": 1024,
                    "last_modified": "2024-01-29T12:00:00Z",
                },
                {
                    "name": "subdir",
                    "type": "directory",
                    "last_modified": "2024-01-29T11:00:00Z",
                },
            ],
        }
        mock_remote_client.update_session_metadata = AsyncMock()

        result = await server.list_dir(session_id="test-session")

        assert result["error"] == ""
        assert len(result["result"]) == 2
        # Directories first, then files alphabetically
        assert (
            "directory subdir - modified: 2024-01-29T11:00:00Z" == result["result"][0]
        )
        assert (
            "file file1.txt (1.0 KB) - modified: 2024-01-29T12:00:00Z"
            == result["result"][1]
        )

        # Verify path calculation:
        # /home/jovyan/sessions/test-session -> sessions/test-session
        mock_remote_client.get_contents.assert_called_once_with("sessions/test-session")

    @pytest.mark.asyncio
    @patch("jupyter_interpreter_mcp.server.ensure_session_available")
    @patch("jupyter_interpreter_mcp.server.remote_client")
    @patch("jupyter_interpreter_mcp.server.sessions", new_callable=dict)
    @patch("jupyter_interpreter_mcp.server.sessions_dir", "/home/jovyan/sessions")
    @patch("jupyter_interpreter_mcp.server.os.getcwd", return_value="/home/jovyan")
    async def test_list_dir_empty_directory(
        self, mock_getcwd, mock_sessions, mock_remote_client, mock_ensure
    ):
        """Test listing an empty directory."""
        import time

        from jupyter_interpreter_mcp import server

        mock_session = Mock(spec=Session)
        mock_session.directory = "/home/jovyan/sessions/test-session"
        mock_session.kernel_id = "test-kernel"
        mock_session.last_access = time.time()
        mock_session.is_expired.return_value = False
        mock_sessions["test-session"] = mock_session

        mock_remote_client.get_contents.return_value = {
            "type": "directory",
            "content": [],
        }
        mock_remote_client.update_session_metadata = AsyncMock()

        result = await server.list_dir(session_id="test-session")

        assert result["error"] == ""
        assert result["result"] == ["(empty directory)"]

    @pytest.mark.asyncio
    @patch("jupyter_interpreter_mcp.server.ensure_session_available")
    @patch("jupyter_interpreter_mcp.server.remote_client")
    @patch("jupyter_interpreter_mcp.server.sessions", new_callable=dict)
    @patch("jupyter_interpreter_mcp.server.sessions_dir", "/home/jovyan/sessions")
    @patch("jupyter_interpreter_mcp.server.os.getcwd", return_value="/home/jovyan")
    async def test_list_dir_not_found(
        self, mock_getcwd, mock_sessions, mock_remote_client, mock_ensure
    ):
        """Test directory not found."""
        import time

        from jupyter_interpreter_mcp import server
        from jupyter_interpreter_mcp.remote import JupyterConnectionError

        mock_session = Mock(spec=Session)
        mock_session.directory = "/home/jovyan/sessions/test-session"
        mock_session.last_access = time.time()
        mock_session.is_expired.return_value = False
        mock_sessions["test-session"] = mock_session

        mock_remote_client.get_contents.side_effect = JupyterConnectionError(
            "Path not found: ghost"
        )

        result = await server.list_dir(session_id="test-session", path="ghost")

        assert "Path not found: ghost" in result["error"]
        assert result["result"] == []

    @pytest.mark.asyncio
    @patch("jupyter_interpreter_mcp.server.ensure_session_available")
    @patch("jupyter_interpreter_mcp.server.remote_client")
    @patch("jupyter_interpreter_mcp.server.sessions", new_callable=dict)
    @patch("jupyter_interpreter_mcp.server.sessions_dir", "/home/jovyan/sessions")
    @patch("jupyter_interpreter_mcp.server.os.getcwd", return_value="/home/jovyan")
    async def test_list_dir_permission_denied(
        self, mock_getcwd, mock_sessions, mock_remote_client, mock_ensure
    ):
        """Test permission denied."""
        import time

        from jupyter_interpreter_mcp import server
        from jupyter_interpreter_mcp.remote import JupyterAuthError

        mock_session = Mock(spec=Session)
        mock_session.directory = "/home/jovyan/sessions/test-session"
        mock_session.last_access = time.time()
        mock_session.is_expired.return_value = False
        mock_sessions["test-session"] = mock_session

        mock_remote_client.get_contents.side_effect = JupyterAuthError(
            "Permission denied"
        )

        result = await server.list_dir(session_id="test-session")

        assert "Permission denied" in result["error"]
        assert result["result"] == []
