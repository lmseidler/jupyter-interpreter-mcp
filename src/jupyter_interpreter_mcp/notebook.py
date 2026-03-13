import logging
import os

from jupyter_interpreter_mcp.remote import JupyterConnectionError, RemoteJupyterClient

logger = logging.getLogger(__name__)


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
        self,
        session_id: str,
        remote_client: RemoteJupyterClient,
        session_directory: str,
    ) -> None:
        """Initializes a new Notebook session.

        :param session_id: A unique identifier for this notebook session (UUID).
        :type session_id: str
        :param remote_client: Client for interacting with remote Jupyter server.
        :type remote_client: RemoteJupyterClient
        :param session_directory: Path to session directory on remote filesystem.
        :type session_directory: str
        """
        self.remote_client = remote_client
        self.session_id: str = session_id
        self.session_directory = session_directory

        self.kernel_id: str | None = None
        self.file_path: str = os.path.join(session_directory, "history.txt")
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

        Writes the history file directly via the Jupyter Contents API without
        executing code on the kernel.
        """
        api_path = self.remote_client._to_api_path(self.file_path)
        content = "".join(line + "\n" for line in self.history)
        self.remote_client.put_contents(api_path, content, format="text")

    async def load_from_file(self) -> bool:
        """Loads and re-executes code from the session history file.

        Reads the history file via the Jupyter Contents API and re-executes
        its content to restore the kernel state.  The restored code is executed
        but NOT added to history again (it is already in the saved history).

        :return: True if the file was successfully loaded and executed (or if
            no history file exists yet), False if an error occurred.
        :rtype: bool
        :raises RuntimeError: If the notebook is not connected.
        """
        if self.kernel_id is None:
            raise RuntimeError("Notebook is not connected. Call connect() first.")

        api_path = self.remote_client._to_api_path(self.file_path)
        try:
            # First, explicitly check whether the history file exists. Only a confirmed
            # "not found" should be treated as a benign fresh-session condition.
            try:
                if not self.remote_client.check_exists(api_path):
                    # File does not exist — fresh session with no prior history.
                    self.history = []
                    return True
            except JupyterConnectionError:
                # Connectivity issue while checking existence; do not treat as file-not-found.
                return False

            contents = self.remote_client.get_file_contents(api_path)
        except JupyterConnectionError:
            # Connectivity issue while fetching contents; treat as a load failure.
            return False
        except Exception:
            return False

        file_content = contents["content"].strip()

        if file_content:
            self.history = [file_content]
            try:
                restore_result = await self.remote_client.execute(
                    self.kernel_id, file_content
                )
                return len(restore_result["error"]) == 0
            except Exception:
                return False

        self.history = []
        return True

    # TODO abstract out creating a new client
    def close(self) -> None:
        """Shuts down the remote Jupyter kernel cleanly.

        Silently ignores errors when the kernel has already been shut down
        (e.g. 404 responses), so this method is safe to call multiple times
        or during ``finally`` cleanup blocks.
        """
        if self.kernel_id:
            try:
                self.remote_client.shutdown_kernel(self.kernel_id)
            except Exception:
                # Kernel may already be shut down (404) or unreachable.
                # Shutdown is best-effort cleanup, so log and continue.
                logger.debug(
                    "Ignoring error while shutting down kernel %s",
                    self.kernel_id,
                )
