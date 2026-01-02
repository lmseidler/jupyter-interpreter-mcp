import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from jupyter_client.blocking.client import BlockingKernelClient
from jupyter_client.manager import KernelManager

parent_folder = Path(__file__).resolve().parent
env_path = parent_folder / ".env"

load_dotenv(dotenv_path=env_path)
# NOTE: Notebook storage will eventually be handled by a JupyterHub
# container (future work)
notebooks_folder_name = os.getenv("NOTEBOOKS_FOLDER", "notebooks")
notebooks_folder = parent_folder / notebooks_folder_name


class Notebook:
    """Manages a persistent Jupyter kernel session for code execution.

    This class provides a wrapper around Jupyter kernel management,
    allowing for persistent code execution sessions with history tracking
    and session persistence to disk.

    Attributes:
        kernel: The Jupyter kernel manager instance.
        session_id: Unique identifier for this notebook session.
        client: The blocking kernel client for executing code.
        file_path: Path to the session history file.
        history: List of successfully executed code blocks.
    """

    def __init__(self, session_id: int) -> None:
        """Initializes a new Notebook session with a Jupyter kernel.

        Args:
            session_id: A unique identifier for this notebook session.
        """
        self.kernel: KernelManager = KernelManager()
        self.kernel.start_kernel()
        self.session_id: int = session_id
        self.client: BlockingKernelClient = BlockingKernelClient(
            connection_file=self.kernel.connection_file
        )
        self.client.load_connection_file()
        self.client.start_channels()
        self.client.wait_for_ready(timeout=5)

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
        """Saves the execution history to a file.

        Writes all successfully executed code blocks to the session file,
        one per line, for later restoration.
        """
        with open(self.file_path, "w") as f:
            for code in self.history:
                f.write(code + "\n")

    def load_from_file(self) -> bool:
        """Loads and re-executes code from the session history file.

        Attempts to read the session file and execute its contents to
        restore the kernel state.

        Returns:
            bool: True if the file was successfully loaded and executed,
                False if an error occurred.
        """
        try:
            with open(self.file_path) as f:
                code = f.read()
                self.execute_new_code(code)
                return True
        except Exception:
            return False

    # TODO abstract out creating a new client
    def close(self) -> None:
        """Shuts down the Jupyter kernel cleanly."""
        self.kernel.shutdown_kernel()
