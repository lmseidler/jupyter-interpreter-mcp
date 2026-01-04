import os

from jupyter_interpreter_mcp.remote import RemoteJupyterClient


class Notebook:
    """Manages a persistent remote Jupyter kernel session for code execution.

    This class provides a wrapper around remote Jupyter kernel management,
    allowing for persistent code execution sessions with history tracking
    and session persistence to the remote filesystem.

    :ivar remote_client: Client for interacting with remote Jupyter server.
    :ivar session_id: Unique identifier for this notebook session.
    :ivar kernel_id: ID of the remote kernel.
    :ivar file_path: Path to the session history file (on remote filesystem).
    :ivar history: List of successfully executed code blocks.
    """

    def __init__(
        self, session_id: int, remote_client: RemoteJupyterClient, notebooks_folder: str
    ) -> None:
        """Initializes a new Notebook session.

        :param session_id: A unique identifier for this notebook session.
        :type session_id: int
        :param remote_client: Client for interacting with remote Jupyter server.
        :type remote_client: RemoteJupyterClient
        :param notebooks_folder: Path to notebooks folder on remote filesystem.
        :type notebooks_folder: str
        """
        self.remote_client = remote_client
        self.session_id: int = session_id
        self.notebooks_folder = notebooks_folder

        self.kernel_id: str | None = None
        self.file_path: str = os.path.join(notebooks_folder, f"{self.session_id}.txt")
        self.history: list[str] = []

    async def connect(self) -> None:
        """Connects to a remote Jupyter kernel asynchronously.

        Creates a new kernel on the remote server.
        """
        # Create kernel on remote server
        self.kernel_id = self.remote_client.create_kernel()

    async def execute_new_code(self, code: str) -> dict[str, list[str]]:
        """Executes code in the kernel and returns results.

        Supports both Python code and bash commands.

        :param code: The code to execute (Python or bash).
        :type code: str
        :return: A dictionary with 'error' and 'result' keys. 'error' contains
            error messages (empty if successful). 'result' contains output and
            execution results.
        :rtype: dict[str, list[str]]
        :raises RuntimeError: If the notebook is not connected.
        """
        if self.kernel_id is None:
            raise RuntimeError("Notebook is not connected. Call connect() first.")

        # Execute code via WebSocket using the remote client
        result = await self.remote_client.execute(self.kernel_id, code)

        # Update history only if no errors
        if len(result["error"]) == 0:
            self.history.append("\n" + code)

        return result

    async def dump_to_file(self) -> None:
        """Saves the execution history to a file on the remote filesystem.

        Executes Python code in the kernel to write the history to the
        remote container filesystem.

        Raises:
            RuntimeError: If the notebook is not connected.
        """
        if self.kernel_id is None:
            raise RuntimeError("Notebook is not connected. Call connect() first.")

        # Generate code to write history to remote file
        code = f"""
import os
os.makedirs(os.path.dirname({repr(self.file_path)}), exist_ok=True)
with open({repr(self.file_path)}, 'w') as f:
    for line in {repr(self.history)}:
        f.write(line + '\\n')
"""
        # Execute in the kernel (we can ignore the output)
        await self.remote_client.execute(self.kernel_id, code)

    async def load_from_file(self) -> bool:
        """Loads and re-executes code from the session history file.

        Attempts to read the session file from the remote container and execute
        its contents to restore the kernel state.

        :return: True if the file was successfully loaded and executed,
            False if an error occurred.
        :rtype: bool
        :raises RuntimeError: If the notebook is not connected.
        """
        if self.kernel_id is None:
            raise RuntimeError("Notebook is not connected. Call connect() first.")

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
            result = await self.execute_new_code(code)
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
                    restore_result = await self.execute_new_code(file_content)
                    return len(restore_result["error"]) == 0

            return False
        except Exception:
            return False

    # TODO abstract out creating a new client
    def close(self) -> None:
        """Shuts down the remote Jupyter kernel cleanly."""
        if self.kernel_id:
            self.remote_client.shutdown_kernel(self.kernel_id)
