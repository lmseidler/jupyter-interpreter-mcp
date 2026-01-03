"""Unit tests for Notebook class."""

from unittest.mock import Mock, patch

import pytest

from jupyter_interpreter_mcp.notebook import Notebook
from jupyter_interpreter_mcp.remote import RemoteJupyterClient


@pytest.fixture
def mock_remote_client():
    """Create a mock RemoteJupyterClient for testing."""
    client = Mock(spec=RemoteJupyterClient)
    client.create_kernel.return_value = "kernel-123"
    client.get_kernel_connection_info.return_value = {
        "shell_port": 50001,
        "iopub_port": 50002,
        "stdin_port": 50003,
        "control_port": 50004,
        "hb_port": 50005,
        "ip": "127.0.0.1",
        "key": "test-key",
        "transport": "tcp",
        "signature_scheme": "hmac-sha256",
    }
    return client


@pytest.fixture
def mock_kernel_client():
    """Create a mock BlockingKernelClient for testing."""
    client = Mock()
    client.start_channels = Mock()
    client.wait_for_ready = Mock()
    client.load_connection_info = Mock()
    client.execute_interactive = Mock()
    client.execute = Mock()
    return client


class TestNotebookInit:
    """Test Notebook initialization."""

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_init_success(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test successful notebook initialization."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=42,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Verify kernel was created
        mock_remote_client.create_kernel.assert_called_once()
        assert notebook.kernel_id == "kernel-123"

        # Verify connection info was retrieved
        mock_remote_client.get_kernel_connection_info.assert_called_once_with(
            "kernel-123"
        )

        # Verify ZMQ client was set up
        mock_kernel_client.load_connection_info.assert_called_once()
        mock_kernel_client.start_channels.assert_called_once()
        mock_kernel_client.wait_for_ready.assert_called_once_with(timeout=10)

        # Verify attributes
        assert notebook.session_id == 42
        assert notebook.file_path == "/home/jovyan/notebooks/42.txt"
        assert notebook.history == []

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_init_connection_timeout(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test notebook initialization with connection timeout."""
        mock_client_class.return_value = mock_kernel_client
        mock_kernel_client.wait_for_ready.side_effect = TimeoutError(
            "Connection timeout"
        )

        with pytest.raises(TimeoutError, match="Connection timeout"):
            Notebook(
                session_id=42,
                remote_client=mock_remote_client,
                notebooks_folder="/home/jovyan/notebooks",
            )


class TestExecuteNewCode:
    """Test code execution."""

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_execute_new_code_success(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test successful code execution."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Mock execute_interactive to call output_hook with stream message
        def mock_execute(code, output_hook, stop_on_error):
            output_hook({"msg_type": "stream", "content": {"text": "Hello, World!\n"}})

        mock_kernel_client.execute_interactive.side_effect = mock_execute

        result = notebook.execute_new_code("print('Hello, World!')")

        assert result["error"] == []
        assert result["result"] == ["Hello, World!\n"]
        assert len(notebook.history) == 1
        assert "\nprint('Hello, World!')" in notebook.history[0]

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_execute_new_code_with_result(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test code execution with execute_result."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Mock execute_interactive with execute_result message
        def mock_execute(code, output_hook, stop_on_error):
            output_hook(
                {
                    "msg_type": "execute_result",
                    "content": {"data": {"text/plain": "42"}},
                }
            )

        mock_kernel_client.execute_interactive.side_effect = mock_execute

        result = notebook.execute_new_code("21 + 21")

        assert result["error"] == []
        assert "Execution Result: 42" in result["result"]
        assert len(notebook.history) == 1

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_execute_new_code_with_error(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test code execution with error."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Mock execute_interactive with error message
        def mock_execute(code, output_hook, stop_on_error):
            output_hook(
                {
                    "msg_type": "error",
                    "content": {
                        "ename": "NameError",
                        "evalue": "name 'x' is not defined",
                    },
                }
            )

        mock_kernel_client.execute_interactive.side_effect = mock_execute

        result = notebook.execute_new_code("print(x)")

        assert "Error: NameError: name 'x' is not defined" in result["error"]
        assert result["result"] == []
        # History should not be updated on error
        assert len(notebook.history) == 0


class TestDumpToFile:
    """Test dumping history to file."""

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_dump_to_file(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test dumping history to remote file."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        notebook.history = ["\nprint('test1')", "\nprint('test2')"]

        notebook.dump_to_file()

        # Verify execute was called with code to write file
        mock_kernel_client.execute.assert_called_once()
        call_args = mock_kernel_client.execute.call_args
        code = call_args[0][0]

        # Verify the code contains file write operations
        assert "os.makedirs" in code
        assert notebook.file_path in code
        assert "with open" in code
        assert notebook.history[0] in code or repr(notebook.history) in code
        assert call_args[1]["silent"] is True

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_dump_to_file_empty_history(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test dumping empty history to file."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # History is empty by default
        notebook.dump_to_file()

        # Should still call execute
        mock_kernel_client.execute.assert_called_once()


class TestLoadFromFile:
    """Test loading history from file."""

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_load_from_file_success(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test successfully loading history from file."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Mock execute_interactive to simulate file read
        call_count = [0]

        def mock_execute(code, output_hook, stop_on_error):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: reading the file
                output_hook(
                    {
                        "msg_type": "stream",
                        "content": {
                            "text": "FILE_CONTENT_START\nx = 10\nFILE_CONTENT_END\n"
                        },
                    }
                )
            else:
                # Second call: re-executing the content
                pass

        mock_kernel_client.execute_interactive.side_effect = mock_execute

        result = notebook.load_from_file()

        assert result is True
        # Should call execute_interactive twice: once to read, once to restore
        assert mock_kernel_client.execute_interactive.call_count == 2

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_load_from_file_not_found(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test loading from non-existent file."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Mock execute_interactive to simulate file not found
        def mock_execute(code, output_hook, stop_on_error):
            output_hook({"msg_type": "stream", "content": {"text": "FILE_NOT_FOUND\n"}})

        mock_kernel_client.execute_interactive.side_effect = mock_execute

        result = notebook.load_from_file()

        assert result is False

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_load_from_file_with_error(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test loading from file with execution error."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Mock execute_interactive to simulate error during file read
        def mock_execute(code, output_hook, stop_on_error):
            output_hook(
                {
                    "msg_type": "error",
                    "content": {"ename": "OSError", "evalue": "Cannot read file"},
                }
            )

        mock_kernel_client.execute_interactive.side_effect = mock_execute

        result = notebook.load_from_file()

        assert result is False

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_load_from_file_exception(
        self, mock_client_class, mock_remote_client, mock_kernel_client
    ):
        """Test loading from file with exception."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        # Mock execute_interactive to raise exception
        mock_kernel_client.execute_interactive.side_effect = Exception(
            "Unexpected error"
        )

        result = notebook.load_from_file()

        assert result is False


class TestClose:
    """Test notebook cleanup."""

    @patch("jupyter_interpreter_mcp.notebook.BlockingKernelClient")
    def test_close(self, mock_client_class, mock_remote_client, mock_kernel_client):
        """Test closing notebook shuts down kernel."""
        mock_client_class.return_value = mock_kernel_client

        notebook = Notebook(
            session_id=1,
            remote_client=mock_remote_client,
            notebooks_folder="/home/jovyan/notebooks",
        )

        notebook.close()

        # Verify kernel was shut down
        mock_remote_client.shutdown_kernel.assert_called_once_with("kernel-123")
