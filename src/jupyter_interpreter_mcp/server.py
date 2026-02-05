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

# Global variables initialized in main()
remote_client: RemoteJupyterClient
notebooks_folder: str

mcp = FastMCP(
    name="Code Interpreter",
    instructions="""You can execute code by sending a request with the code you want
to run. Think of this tool as a jupyter notebook. It will remember your previously
executed code, if you pass in your session_id. It is crucial to provide your
session_id for that to work.

Supports both Python code and bash commands (e.g., 'ls', 'pwd', 'cat file.txt').
Bash commands are executed directly without needing shell wrappers like !ls.
You can also use shell commands to install packages.

Additionally, you can use the list_dir tool to explore the working directory and
see what files are available without executing code.
    """,
)
sessions: dict[int, Notebook] = {}


@mcp.tool(
    "execute_code",
    description=(
        "Executes code (Python or bash) within a persistent session, retaining "
        "past results (e.g., variables, imports). Similar to a Jupyter notebook. "
        "In order to reuse variables it is crucial to pass in a session_id. "
        "A session_id is returned on every execution."
        "Bash commands (e.g., 'ls', 'pwd') work directly without wrappers and "
        "can be used to install packages."
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


@mcp.tool(
    "list_dir",
    description="Lists all files and directories in the current working directory.",
)
async def list_dir() -> dict[str, list[str] | str]:
    """Lists files and directories in the current working directory.

    This tool uses the Jupyter Contents API to retrieve directory listings
    and returns formatted output showing files and directories with their metadata
    (type, size, last modified timestamp).

    :return: A dictionary with 'error' key (containing error message or empty string)
        and 'result' key (containing list of formatted directory entry lines).
    :rtype: dict[str, list[str] | str]
    """
    try:
        # Call Jupyter Contents API to get directory listing
        contents_response = remote_client.get_contents(".")

        # Format the response into user-friendly output
        result_lines = []

        # The contents_response for a directory contains a "content" key
        # with list of items
        content = contents_response.get("content", [])

        if not content:
            # Empty directory
            result_lines.append("(empty directory)")
        else:
            for item in content:
                item_type = item.get("type", "unknown")
                name = item.get("name", "")
                size = item.get("size")
                last_modified = item.get("last_modified", "")

                # Format size based on type
                if item_type == "directory":
                    size_str = "directory"
                elif size is not None:
                    # Convert bytes to human-readable format
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                else:
                    size_str = ""

                # Format the line: <type> <name> <size> - modified: <timestamp>
                line = f"{item_type} {name}"
                if size_str:
                    line += f" ({size_str})"
                if last_modified:
                    line += f" - modified: {last_modified}"

                result_lines.append(line)

        return {
            "error": "",
            "result": result_lines,
        }
    except (JupyterConnectionError, JupyterAuthError) as e:
        return {
            "error": str(e),
            "result": [],
        }
    except Exception:
        return {
            "error": traceback.format_exc(),
            "result": [],
        }


def main() -> None:
    """Entry point for the MCP server."""
    import argparse
    from importlib.metadata import version

    # Load .env file first to ensure environment variables are available
    parent_folder = Path(__file__).resolve().parent
    env_path = parent_folder / ".env"
    load_dotenv(dotenv_path=env_path)

    # Set up argument parser
    # Default values come from environment variables (already loaded from .env)
    parser = argparse.ArgumentParser(
        prog="jupyter-interpreter-mcp",
        description="MCP server for executing code in remote Jupyter notebooks",
    )
    parser.add_argument(
        "--jupyter-base-url",
        default=os.getenv("JUPYTER_BASE_URL", "http://localhost:8888"),
        help="Base URL of the Jupyter server (default: %(default)s)",
    )
    parser.add_argument(
        "--jupyter-token",
        default=os.getenv("JUPYTER_TOKEN"),
        help="Authentication token for Jupyter server",
    )
    parser.add_argument(
        "--notebooks-folder",
        default=os.getenv("NOTEBOOKS_FOLDER", "/home/jovyan/notebooks"),
        help="Path for session notebook storage (default: %(default)s)",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"jupyter-interpreter-mcp {version('jupyter-interpreter-mcp')}",
    )

    # Parse arguments (CLI args will override the defaults)
    args = parser.parse_args()

    # Build configuration with precedence: CLI args > env vars > defaults
    # argparse already handles this via default= parameter
    base_url = args.jupyter_base_url
    token = args.jupyter_token
    notebooks_folder_path = args.notebooks_folder

    # Initialize remote client
    global remote_client, notebooks_folder
    try:
        if not token:
            raise ValueError(
                "JUPYTER_TOKEN is required "
                "(provide via --jupyter-token or environment variable)"
            )
        remote_client = RemoteJupyterClient(base_url=base_url, auth_token=token)
        notebooks_folder = notebooks_folder_path
        # Validate connection on startup
        remote_client.validate_connection()
    except (JupyterConnectionError, JupyterAuthError) as e:
        print(
            f"Failed to connect to Jupyter server at {base_url}: {e}", file=sys.stderr
        )
        print(
            "Please check your configuration and ensure Jupyter server is running.",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError as e:
        print(f"Invalid configuration: {e}", file=sys.stderr)
        sys.exit(1)

    mcp.run()


if __name__ == "__main__":
    main()
