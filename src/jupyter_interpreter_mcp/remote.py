"""Remote Jupyter server client for kernel management and execution."""

import asyncio
import json
import posixpath
import uuid
from typing import Any, cast
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
        jupyter_root: str = "/home/jovyan",
    ) -> None:
        """Initialize the remote Jupyter client.

        :param base_url: URL of the Jupyter server (e.g., 'http://localhost:8889')
        :type base_url: str
        :param auth_token: Authentication token
        :type auth_token: str
        :param timeout: HTTP request timeout in seconds
        :type timeout: int
        :param jupyter_root: Absolute path to the Jupyter server root on the remote
            filesystem (e.g., ``'/home/jovyan'``).  Used to convert absolute paths
            to Contents API-relative paths.
        :type jupyter_root: str
        """
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout
        self.jupyter_root = jupyter_root

    def _to_api_path(self, absolute_path: str) -> str:
        """Convert an absolute remote filesystem path to a Contents API path.

        The Contents API uses paths relative to ``jupyter_root``.  This helper
        normalises *absolute_path* and expresses it relative to
        ``self.jupyter_root``.

        :param absolute_path: Absolute path on the remote filesystem.
        :type absolute_path: str
        :return: Path suitable for use with the Contents API (no leading slash).
        :rtype: str
        :raises ValueError: If *absolute_path* is outside ``self.jupyter_root``.
        """
        jupyter_root_abs = posixpath.normpath(self.jupyter_root)
        abs_path = posixpath.normpath(absolute_path)
        api_path = posixpath.relpath(abs_path, jupyter_root_abs)
        if api_path.startswith(".."):
            raise ValueError(
                f"Path {absolute_path!r} is outside jupyter_root {self.jupyter_root!r}"
            )
        return api_path

    def _resolve_path(self, path: str) -> str:
        """Resolve *path* to a Contents API-relative path, accepting both absolute
        and relative inputs.

        Absolute paths (starting with ``/``) are converted via
        :meth:`_to_api_path`, which validates that they are within
        ``jupyter_root``.

        Relative paths are normalised with :func:`posixpath.normpath` and
        validated to ensure they do not escape the root via ``..`` traversal
        (e.g. ``../../etc/passwd`` is rejected).

        :param path: Either an absolute filesystem path or a path already
            relative to the Jupyter root.
        :type path: str
        :return: Path suitable for use with the Contents API (no leading slash,
            no ``..`` components that escape the root).
        :rtype: str
        :raises ValueError: If *path* is absolute and outside ``jupyter_root``,
            or if *path* is relative and contains escaping ``..`` components.
        """
        if posixpath.isabs(path):
            return self._to_api_path(path)
        normalised = posixpath.normpath(path)
        if normalised.startswith(".."):
            raise ValueError(
                f"Relative path {path!r} escapes the Jupyter root via '..' components"
            )
        return normalised

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

        Supports both Python code and bash commands.

        :param kernel_id: ID of the kernel to execute code in
        :type kernel_id: str
        :param code: Code to execute (Python or bash)
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

        Supports both Python code and bash commands.

        :param kernel_id: ID of the kernel to execute code in
        :type kernel_id: str
        :param code: Code to execute (Python or bash)
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

    async def create_session_directory(
        self, session_dir: str, created_at: float, last_access: float
    ) -> None:
        """Create a session directory with metadata file via the Contents API.

        :param session_dir: Absolute path to the session directory on the remote
            filesystem.
        :type session_dir: str
        :param created_at: Session creation timestamp.
        :type created_at: float
        :param last_access: Session last access timestamp.
        :type last_access: float
        :raises JupyterConnectionError: If the Contents API call fails.
        :raises ValueError: If *session_dir* is outside ``self.jupyter_root``.
        """
        self.create_directory(session_dir)
        metadata = json.dumps(
            {"created_at": created_at, "last_access": last_access}, indent=2
        )
        self.put_contents(f"{session_dir}/session_meta.json", metadata, format="text")

    async def update_session_metadata(
        self, session_dir: str, last_access: float
    ) -> None:
        """Update session metadata file with new last_access timestamp.

        Reads ``session_meta.json`` from the session directory via the Contents
        API, updates ``last_access``, and writes it back.  If the metadata file
        does not yet exist a new one is created with only ``last_access`` set.

        :param session_dir: Absolute path to the session directory on the remote
            filesystem.
        :type session_dir: str
        :param last_access: New last access timestamp.
        :type last_access: float
        :raises JupyterConnectionError: If the Contents API call fails.
        :raises ValueError: If *session_dir* is outside ``self.jupyter_root``.
        """
        meta_path = f"{session_dir}/session_meta.json"
        try:
            contents = self.get_file_contents(meta_path)
            metadata = json.loads(contents["content"])
        except JupyterConnectionError:
            metadata = {}
        metadata["last_access"] = last_access
        self.put_contents(meta_path, json.dumps(metadata, indent=2), format="text")

    def get_contents(self, path: str) -> dict[str, Any]:
        """Get directory or file information from Jupyter Contents API.

        :param path: Path to directory or file — either an absolute filesystem
            path or a path relative to the Jupyter root
            (e.g., ``'.'`` for the root directory).
        :type path: str
        :return: Contents API response as dictionary with metadata
        :rtype: dict[str, Any]
        :raises JupyterConnectionError: If path not found (404) or connection fails
        :raises JupyterAuthError: If permission denied (403)
        :raises ValueError: If *path* is outside ``jupyter_root`` or escapes via
            ``..`` components.
        """
        path = self._resolve_path(path)
        try:
            response = self._make_request("GET", f"/api/contents/{path}")
            return cast(dict[str, Any], response.json())
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                raise JupyterConnectionError(f"Path not found: {path}") from e
            # 403 is already handled by _make_request as JupyterAuthError
            raise

    def get_file_contents(self, path: str) -> dict[str, Any]:
        """Fetch file content from Jupyter Contents API.

        Retrieves file content (text or base64-encoded binary) via
        ``GET /api/contents/{path}?content=1&type=file``.

        :param path: Path to the file — either an absolute filesystem path or a
            path relative to the Jupyter root
            (e.g., ``'sessions/abc123/data.csv'``).
        :type path: str
        :return: Contents API response dict with at minimum ``format``
            (``"text"`` or ``"base64"``), ``content``, and ``name`` keys.
        :rtype: dict[str, Any]
        :raises JupyterConnectionError: If the file is not found (404) or
            the connection fails.
        :raises JupyterAuthError: If permission is denied (401/403).
        :raises ValueError: If *path* is outside ``jupyter_root`` or escapes via
            ``..`` components.
        """
        path = self._resolve_path(path)
        try:
            response = self._make_request(
                "GET", f"/api/contents/{path}", params={"content": "1", "type": "file"}
            )
            return cast(dict[str, Any], response.json())
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                raise JupyterConnectionError(f"File not found: {path}") from e
            raise

    def put_contents(
        self, path: str, content: str, format: str = "text"
    ) -> dict[str, Any]:
        """Create or overwrite a file via Jupyter Contents API.

        Sends ``PUT /api/contents/{path}`` with a JSON body containing
        ``{"type": "file", "format": format, "content": content}``.

        :param path: Destination path — either an absolute filesystem path or a
            path relative to the Jupyter root
            (e.g., ``'sessions/abc123/output.txt'``).
        :type path: str
        :param content: File content.  Plain text for ``format="text"``;
            base64-encoded bytes for ``format="base64"``.
        :type content: str
        :param format: Either ``"text"`` (default) or ``"base64"``.
        :type format: str
        :return: Contents API response dict for the created/updated file.
        :rtype: dict[str, Any]
        :raises JupyterConnectionError: If the connection fails.
        :raises JupyterAuthError: If permission is denied (401/403).
        :raises ValueError: If *path* is outside ``jupyter_root`` or escapes via
            ``..`` components.
        """
        path = self._resolve_path(path)
        payload = {"type": "file", "format": format, "content": content}
        response = self._make_request("PUT", f"/api/contents/{path}", json=payload)
        return cast(dict[str, Any], response.json())

    def create_directory(self, path: str) -> None:
        """Create a directory (and any missing parents) via Contents API.

        Sends ``PUT /api/contents/{path}`` with ``{"type": "directory"}`` for
        each path component that does not yet exist.  Ignores 409 Conflict
        responses (directory already exists).

        :param path: Directory path — either an absolute filesystem path or a
            path relative to the Jupyter root.
        :type path: str
        :raises JupyterConnectionError: If the connection fails.
        :raises JupyterAuthError: If permission is denied (401/403).
        :raises ValueError: If *path* is outside ``jupyter_root`` or escapes via
            ``..`` components.
        """
        path = self._resolve_path(path)
        # Build list of ancestor paths to ensure all intermediate dirs exist
        parts = path.replace("\\", "/").split("/")
        dirs_to_create = []
        for i in range(1, len(parts) + 1):
            dirs_to_create.append("/".join(parts[:i]))

        for dir_path in dirs_to_create:
            try:
                self._make_request(
                    "PUT",
                    f"/api/contents/{dir_path}",
                    json={"type": "directory"},
                )
            except requests.HTTPError as e:
                # 409 Conflict means the directory already exists — ignore
                if e.response.status_code == 409:
                    continue
                raise

    def check_exists(self, path: str) -> bool:
        """Check whether a path exists on the remote Jupyter server.

        Uses ``GET /api/contents/{path}?content=0`` to test for existence
        without fetching the file content.

        :param path: Path to check — either an absolute filesystem path or a
            path relative to the Jupyter root.
        :type path: str
        :return: ``True`` if the path exists, ``False`` if it does not (404).
        :rtype: bool
        :raises JupyterConnectionError: If the connection fails for reasons
            other than a 404.
        :raises JupyterAuthError: If permission is denied (401/403).
        :raises ValueError: If *path* is outside ``jupyter_root`` or escapes via
            ``..`` components.
        """
        path = self._resolve_path(path)
        try:
            self._make_request("GET", f"/api/contents/{path}", params={"content": "0"})
            return True
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return False
            raise
