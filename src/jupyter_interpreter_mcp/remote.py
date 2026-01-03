"""Remote Jupyter server client for kernel management and execution."""

import asyncio
import json
import uuid
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import websockets


class JupyterConnectionError(Exception):
    """Raised when cannot connect to Jupyter server."""

    pass


class JupyterAuthError(Exception):
    """Raised when authentication fails."""

    pass


class JupyterExecutionError(Exception):
    """Raised when code execution fails."""

    pass


class RemoteJupyterClient:
    """Client for interacting with remote Jupyter server.

    This class manages all interactions with a remote Jupyter server, including:
    - Kernel creation and management via REST API
    - Code execution via WebSocket
    - Authentication handling
    """

    def __init__(
        self,
        base_url: str,
        auth_token: str,
        timeout: int = 30,
    ) -> None:
        """Initialize the remote Jupyter client.

        :param base_url: URL of the Jupyter server (e.g., 'http://localhost:8889')
        :type base_url: str
        :param auth_token: Authentication token
        :type auth_token: str
        :param timeout: HTTP request timeout in seconds
        :type timeout: int
        """
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout

    def _get_auth_headers(self) -> dict[str, str]:
        """Build authentication headers for requests.

        :return: Dictionary of headers including authorization
        :rtype: dict[str, str]
        """
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"token {self.auth_token}"
        return headers

    def _make_request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> requests.Response:
        """Make an authenticated HTTP request to Jupyter API.

        :param method: HTTP method (GET, POST, DELETE, etc.)
        :type method: str
        :param endpoint: API endpoint (e.g., '/api/kernels')
        :type endpoint: str
        :param kwargs: Additional arguments to pass to requests
        :return: Response object
        :rtype: requests.Response
        :raises JupyterConnectionError: If connection fails
        :raises JupyterAuthError: If authentication fails
        """
        url = urljoin(self.base_url, endpoint)
        headers = self._get_auth_headers()

        # Merge provided headers with auth headers
        if "headers" in kwargs:
            headers.update(kwargs["headers"])
        kwargs["headers"] = headers

        # Set timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        try:
            response = requests.request(method, url, **kwargs)

            # Check for authentication errors
            if response.status_code == 401:
                raise JupyterAuthError(
                    f"Authentication failed: {response.status_code} {response.text}"
                )
            if response.status_code == 403:
                raise JupyterAuthError(
                    f"Authorization failed: {response.status_code} {response.text}"
                )

            # Raise for other HTTP errors
            response.raise_for_status()

            return response
        except requests.ConnectionError as e:
            raise JupyterConnectionError(
                f"Cannot connect to Jupyter server at {self.base_url}: {e}"
            ) from e
        except requests.Timeout as e:
            raise JupyterConnectionError(
                f"Request to {url} timed out after {self.timeout}s: {e}"
            ) from e

    def validate_connection(self) -> bool:
        """Validate that we can connect to the Jupyter server.

        :return: True if connection is valid
        :rtype: bool
        :raises JupyterConnectionError: If connection fails
        :raises JupyterAuthError: If authentication fails
        """
        try:
            response = self._make_request("GET", "/api")
            return bool(response.status_code == 200)
        except (JupyterConnectionError, JupyterAuthError):
            raise

    def create_kernel(self, kernel_name: str = "python3") -> str:
        """Create a new kernel and return its ID.

        :param kernel_name: Name of the kernel to create (default: python3)
        :type kernel_name: str
        :return: Kernel ID (string)
        :rtype: str
        :raises JupyterConnectionError: If connection fails
        :raises JupyterAuthError: If authentication fails
        """
        payload = {"name": kernel_name}
        response = self._make_request("POST", "/api/kernels", json=payload)
        data = response.json()
        kernel_id: str = data["id"]
        return kernel_id

    def shutdown_kernel(self, kernel_id: str) -> None:
        """Shutdown a kernel.

        :param kernel_id: ID of the kernel to shutdown
        :type kernel_id: str
        :raises JupyterConnectionError: If connection fails
        """
        self._make_request("DELETE", f"/api/kernels/{kernel_id}")

    async def execute_code_for_output(self, kernel_id: str, code: str) -> str:
        """Execute code via WebSocket and return output as a string.

        Legacy method that returns only stdout. For structured results
        (including errors and execution results), use execute() instead.

        :param kernel_id: ID of the kernel to execute code in
        :type kernel_id: str
        :param code: Python code to execute
        :type code: str
        :return: stdout from execution
        :rtype: str
        :raises JupyterExecutionError: If execution fails
        """
        # Convert http(s) to ws(s)
        parsed = urlparse(self.base_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/api/kernels/{kernel_id}/channels"

        # Add token to URL if using token auth
        if self.auth_token:
            ws_url += f"?token={self.auth_token}"

        output = []
        error = []

        try:
            async with websockets.connect(ws_url) as websocket:
                # Send execute_request message
                msg_id = str(uuid.uuid4())
                execute_request = {
                    "header": {
                        "msg_id": msg_id,
                        "username": "",
                        "session": str(uuid.uuid4()),
                        "msg_type": "execute_request",
                        "version": "5.3",
                    },
                    "parent_header": {},
                    "metadata": {},
                    "content": {
                        "code": code,
                        "silent": False,
                        "store_history": False,
                        "user_expressions": {},
                        "allow_stdin": False,
                    },
                    "channel": "shell",
                }

                await websocket.send(json.dumps(execute_request))

                # Collect output from messages
                # Only collect messages that are responses to our execute_request
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                        msg = json.loads(message)

                        # Only process messages that are replies to our request
                        parent_msg_id = msg.get("parent_header", {}).get("msg_id", "")
                        if parent_msg_id != msg_id:
                            continue

                        msg_type = msg.get("msg_type", "")

                        if msg_type == "stream":
                            output.append(msg["content"]["text"])
                        elif msg_type == "execute_result":
                            output.append(msg["content"]["data"]["text/plain"])
                        elif msg_type == "error":
                            error.append(
                                f"{msg['content']['ename']}: {msg['content']['evalue']}"
                            )
                        elif (
                            msg_type == "status"
                            and msg["content"]["execution_state"] == "idle"
                        ):
                            # Execution complete
                            break

                    except asyncio.TimeoutError:
                        break

        except Exception as e:
            raise JupyterExecutionError(f"Failed to execute code: {e}") from e

        if error:
            raise JupyterExecutionError(f"Code execution failed: {'; '.join(error)}")

        return "".join(output)

    async def execute(
        self, kernel_id: str, code: str, timeout: float = 30.0
    ) -> dict[str, list[str]]:
        """Execute code via WebSocket and return structured results.

        This method replaces the ZMQ-based execution with WebSocket transport,
        making it work in containerized environments where ZMQ ports are not mapped.

        :param kernel_id: ID of the kernel to execute code in
        :type kernel_id: str
        :param code: Python code to execute
        :type code: str
        :param timeout: Maximum time to wait for execution completion in seconds
        :type timeout: float
        :return: Dictionary with 'error' and 'result' keys. 'error' contains
            list of error messages (empty if successful). 'result' contains
            list of output strings and execution results.
        :rtype: dict[str, list[str]]
        :raises JupyterExecutionError: If execution fails or times out
        """
        # Convert http(s) to ws(s)
        parsed = urlparse(self.base_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/api/kernels/{kernel_id}/channels"

        # Add token to URL if using token auth
        if self.auth_token:
            ws_url += f"?token={self.auth_token}"

        result: list[str] = []
        error: list[str] = []

        try:
            async with websockets.connect(ws_url) as websocket:
                # Send execute_request message
                msg_id = str(uuid.uuid4())
                execute_request = {
                    "header": {
                        "msg_id": msg_id,
                        "username": "",
                        "session": str(uuid.uuid4()),
                        "msg_type": "execute_request",
                        "version": "5.3",
                    },
                    "parent_header": {},
                    "metadata": {},
                    "content": {
                        "code": code,
                        "silent": False,
                        "store_history": True,
                        "user_expressions": {},
                        "allow_stdin": False,
                    },
                    "channel": "shell",
                }

                await websocket.send(json.dumps(execute_request))

                # Collect output from messages
                # Only collect messages that are responses to our execute_request
                while True:
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(), timeout=timeout
                        )
                        msg = json.loads(message)

                        # Only process messages that are replies to our request
                        parent_msg_id = msg.get("parent_header", {}).get("msg_id", "")
                        if parent_msg_id != msg_id:
                            continue

                        msg_type = msg.get("msg_type", "")

                        if msg_type == "stream":
                            result.append(msg["content"]["text"])
                        elif msg_type == "execute_result":
                            plain_text = msg["content"]["data"]["text/plain"]
                            result.append(f"Execution Result: {plain_text}")
                        elif msg_type == "error":
                            ename = msg["content"]["ename"]
                            evalue = msg["content"]["evalue"]
                            error.append(f"Error: {ename}: {evalue}")
                        elif (
                            msg_type == "status"
                            and msg["content"]["execution_state"] == "idle"
                        ):
                            # Execution complete
                            break

                    except asyncio.TimeoutError as e:
                        raise JupyterExecutionError(
                            f"Code execution timed out after {timeout}s"
                        ) from e

        except JupyterExecutionError:
            # Re-raise our own exceptions
            raise
        except Exception as e:
            raise JupyterExecutionError(f"Failed to execute code: {e}") from e

        return {"error": error, "result": result}

    async def get_kernel_connection_info(self, kernel_id: str) -> dict[str, Any]:
        """Retrieve kernel ZMQ connection information asynchronously.

        DEPRECATED: This method is no longer needed as execution now uses
        WebSocket instead of ZMQ. It may be removed in a future version.

        Tries to read connection file from the remote kernel's filesystem.

        :param kernel_id: ID of the kernel
        :type kernel_id: str
        :return: Dictionary with connection info compatible with BlockingKernelClient:
            {
                'shell_port': int,
                'iopub_port': int,
                'stdin_port': int,
                'control_port': int,
                'hb_port': int,
                'ip': str,
                'key': str,
                'transport': str,
                'signature_scheme': str
            }
        :rtype: dict[str, Any]
        :raises JupyterConnectionError: If cannot retrieve connection info
        """
        # Try multiple possible locations for the connection file
        possible_paths = [
            f"~/.local/share/jupyter/runtime/kernel-{kernel_id}.json",
            f"/run/user/1000/jupyter/kernel-{kernel_id}.json",
            f"/tmp/kernel-{kernel_id}.json",
        ]

        code = f"""
import json
import os

paths = {possible_paths}
for path in paths:
    expanded_path = os.path.expanduser(path)
    if os.path.exists(expanded_path):
        with open(expanded_path, 'r') as f:
            conn_info = json.load(f)
        print(json.dumps(conn_info))
        break
else:
    print("ERROR: Connection file not found in any of the expected locations")
"""

        try:
            # Execute code asynchronously
            output = await self.execute_code_for_output(kernel_id, code)

            # Parse the JSON output
            conn_info = json.loads(output.strip())

            # Validate required fields
            required_fields = [
                "shell_port",
                "iopub_port",
                "stdin_port",
                "control_port",
                "hb_port",
                "ip",
                "key",
                "transport",
                "signature_scheme",
            ]

            for field in required_fields:
                if field not in conn_info:
                    raise JupyterConnectionError(
                        f"Connection info missing required field: {field}"
                    )

            # Cast to the proper return type
            return dict(conn_info)

        except json.JSONDecodeError as e:
            raise JupyterConnectionError(f"Failed to parse connection info: {e}") from e
        except JupyterExecutionError as e:
            raise JupyterConnectionError(
                f"Failed to retrieve connection info: {e}"
            ) from e
