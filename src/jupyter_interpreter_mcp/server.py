import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv  # type: ignore [import-not-found]
from mcp.server.fastmcp import FastMCP  # type: ignore [import-not-found]

from jupyter_interpreter_mcp.notebook import Notebook
from jupyter_interpreter_mcp.remote import (
    JupyterAuthError,
    JupyterConnectionError,
    RemoteJupyterClient,
)

parent_folder = Path(__file__).resolve().parent
env_path = parent_folder / ".env"

load_dotenv(dotenv_path=env_path)

# Load configuration from environment
base_url = os.getenv("JUPYTER_BASE_URL", "http://localhost:8888")
token = os.getenv("JUPYTER_TOKEN")
notebooks_folder = os.getenv("NOTEBOOKS_FOLDER", "/home/jovyan/notebooks")

# Initialize remote client
try:
    if not token:
        raise ValueError("JUPYTER_TOKEN environment variable is required")
    remote_client = RemoteJupyterClient(base_url=base_url, auth_token=token)
    # Validate connection on startup
    remote_client.validate_connection()
except (JupyterConnectionError, JupyterAuthError) as e:
    print(f"Failed to connect to Jupyter server at {base_url}: {e}", file=sys.stderr)
    print(
        "Please check your configuration and ensure Jupyter server is running.",
        file=sys.stderr,
    )
    sys.exit(1)
except ValueError as e:
    print(f"Invalid configuration: {e}", file=sys.stderr)
    print(
        "Please provide JUPYTER_TOKEN.",
        file=sys.stderr,
    )
    sys.exit(1)

mcp = FastMCP(
    name="Code Interpreter",
    instructions="""
    You can execute Python code by sending a request with the code you want to run.
    Think of this tool as a jupyter notebook. It will remember your previously
    executed code, if you pass in your session_id.
    It is crucial to remember your session_id for a smooth interaction.
    """,
)
sessions: dict[int, Notebook] = {}


@mcp.tool(
    "execute_code",
    description=(
        "Executes Python code within a persistent session, retaining past results "
        "(e.g., variables, imports). Similar to a Jupyter notebook. A session_id is "
        "returned on first use and must be included in subsequent requests to "
        "maintain context."
    ),
)
async def execute_code(code: str, session_id: int = 0) -> dict[str, list[str]]:
    global sessions
    """Executes the provided Python code and returns the result.

    Args:
        code (str): The Python code to execute.
        session_id (int, optional): A unique identifier used to associate
            multiple code execution requests with the same logical session.
            If this is the first request, you may omit it or set it to 0.
            The system will generate and return a new session_id, which
            should be reused in follow-up requests to maintain continuity
            within the same session.

    Returns:
        dict[str, list[str]]: A dictionary with 'error' and 'result' keys,
            each containing a list of strings.
    """
    session_info: str | None = None

    # Create new session if session_id is 0 or session doesn't exist in memory
    if session_id == 0 or session_id not in sessions:
        # Generate new session_id if needed
        if session_id == 0:
            session_id = int(time.time())

        # Create new notebook session
        sessions[session_id] = Notebook(session_id, remote_client, notebooks_folder)

        # Try to load from file if it exists (for session restoration)
        if session_id != int(time.time()):
            sessions[session_id].load_from_file()

        session_info = (
            f"Your session_id for this chat is {session_id}. "
            f"You should provide it for subsequent requests."
        )

    try:
        notebook = sessions[session_id]
        result: dict[str, list[str]] = notebook.execute_new_code(code)
        if session_info:
            result["result"].append(session_info)
        if len(result["error"]) == 0:
            notebook.dump_to_file()
        return result
    except Exception as e:
        return {"error": [str(e)], "result": []}


def main() -> None:
    """Entry point for the MCP server."""
    import sys

    # Handle --version flag
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        from importlib.metadata import version

        print(f"jupyter-interpreter-mcp {version('jupyter-interpreter-mcp')}")
        sys.exit(0)

    mcp.run()


if __name__ == "__main__":
    main()
