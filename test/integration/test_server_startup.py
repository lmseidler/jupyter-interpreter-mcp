"""Integration tests for server module."""

from unittest.mock import Mock, patch


class TestServerStartup:
    """Test server startup with various configurations."""

    @patch("jupyter_interpreter_mcp.server.mcp")
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    def test_server_starts_with_cli_args(self, mock_client_class, mock_mcp):
        """Test server starts successfully with CLI arguments."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch(
            "sys.argv",
            [
                "jupyter-interpreter-mcp",
                "--jupyter-base-url",
                "http://test:8888",
                "--jupyter-token",
                "test-token",
                "--notebooks-folder",
                "/test/path",
            ],
        ):
            from jupyter_interpreter_mcp.server import main

            main()

        # Verify client was initialized with correct parameters
        mock_client_class.assert_called_once_with(
            base_url="http://test:8888", auth_token="test-token"
        )
        mock_client.validate_connection.assert_called_once()
        mock_mcp.run.assert_called_once()

    @patch("jupyter_interpreter_mcp.server.load_dotenv")
    @patch("jupyter_interpreter_mcp.server.mcp")
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    def test_server_starts_with_env_vars(
        self, mock_client_class, mock_mcp, mock_load_dotenv
    ):
        """Test server starts successfully with environment variables only."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict(
            "os.environ",
            {
                "JUPYTER_BASE_URL": "http://env:8888",
                "JUPYTER_TOKEN": "env-token",
                "NOTEBOOKS_FOLDER": "/env/path",
            },
        ):
            with patch("sys.argv", ["jupyter-interpreter-mcp"]):
                from jupyter_interpreter_mcp.server import main

                main()

        # Verify client was initialized with env var values
        mock_client_class.assert_called_once_with(
            base_url="http://env:8888", auth_token="env-token"
        )
        mock_client.validate_connection.assert_called_once()
        mock_mcp.run.assert_called_once()

    @patch("jupyter_interpreter_mcp.server.mcp")
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    def test_server_starts_with_mixed_config(self, mock_client_class, mock_mcp):
        """Test server starts with mixed CLI args and env vars."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict(
            "os.environ",
            {
                "JUPYTER_BASE_URL": "http://env:8888",
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

        # Verify CLI token overrode env token, but env base_url was used
        mock_client_class.assert_called_once_with(
            base_url="http://env:8888", auth_token="cli-token"
        )
        mock_client.validate_connection.assert_called_once()
        mock_mcp.run.assert_called_once()

    @patch("jupyter_interpreter_mcp.server.mcp")
    @patch("jupyter_interpreter_mcp.server.RemoteJupyterClient")
    def test_configuration_values_set_globally(self, mock_client_class, mock_mcp):
        """Verify configuration values are correctly set as global variables."""
        mock_client = Mock()
        mock_client.validate_connection = Mock()
        mock_client_class.return_value = mock_client

        with patch.dict("os.environ", {"JUPYTER_TOKEN": "test-token"}):
            with patch(
                "sys.argv",
                [
                    "jupyter-interpreter-mcp",
                    "--notebooks-folder",
                    "/custom/path",
                ],
            ):
                from jupyter_interpreter_mcp import server

                server.main()

                # Verify global variables are set
                assert server.remote_client == mock_client
                assert server.notebooks_folder == "/custom/path"
