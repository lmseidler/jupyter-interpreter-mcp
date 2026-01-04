import os
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

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
    instructions="""You can execute code by sending a request with the code you want
to run. Think of this tool as a jupyter notebook. It will remember your previously
executed code, if you pass in your session_id. It is crucial to remember your
session_id for a smooth interaction.

Supports both Python code and bash commands (e.g., 'ls', 'pwd', 'cat file.txt').
Bash commands are executed directly without needing shell wrappers like !ls.
You can also use shell commands to install packages
    """,
)
sessions: dict[int, Notebook] = {}


@mcp.tool(
    "execute_code",
    description=(
        "Executes code (Python or bash) within a persistent session, retaining "
        "past results (e.g., variables, imports). Similar to a Jupyter notebook. "
        "A session_id is returned on first use and must be included in subsequent "
        "requests to maintain context. Bash commands (e.g., 'ls', 'pwd') work "
        "directly without wrappers and can be used to install packages."
    ),
)
async def execute_code(code: str, session_id: int = 0) -> dict[str, list[str] | int]:
    global sessions
    """Executes the provided code and returns the result.

    :param code: The code to execute (Python or bash commands).
    :type code: str
    :param session_id: A unique identifier used to associate multiple code execution
        requests with the same logical session. If this is the first request, you may
        omit it or set it to 0. The system will generate and return a new session_id,
        which should be reused in follow-up requests to maintain continuity within the
        same session.
    :type session_id: int, optional
    :return: A dictionary with 'error' and 'result' keys (each containing a list of
        strings), and 'session_id' key (containing the session ID as an integer).
    :rtype: dict
    """
    # Create new session if session_id is 0 or session doesn't exist in memory
    if session_id == 0 or session_id not in sessions:
        # Generate new session_id if needed
        if session_id == 0:
            session_id = int(time.time())

        # Create new notebook session
        notebook = Notebook(session_id, remote_client, notebooks_folder)
        await notebook.connect()
        sessions[session_id] = notebook

        # Try to load from file if it exists (for session restoration)
        # If session_id was provided but not in memory, it might exist on disk
        await notebook.load_from_file()

    try:
        notebook = sessions[session_id]
        result: dict[str, list[str]] = await notebook.execute_new_code(code)

        # Add session_id to the response
        response: dict[str, list[str] | int] = {
            "error": result["error"],
            "result": result["result"],
            "session_id": session_id,
        }

        if len(result["error"]) == 0:
            await notebook.dump_to_file()

        return response
    except Exception:
        return {
            "error": [
                traceback.format_exc()
            ],  # TODO: need to see if this is too verbose
            "result": [],
            "session_id": session_id,
        }


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
