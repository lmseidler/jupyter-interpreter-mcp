"""Unit tests for RemoteJupyterClient."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
import requests

from jupyter_interpreter_mcp.remote import (
    JupyterAuthError,
    JupyterConnectionError,
    JupyterExecutionError,
    RemoteJupyterClient,
)


class TestRemoteJupyterClientInit:
    """Test RemoteJupyterClient initialization."""

    def test_init_with_token(self):
        """Test initialization with token authentication."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )
        assert client.base_url == "http://localhost:8888"
        assert client.auth_token == "test-token"

    def test_init_strips_trailing_slash(self):
        """Test that base URL trailing slash is removed."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888/", auth_token="test-token"
        )
        assert client.base_url == "http://localhost:8888"


class TestAuthHeaders:
    """Test authentication header generation."""

    def test_get_auth_headers_with_token(self):
        """Test auth headers with token."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )
        headers = client._get_auth_headers()
        assert headers["Authorization"] == "token test-token"
        assert headers["Content-Type"] == "application/json"


class TestMakeRequest:
    """Test HTTP request wrapper."""

    def test_make_request_success(self):
        """Test successful request."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )
        mock_response = Mock()
        mock_response.status_code = 200

        with patch("requests.request", return_value=mock_response):
            result = client._make_request("GET", "/api/kernels")
            assert result == mock_response
            assert result.status_code == 200

    def test_make_request_connection_error(self):
        """Test connection error."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )

        with patch("requests.request", side_effect=requests.ConnectionError("Failed")):
            with pytest.raises(JupyterConnectionError, match="Cannot connect"):
                client._make_request("GET", "/api/kernels")

    def test_make_request_timeout(self):
        """Test timeout error."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )

        with patch("requests.request", side_effect=requests.Timeout("Timeout")):
            with pytest.raises(JupyterConnectionError, match="timed out"):
                client._make_request("GET", "/api/kernels")

    def test_make_request_auth_error_401(self):
        """Test authentication error (401)."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="bad-token"
        )
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("requests.request", return_value=mock_response):
            with pytest.raises(JupyterAuthError, match="Authentication failed"):
                client._make_request("GET", "/api/kernels")

    def test_make_request_auth_error_403(self):
        """Test authorization error (403)."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="bad-token"
        )
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("requests.request", return_value=mock_response):
            with pytest.raises(JupyterAuthError, match="Authorization failed"):
                client._make_request("GET", "/api/kernels")


class TestValidateConnection:
    """Test connection validation."""

    def test_validate_connection_success(self):
        """Test successful connection validation."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )
        mock_response = Mock()
        mock_response.status_code = 200

        with patch.object(client, "_make_request", return_value=mock_response):
            result = client.validate_connection()
            assert result is True

    def test_validate_connection_failure(self):
        """Test failed connection validation."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="bad-token"
        )

        with patch.object(
            client,
            "_make_request",
            side_effect=JupyterConnectionError("Cannot connect"),
        ):
            with pytest.raises(JupyterConnectionError, match="Cannot connect"):
                client.validate_connection()


class TestCreateKernel:
    """Test kernel creation."""

    def test_create_kernel_success(self):
        """Test successful kernel creation."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "kernel-123", "name": "python3"}

        with patch.object(client, "_make_request", return_value=mock_response):
            kernel_id = client.create_kernel("python3")
            assert kernel_id == "kernel-123"

    def test_create_kernel_default_name(self):
        """Test kernel creation with default kernel name."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "kernel-456", "name": "python3"}

        with patch.object(client, "_make_request", return_value=mock_response):
            kernel_id = client.create_kernel()
            assert kernel_id == "kernel-456"

    def test_create_kernel_failure(self):
        """Test kernel creation failure."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )

        with patch.object(
            client,
            "_make_request",
            side_effect=JupyterConnectionError("Failed to create kernel"),
        ):
            with pytest.raises(JupyterConnectionError, match="Failed to create kernel"):
                client.create_kernel()


class TestShutdownKernel:
    """Test kernel shutdown."""

    def test_shutdown_kernel_success(self):
        """Test successful kernel shutdown."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )
        mock_response = Mock()
        mock_response.status_code = 204

        with patch.object(client, "_make_request", return_value=mock_response) as mock:
            client.shutdown_kernel("kernel-123")
            # Verify DELETE was called with correct endpoint
            mock.assert_called_once()
            call_args = mock.call_args
            assert call_args[0][0] == "DELETE"
            assert "kernel-123" in call_args[0][1]

    def test_shutdown_kernel_failure(self):
        """Test kernel shutdown failure."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="token"
        )

        with patch.object(
            client,
            "_make_request",
            side_effect=JupyterConnectionError("Failed to shutdown"),
        ):
            with pytest.raises(JupyterConnectionError, match="Failed to shutdown"):
                client.shutdown_kernel("kernel-123")


class TestExecuteCodeForOutput:
    """Test WebSocket code execution for bootstrap operations."""

    @pytest.mark.asyncio
    @patch("websockets.connect")
    async def test_execute_code_for_output_success(self, mock_connect):
        """Test successful code execution via WebSocket."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )

        # Mock WebSocket connection with AsyncMock
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws

        # Capture the msg_id from the sent message
        sent_messages = []

        async def capture_send(data):
            sent_messages.append(json.loads(data))

        mock_ws.send = AsyncMock(side_effect=capture_send)

        # Mock WebSocket messages with proper parent_header
        async def mock_recv():
            # First call returns stream output
            if len(sent_messages) > 0:
                msg_id = sent_messages[0]["header"]["msg_id"]
                return json.dumps(
                    {
                        "msg_type": "stream",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"name": "stdout", "text": "Hello, World!\n"},
                    }
                )
            return json.dumps(
                {
                    "msg_type": "status",
                    "parent_header": {},
                    "content": {"execution_state": "idle"},
                }
            )

        # Use a side_effect function to set parent_header correctly
        call_count = [0]

        async def mock_recv_side_effect():
            if call_count[0] == 0:
                # Wait for send to be called first
                await asyncio.sleep(0.01)
                msg_id = sent_messages[0]["header"]["msg_id"]
                call_count[0] += 1
                return json.dumps(
                    {
                        "msg_type": "stream",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"name": "stdout", "text": "Hello, World!\n"},
                    }
                )
            else:
                msg_id = sent_messages[0]["header"]["msg_id"]
                return json.dumps(
                    {
                        "msg_type": "status",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"execution_state": "idle"},
                    }
                )

        mock_ws.recv = AsyncMock(side_effect=mock_recv_side_effect)

        result = await client.execute_code_for_output(
            "kernel-123", "print('Hello, World!')"
        )

        assert "Hello, World!" in result

    @pytest.mark.asyncio
    @patch("websockets.connect")
    async def test_execute_code_for_output_error(self, mock_connect):
        """Test code execution error via WebSocket."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )

        # Mock WebSocket connection with AsyncMock
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws

        # Capture sent messages
        sent_messages = []

        async def capture_send(data):
            sent_messages.append(json.loads(data))

        mock_ws.send = AsyncMock(side_effect=capture_send)

        call_count = [0]

        async def mock_recv_side_effect():
            # Wait for send
            await asyncio.sleep(0.01)
            msg_id = sent_messages[0]["header"]["msg_id"]

            if call_count[0] == 0:
                call_count[0] += 1
                return json.dumps(
                    {
                        "msg_type": "error",
                        "parent_header": {"msg_id": msg_id},
                        "content": {
                            "ename": "NameError",
                            "evalue": "name 'x' is not defined",
                            "traceback": [
                                "Traceback...",
                                "NameError: name 'x' is not defined",
                            ],
                        },
                    }
                )
            else:
                return json.dumps(
                    {
                        "msg_type": "status",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"execution_state": "idle"},
                    }
                )

        mock_ws.recv = AsyncMock(side_effect=mock_recv_side_effect)

        with pytest.raises(JupyterExecutionError, match="name 'x' is not defined"):
            await client.execute_code_for_output("kernel-123", "print(x)")


class TestExecute:
    """Test WebSocket code execution."""

    @pytest.mark.asyncio
    @patch("websockets.connect")
    async def test_execute_success(self, mock_connect):
        """Test successful code execution via WebSocket."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )

        # Mock WebSocket connection with AsyncMock
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws

        # Capture the msg_id from the sent message
        sent_messages = []

        async def capture_send(data):
            sent_messages.append(json.loads(data))

        mock_ws.send = AsyncMock(side_effect=capture_send)

        # Mock WebSocket messages with proper parent_header
        call_count = [0]

        async def mock_recv_side_effect():
            if call_count[0] == 0:
                # Wait for send to be called first
                await asyncio.sleep(0.01)
                msg_id = sent_messages[0]["header"]["msg_id"]
                call_count[0] += 1
                return json.dumps(
                    {
                        "msg_type": "stream",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"name": "stdout", "text": "Hello, World!\n"},
                    }
                )
            else:
                msg_id = sent_messages[0]["header"]["msg_id"]
                return json.dumps(
                    {
                        "msg_type": "status",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"execution_state": "idle"},
                    }
                )

        mock_ws.recv = AsyncMock(side_effect=mock_recv_side_effect)

        result = await client.execute("kernel-123", "print('Hello, World!')")

        assert result["error"] == []
        assert "Hello, World!" in result["result"][0]

    @pytest.mark.asyncio
    @patch("websockets.connect")
    async def test_execute_with_result(self, mock_connect):
        """Test code execution with execute_result."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )

        # Mock WebSocket connection
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws

        sent_messages = []

        async def capture_send(data):
            sent_messages.append(json.loads(data))

        mock_ws.send = AsyncMock(side_effect=capture_send)

        call_count = [0]

        async def mock_recv_side_effect():
            await asyncio.sleep(0.01)
            msg_id = sent_messages[0]["header"]["msg_id"]

            if call_count[0] == 0:
                call_count[0] += 1
                return json.dumps(
                    {
                        "msg_type": "execute_result",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"data": {"text/plain": "42"}},
                    }
                )
            else:
                return json.dumps(
                    {
                        "msg_type": "status",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"execution_state": "idle"},
                    }
                )

        mock_ws.recv = AsyncMock(side_effect=mock_recv_side_effect)

        result = await client.execute("kernel-123", "21 + 21")

        assert result["error"] == []
        assert "Execution Result: 42" in result["result"][0]

    @pytest.mark.asyncio
    @patch("websockets.connect")
    async def test_execute_error(self, mock_connect):
        """Test code execution error via WebSocket."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )

        # Mock WebSocket connection
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws

        sent_messages = []

        async def capture_send(data):
            sent_messages.append(json.loads(data))

        mock_ws.send = AsyncMock(side_effect=capture_send)

        call_count = [0]

        async def mock_recv_side_effect():
            await asyncio.sleep(0.01)
            msg_id = sent_messages[0]["header"]["msg_id"]

            if call_count[0] == 0:
                call_count[0] += 1
                return json.dumps(
                    {
                        "msg_type": "error",
                        "parent_header": {"msg_id": msg_id},
                        "content": {
                            "ename": "NameError",
                            "evalue": "name 'x' is not defined",
                            "traceback": [
                                "Traceback...",
                                "NameError: name 'x' is not defined",
                            ],
                        },
                    }
                )
            else:
                return json.dumps(
                    {
                        "msg_type": "status",
                        "parent_header": {"msg_id": msg_id},
                        "content": {"execution_state": "idle"},
                    }
                )

        mock_ws.recv = AsyncMock(side_effect=mock_recv_side_effect)

        result = await client.execute("kernel-123", "print(x)")

        assert "Error: NameError: name 'x' is not defined" in result["error"][0]
        assert result["result"] == []

    @pytest.mark.asyncio
    @patch("websockets.connect")
    async def test_execute_timeout(self, mock_connect):
        """Test code execution timeout."""
        client = RemoteJupyterClient(
            base_url="http://localhost:8888", auth_token="test-token"
        )

        # Mock WebSocket connection
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws

        sent_messages = []

        async def capture_send(data):
            sent_messages.append(json.loads(data))

        mock_ws.send = AsyncMock(side_effect=capture_send)

        # Mock recv to simulate a timeout by sleeping longer than the timeout
        async def mock_recv_timeout():
            # Sleep longer than the timeout to trigger asyncio.TimeoutError
            await asyncio.sleep(10)
            return json.dumps(
                {
                    "msg_type": "status",
                    "parent_header": {},
                    "content": {"execution_state": "busy"},
                }
            )

        mock_ws.recv = AsyncMock(side_effect=mock_recv_timeout)

        with pytest.raises(JupyterExecutionError, match="timed out"):
            await client.execute(
                "kernel-123", "import time; time.sleep(100)", timeout=0.1
            )
