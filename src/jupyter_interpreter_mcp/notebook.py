import os
from typing import Any

from jupyter_client.blocking.client import (  # type: ignore[import-not-found]
    BlockingKernelClient,
)

from jupyter_interpreter_mcp.remote import RemoteJupyterClient


class Notebook:
    """Manages a persistent remote Jupyter kernel session for code execution.

    This class provides a wrapper around remote Jupyter kernel management,
    allowing for persistent code execution sessions with history tracking
    and session persistence to the remote filesystem.

    Attributes:
        remote_client: Client for interacting with remote Jupyter server.
        session_id: Unique identifier for this notebook session.
        kernel_id: ID of the remote kernel.
        client: The blocking kernel client for executing code via ZMQ.
        file_path: Path to the session history file (on remote filesystem).
        history: List of successfully executed code blocks.
    """

    def __init__(
        self, session_id: int, remote_client: RemoteJupyterClient, notebooks_folder: str
    ) -> None:
        """Initializes a new Notebook session with a remote Jupyter kernel.

        Args:
            session_id: A unique identifier for this notebook session.
            remote_client: Client for interacting with remote Jupyter server.
            notebooks_folder: Path to notebooks folder on remote filesystem.
        """
        self.remote_client = remote_client
        self.session_id: int = session_id

        # Create kernel on remote server
        self.kernel_id: str = remote_client.create_kernel()

        # Get remote kernel connection info
        conn_info = remote_client.get_kernel_connection_info(self.kernel_id)

        # Connect to remote kernel via ZMQ
        self.client: BlockingKernelClient = BlockingKernelClient()
        self.client.load_connection_info(conn_info)
        self.client.start_channels()
        self.client.wait_for_ready(timeout=10)

        self.file_path: str = os.path.join(notebooks_folder, f"{self.session_id}.txt")

        self.history: list[str] = []

    def execute_new_code(self, code: str) -> dict[str, list[str]]:
        """Executes Python code in the kernel and returns results.

        Args:
            code: The Python code string to execute.

        Returns:
            dict[str, list[str]]: A dictionary with 'error' and 'result' keys.
                'error' contains error messages (empty if successful).
                'result' contains output and execution results.
        """
        result: list[str] = []
        error: list[str] = []

        def output_callback(msg: dict[str, Any]) -> None:
            if msg["msg_type"] == "stream":
                result.append(msg["content"]["text"])
            elif msg["msg_type"] == "execute_result":
                result.append(
                    f"Execution Result: {msg['content']['data']['text/plain']}"
                )
            elif msg["msg_type"] == "error":
                error.append(
                    f"Error: {msg['content']['ename']}: {msg['content']['evalue']}"
                )

        self.client.execute_interactive(
            code=code,
            output_hook=output_callback,
            stop_on_error=True,  # Optional: stop if an error occurs
        )
        if len(error) == 0:
            self.history.append("\n" + code)
        return {"error": error, "result": result}

    def dump_to_file(self) -> None:
        """Saves the execution history to a file on the remote filesystem.

        Executes Python code in the kernel to write the history to the
        remote container filesystem.
        """
        # Generate code to write history to remote file
        code = f"""
import os
os.makedirs(os.path.dirname({repr(self.file_path)}), exist_ok=True)
with open({repr(self.file_path)}, 'w') as f:
    for line in {repr(self.history)}:
        f.write(line + '\\n')
"""
        # Execute silently in the kernel
        self.client.execute(code, silent=True)

    def load_from_file(self) -> bool:
        """Loads and re-executes code from the session history file.

        Attempts to read the session file from the remote container and execute
        its contents to restore the kernel state.

        Returns:
            bool: True if the file was successfully loaded and executed,
                False if an error occurred.
        """
        # Generate code to read history from remote file
        code = f"""
import os
if os.path.exists({repr(self.file_path)}):
    with open({repr(self.file_path)}, 'r') as f:
        content = f.read()
    print('FILE_CONTENT_START')
    print(content, end='')
    print('FILE_CONTENT_END')
else:
    print('FILE_NOT_FOUND')
"""
        try:
            result = self.execute_new_code(code)
            if result["error"]:
                return False

            output = "".join(result["result"])

            if "FILE_NOT_FOUND" in output:
                return False

            # Extract file content between markers
            start_marker = "FILE_CONTENT_START"
            end_marker = "FILE_CONTENT_END"

            if start_marker in output and end_marker in output:
                start_idx = output.index(start_marker) + len(start_marker)
                end_idx = output.index(end_marker)
                file_content = output[start_idx:end_idx].strip()

                # Execute the file content to restore state
                if file_content:
                    restore_result = self.execute_new_code(file_content)
                    return len(restore_result["error"]) == 0

            return False
        except Exception:
            return False

    # TODO abstract out creating a new client
    def close(self) -> None:
        """Shuts down the remote Jupyter kernel cleanly."""
        self.remote_client.shutdown_kernel(self.kernel_id)
