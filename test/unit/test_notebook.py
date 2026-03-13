"""Unit tests for Notebook class."""

from unittest.mock import AsyncMock, Mock

import pytest

from jupyter_interpreter_mcp.notebook import Notebook
from jupyter_interpreter_mcp.remote import RemoteJupyterClient


@pytest.fixture
def mock_remote_client():
    """Create a mock RemoteJupyterClient for testing."""
    client = Mock(spec=RemoteJupyterClient)
    client.create_kernel.return_value = "kernel-123"
    client.execute = AsyncMock(return_value={"error": [], "result": []})
    return client


class TestNotebookInit:
    """Test Notebook initialization."""

    @pytest.mark.asyncio
    async def test_init_success(self, mock_remote_client):
        """Test successful notebook initialization."""
        notebook = Notebook(
            session_id="test-session-123",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-123",
        )
        await notebook.connect()

        # Verify kernel was created
        mock_remote_client.create_kernel.assert_called_once()
        assert notebook.kernel_id == "kernel-123"

        # Verify attributes
        assert notebook.session_id == "test-session-123"
        assert (
            notebook.file_path == "/home/jovyan/sessions/test-session-123/history.txt"
        )
        assert notebook.history == []


class TestExecuteNewCode:
    """Test code execution."""

    @pytest.mark.asyncio
    async def test_execute_new_code_success(self, mock_remote_client):
        """Test successful code execution."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # Mock execute to return stream output
        mock_remote_client.execute.return_value = {
            "error": [],
            "result": ["Hello, World!\n"],
        }

        result = await notebook.execute_new_code("print('Hello, World!')")

        assert result["error"] == []
        assert result["result"] == ["Hello, World!\n"]
        assert len(notebook.history) == 1
        assert "\nprint('Hello, World!')" in notebook.history[0]

        # Verify execute was called with correct parameters
        mock_remote_client.execute.assert_called_once_with(
            "kernel-123", "print('Hello, World!')"
        )

    @pytest.mark.asyncio
    async def test_execute_new_code_with_result(self, mock_remote_client):
        """Test code execution with execute_result."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # Mock execute with execute_result
        mock_remote_client.execute.return_value = {
            "error": [],
            "result": ["Execution Result: 42"],
        }

        result = await notebook.execute_new_code("21 + 21")

        assert result["error"] == []
        assert "Execution Result: 42" in result["result"]
        assert len(notebook.history) == 1

    @pytest.mark.asyncio
    async def test_execute_new_code_with_error(self, mock_remote_client):
        """Test code execution with error."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # Mock execute with error
        mock_remote_client.execute.return_value = {
            "error": ["Error: NameError: name 'x' is not defined"],
            "result": [],
        }

        result = await notebook.execute_new_code("print(x)")

        assert "Error: NameError: name 'x' is not defined" in result["error"]
        assert result["result"] == []
        # History should not be updated on error
        assert len(notebook.history) == 0


class TestDumpToFile:
    """Test dumping history to file."""

    @pytest.mark.asyncio
    async def test_dump_to_file(self, mock_remote_client):
        """Test dumping history to remote file."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        notebook.history = ["\nprint('test1')", "\nprint('test2')"]

        await notebook.dump_to_file()

        # Verify put_contents was called with the serialised history
        mock_remote_client.put_contents.assert_called_once()
        call_args = mock_remote_client.put_contents.call_args
        content = call_args[0][1]

        # Verify the content contains the history lines
        assert "\nprint('test1')" in content
        assert "\nprint('test2')" in content

    @pytest.mark.asyncio
    async def test_dump_to_file_empty_history(self, mock_remote_client):
        """Test dumping empty history to file."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # History is empty by default
        await notebook.dump_to_file()

        # Should still call put_contents (even for empty history)
        mock_remote_client.put_contents.assert_called_once()


class TestLoadFromFile:
    """Test loading history from file."""

    @pytest.mark.asyncio
    async def test_load_from_file_success(self, mock_remote_client):
        """Test successfully loading history from file."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # Mock get_file_contents to return file content, and execute for re-execution
        mock_remote_client.get_file_contents.return_value = {"content": "x = 10\n"}
        mock_remote_client.execute.return_value = {"error": [], "result": []}

        result = await notebook.load_from_file()

        assert result is True
        # Should call execute once to re-execute the restored content
        assert mock_remote_client.execute.call_count == 1
        # Restored history should contain only restored user code
        assert notebook.history == ["x = 10"]

    @pytest.mark.asyncio
    async def test_load_from_file_not_found(self, mock_remote_client):
        """Test loading from non-existent file."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # Mock get_file_contents to raise JupyterConnectionError (file not found)
        from jupyter_interpreter_mcp.remote import JupyterConnectionError

        mock_remote_client.get_file_contents.side_effect = JupyterConnectionError(
            "Not found"
        )

        result = await notebook.load_from_file()

        assert result is True
        assert notebook.history == []

    @pytest.mark.asyncio
    async def test_load_from_file_with_error(self, mock_remote_client):
        """Test loading from file with execution error."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # Mock get_file_contents to raise a generic exception (read error)
        mock_remote_client.get_file_contents.side_effect = Exception(
            "Error: OSError: Cannot read file"
        )

        result = await notebook.load_from_file()

        assert result is False

    @pytest.mark.asyncio
    async def test_load_from_file_exception(self, mock_remote_client):
        """Test loading from file with exception."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        # Mock get_file_contents to raise exception
        mock_remote_client.get_file_contents.side_effect = Exception("Unexpected error")

        result = await notebook.load_from_file()

        assert result is False


class TestClose:
    """Test notebook cleanup."""

    @pytest.mark.asyncio
    async def test_close(self, mock_remote_client):
        """Test closing notebook shuts down kernel."""
        notebook = Notebook(
            session_id="test-session-1",
            remote_client=mock_remote_client,
            session_directory="/home/jovyan/sessions/test-session-1",
        )
        await notebook.connect()

        notebook.close()

        # Verify kernel was shut down
        mock_remote_client.shutdown_kernel.assert_called_once_with("kernel-123")
