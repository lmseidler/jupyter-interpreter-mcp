"""Unit tests for server module argument parsing."""

from unittest.mock import Mock, patch

import pytest

from jupyter_interpreter_mcp.remote import JupyterAuthError, JupyterConnectionError


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
                "NOTEBOOKS_FOLDER": "/env/notebooks",
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
                    "--notebooks-folder",
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
                "NOTEBOOKS_FOLDER": "/env/notebooks",
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
