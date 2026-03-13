"""Test session restoration to ensure code is not duplicated on reload."""

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


@pytest.mark.asyncio
async def test_session_restoration_does_not_duplicate_history(mock_remote_client):
    """Test that restoring a session does not duplicate code in history.

    This is a regression test for the bug where session restoration would
    re-execute code and add it to history again, causing code duplication
    on each server restart.
    """
    # Create a notebook
    notebook = Notebook(
        session_id="test-session",
        remote_client=mock_remote_client,
        session_directory="/home/jovyan/sessions/test-session",
    )
    await notebook.connect()

    # Execute some code
    mock_remote_client.execute.return_value = {
        "error": [],
        "result": ["10\n"],
    }
    await notebook.execute_new_code("x = 10")

    # Save history
    await notebook.dump_to_file()

    # Verify history has one entry
    assert len(notebook.history) == 1
    assert "\nx = 10" in notebook.history[0]

    # Simulate server restart by creating a new notebook
    notebook2 = Notebook(
        session_id="test-session-restored",
        remote_client=mock_remote_client,
        session_directory="/home/jovyan/sessions/test-session-restored",
    )
    await notebook2.connect()

    # Mock the file read to return the saved history
    mock_remote_client.get_file_contents.return_value = {"content": "\nx = 10\n"}
    mock_remote_client.execute.side_effect = None
    mock_remote_client.execute.return_value = {"error": [], "result": ["10\n"]}

    # Load from file (simulating session restoration)
    result = await notebook2.load_from_file()

    # Verify restoration succeeded
    assert result is True

    # CRITICAL: History should contain exactly the restored file content
    # (one entry). load_from_file executes code directly via
    # remote_client.execute, not execute_new_code, so it must not *duplicate*
    # the restored content in history. The bug was that it used
    # execute_new_code, which added an extra history entry on restoration.
    assert len(notebook2.history) == 1  # Only the restored file content

    # Now execute new code after restoration
    mock_remote_client.execute.side_effect = None
    mock_remote_client.execute.return_value = {
        "error": [],
        "result": ["20\n"],
    }
    await notebook2.execute_new_code("y = 20")

    # History should now have 2 entries: the file read code + new code
    assert len(notebook2.history) == 2


@pytest.mark.asyncio
async def test_multiple_restorations_do_not_multiply_history(mock_remote_client):
    """Test that multiple restoration cycles don't exponentially grow history.

    This tests the scenario where:
    1. Execute code -> save
    2. Restore -> execute new code -> save
    3. Restore again -> history should not have duplicates
    """
    # Create and use first notebook
    notebook1 = Notebook(
        session_id="test-1",
        remote_client=mock_remote_client,
        session_directory="/home/jovyan/sessions/test-1",
    )
    await notebook1.connect()

    mock_remote_client.execute.return_value = {"error": [], "result": []}
    await notebook1.execute_new_code("a = 1")

    # Save: history = ["\na = 1"]
    await notebook1.dump_to_file()
    assert len(notebook1.history) == 1

    # Simulate restoration
    notebook2 = Notebook(
        session_id="test-2",
        remote_client=mock_remote_client,
        session_directory="/home/jovyan/sessions/test-2",
    )
    await notebook2.connect()

    # Mock restoration
    mock_remote_client.get_file_contents.return_value = {"content": "\na = 1\n"}
    mock_remote_client.execute.side_effect = None
    mock_remote_client.execute.return_value = {"error": [], "result": []}
    await notebook2.load_from_file()

    # Execute new code
    mock_remote_client.execute.return_value = {"error": [], "result": []}
    await notebook2.execute_new_code("b = 2")

    # Save: history should be [read code, "\nb = 2"]
    await notebook2.dump_to_file()
    assert len(notebook2.history) == 2

    # Third notebook: restore again
    notebook3 = Notebook(
        session_id="test-3",
        remote_client=mock_remote_client,
        session_directory="/home/jovyan/sessions/test-3",
    )
    await notebook3.connect()

    # The bug would cause the file to contain duplicated "a = 1"
    # Our fix ensures it's only executed, not added to history
    mock_remote_client.get_file_contents.return_value = {"content": "\nb = 2\n"}
    mock_remote_client.execute.return_value = {"error": [], "result": []}
    await notebook3.load_from_file()

    # After restoration, history should only have the read code
    # NOT the restored code duplicated
    assert len(notebook3.history) == 1
