"""Integration tests for list_dir tool."""

from unittest.mock import Mock, patch

import pytest


class TestListDirIntegration:
    """Integration tests for list_dir tool."""

    @pytest.mark.asyncio
    async def test_list_dir_with_contents_api(self):
        """Test list_dir using Contents API."""
        from jupyter_interpreter_mcp import server

        # Mock the Contents API response
        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            return_value={
                "name": "",
                "path": ".",
                "type": "directory",
                "content": [
                    {
                        "name": "data.csv",
                        "path": "data.csv",
                        "type": "file",
                        "size": 1024,
                        "last_modified": "2024-01-29T12:00:00Z",
                    },
                    {
                        "name": "script.py",
                        "path": "script.py",
                        "type": "file",
                        "size": 512,
                        "last_modified": "2024-01-29T11:30:00Z",
                    },
                    {
                        "name": "notebooks",
                        "path": "notebooks",
                        "type": "directory",
                        "size": None,
                        "last_modified": "2024-01-29T11:00:00Z",
                    },
                ],
            }
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            # Verify result structure
            assert "error" in result
            assert "result" in result
            assert result["error"] == ""
            assert len(result["result"]) == 3

            # Verify content formatting
            assert "file data.csv (1.0 KB)" in result["result"][0]
            assert "file script.py (512 B)" in result["result"][1]
            assert "directory notebooks (directory)" in result["result"][2]

            # Verify Contents API was called
            mock_remote_client.get_contents.assert_called_once_with(".")

    @pytest.mark.asyncio
    async def test_list_dir_empty_directory_api(self):
        """Test list_dir with empty directory via Contents API."""
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

            # Verify result
            assert result["error"] == ""
            assert len(result["result"]) == 1
            assert result["result"][0] == "(empty directory)"

            # Verify Contents API was called
            mock_remote_client.get_contents.assert_called_once_with(".")

    @pytest.mark.asyncio
    async def test_list_dir_handles_api_connection_error(self):
        """Test list_dir handles Contents API connection errors gracefully."""
        from jupyter_interpreter_mcp import server
        from jupyter_interpreter_mcp.remote import JupyterConnectionError

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            side_effect=JupyterConnectionError("Cannot connect to server")
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            # Verify error is captured
            assert "error" in result
            assert "Cannot connect to server" in result["error"]
            assert result["result"] == []

    @pytest.mark.asyncio
    async def test_list_dir_handles_path_not_found(self):
        """Test list_dir handles 404 path not found errors."""
        from jupyter_interpreter_mcp import server
        from jupyter_interpreter_mcp.remote import JupyterConnectionError

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            side_effect=JupyterConnectionError("Path not found: .")
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            # Verify error is returned
            assert "error" in result
            assert "Path not found" in result["error"]
            assert result["result"] == []

    @pytest.mark.asyncio
    async def test_list_dir_handles_permission_denied(self):
        """Test list_dir handles 403 permission denied errors."""
        from jupyter_interpreter_mcp import server
        from jupyter_interpreter_mcp.remote import JupyterAuthError

        mock_remote_client = Mock()
        mock_remote_client.get_contents = Mock(
            side_effect=JupyterAuthError("Authorization failed: 403")
        )

        with patch.object(server, "remote_client", mock_remote_client, create=True):
            result = await server.list_dir()

            # Verify error is returned
            assert "error" in result
            assert "Authorization failed" in result["error"]
            assert result["result"] == []
