import asyncio
import base64
import json
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
from jupyter_interpreter_mcp.session import Session

# Global variables initialized in main()
remote_client: RemoteJupyterClient
sessions_dir: str
session_ttl: float

mcp = FastMCP(
    name="Code Interpreter",
    instructions="""You can execute code by sending a request with the code you want
to run. Think of this tool as a jupyter notebook. It will remember your previously
executed code, if you pass in your session_id. It is crucial to provide your
session_id for that to work.

Supports both Python code and bash commands (e.g., 'ls', 'pwd', 'cat file.txt').
""",
)

# Session registry: session_id -> Session object
sessions: dict[str, Session] = {}
# Notebook registry: session_id -> Notebook object
notebooks: dict[str, Notebook] = {}

# Locks for thread-safe access to registries
registry_lock = asyncio.Lock()


async def get_session_and_notebook(session_id: str) -> tuple[Session, Notebook]:
    """Retrieve session and notebook objects while holding the registry lock.

    :param session_id: Unique identifier for the session.
    :return: A tuple of (Session, Notebook).
    :raises ValueError: If the session is not found or is expired.
    """
    async with registry_lock:
        if session_id not in sessions:
            raise ValueError(f"Session {session_id} not found")

        session = sessions[session_id]
        if session.is_expired(session_ttl):
            raise ValueError(f"Session {session_id} has expired")

        notebook = notebooks.get(session_id)
        if not notebook:
            raise ValueError(f"Notebook for session {session_id} not found")

        return session, notebook


async def cleanup_expired_sessions() -> int:
    """Clean up sessions that have exceeded their TTL.

    :return: Number of sessions cleaned up.
    :rtype: int
    """
    global sessions, notebooks, remote_client, session_ttl

    if session_ttl <= 0:
        return 0  # No cleanup if TTL is disabled

    async with registry_lock:
        expired_ids = [
            sid for sid, session in sessions.items() if session.is_expired(session_ttl)
        ]

        for session_id in expired_ids:
            try:
                session = sessions[session_id]

                # Shutdown kernel
                try:
                    remote_client.shutdown_kernel(session.kernel_id)
                except Exception as e:
                    print(
                        f"Warning: Failed to shutdown kernel for session "
                        f"{session_id}: {e}",
                        file=sys.stderr,
                    )

                # Remove from registries
                sessions.pop(session_id, None)
                notebooks.pop(session_id, None)

                print(f"Cleaned up expired session: {session_id}")
            except Exception as e:
                print(f"Error cleaning up session {session_id}: {e}", file=sys.stderr)

        return len(expired_ids)


async def restore_sessions_from_disk(target_session_id: str | None = None) -> int:
    """Restore existing sessions from disk on server startup.

    Scans the sessions directory for existing session folders, reads their
    metadata, creates new kernels, and populates the sessions registry.

    :param target_session_id: Optional specific session ID to restore.
        If provided, only that session is considered.
    :type target_session_id: str | None
    :return: Number of sessions restored.
    :rtype: int
    """
    global sessions, notebooks, remote_client, sessions_dir, session_ttl

    # Create a temporary kernel to list session directories
    temp_kernel_id = None
    try:
        temp_kernel_id = remote_client.create_kernel()
    except Exception as e:
        print(f"Error creating temporary kernel for restoration: {e}", file=sys.stderr)
        return 0

    restored_count = 0

    try:
        # Execute code to list session directories
        list_code = f"""
import os
import json

sessions_dir = {repr(sessions_dir)}
target_session_id = {repr(target_session_id)}
result = []

if os.path.exists(sessions_dir):
    for item in os.listdir(sessions_dir):
        if target_session_id and item != target_session_id:
            continue
        item_path = os.path.join(sessions_dir, item)
        if os.path.isdir(item_path):
            metadata_path = os.path.join(item_path, '.session.json')
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                result.append({{
                    'session_id': item,
                    'created_at': metadata.get('created_at'),
                    'last_access': metadata.get('last_access'),
                    'directory': item_path
                }})

print("SESSION_LIST_START")
print(json.dumps(result))
print("SESSION_LIST_END")
"""
        result = await remote_client.execute(temp_kernel_id, list_code)
        if result["error"]:
            print(
                f"Error listing sessions: {'; '.join(result['error'])}", file=sys.stderr
            )
            return 0

        output = "".join(result["result"])
        if "SESSION_LIST_START" not in output or "SESSION_LIST_END" not in output:
            return 0

        start_idx = output.index("SESSION_LIST_START") + len("SESSION_LIST_START")
        end_idx = output.index("SESSION_LIST_END")
        sessions_json = output[start_idx:end_idx].strip()
        sessions_to_restore = json.loads(sessions_json)

        for meta in sessions_to_restore:
            session_id = meta["session_id"]
            created_at = meta["created_at"]
            last_access = meta["last_access"]
            session_directory = meta["directory"]

            # Double-checked locking to prevent duplicate restoration
            async with registry_lock:
                if session_id in sessions:
                    continue

            if created_at is None or last_access is None:
                print(f"Skipping {session_id}: invalid metadata")
                continue

            # Check if session is expired
            if session_ttl > 0:
                age = time.time() - last_access
                if age > session_ttl:
                    print(f"Skipping {session_id}: expired ({age:.0f}s old)")
                    continue

            try:
                # Create kernel for restored session
                kernel_id = remote_client.create_kernel()

                # Change working directory
                chdir_code = f"import os\nos.chdir({repr(session_directory)})"
                chdir_result = await remote_client.execute(kernel_id, chdir_code)
                if chdir_result["error"]:
                    print(
                        f"Warning: Failed to set working directory for {session_id}: "
                        f"{'; '.join(chdir_result['error'])}",
                        file=sys.stderr,
                    )
                    remote_client.shutdown_kernel(kernel_id)
                    continue

                # Create session object
                session = Session(
                    id=session_id,
                    kernel_id=kernel_id,
                    created_at=created_at,
                    last_access=last_access,
                    directory=session_directory,
                )

                # Create notebook object
                notebook = Notebook(session_id, remote_client, session_directory)
                notebook.kernel_id = kernel_id

                # Restore execution history
                history_restored = await notebook.load_from_file()
                if not history_restored:
                    print(
                        f"Warning: Failed to restore history for session {session_id}",
                        file=sys.stderr,
                    )
                    remote_client.shutdown_kernel(kernel_id)
                    continue

                async with registry_lock:
                    # Check again inside the lock before committing
                    if session_id not in sessions:
                        sessions[session_id] = session
                        notebooks[session_id] = notebook
                        print(f"Restored session: {session_id}")
                        restored_count += 1
                    else:
                        print(f"Session {session_id} already restored by another task")
                        remote_client.shutdown_kernel(kernel_id)

            except Exception as e:
                print(f"Error restoring session {session_id}: {e}", file=sys.stderr)
                continue

    finally:
        # Clean up temporary kernel
        if temp_kernel_id is not None:
            try:
                remote_client.shutdown_kernel(temp_kernel_id)
            except Exception:
                pass

    return restored_count


async def ensure_session_available(session_id: str) -> bool:
    """Ensure a session is loaded in memory, restoring it on-demand if needed.

    :param session_id: Session ID to ensure is available.
    :type session_id: str
    :return: True if the session is available in memory, False otherwise.
    :rtype: bool
    """
    async with registry_lock:
        if session_id in sessions and session_id in notebooks:
            return True

    # restore_sessions_from_disk has its own double-checked locking
    restored = await restore_sessions_from_disk(session_id)

    async with registry_lock:
        return restored > 0 and session_id in sessions and session_id in notebooks


@mcp.tool(
    "create_session",
    description=(
        "Creates a new isolated code execution session. Returns a unique session_id "
        "that must be used in all subsequent operations (execute_code, "
        "upload_file_path, download_file, list_dir). Each session has its "
        "own directory and kernel."
    ),
)
async def create_session() -> dict[str, str]:
    """Creates a new session with isolated directory and kernel.

    :return: A dictionary with 'session_id' key containing the new UUID.
    :rtype: dict[str, str]
    """
    from jupyter_interpreter_mcp.session import generate_session_id

    global sessions, notebooks, remote_client, sessions_dir

    kernel_id = None
    try:
        # Generate session ID
        session_id = generate_session_id()

        # Create kernel
        kernel_id = remote_client.create_kernel()

        # Create session directory
        current_time = time.time()
        session_directory = os.path.join(sessions_dir, session_id)
        await remote_client.create_session_directory(
            kernel_id, session_directory, current_time, current_time
        )

        # Change kernel working directory to session directory
        chdir_code = f"""
import os
os.chdir({repr(session_directory)})
print(f"Working directory: {{os.getcwd()}}")
"""
        chdir_result = await remote_client.execute(kernel_id, chdir_code)
        if chdir_result["error"]:
            raise Exception(
                f"Failed to set working directory: {'; '.join(chdir_result['error'])}"
            )

        # Create session object
        session = Session(
            id=session_id,
            kernel_id=kernel_id,
            created_at=current_time,
            last_access=current_time,
            directory=session_directory,
        )

        # Create notebook object
        notebook = Notebook(session_id, remote_client, session_directory)
        notebook.kernel_id = kernel_id

        async with registry_lock:
            sessions[session_id] = session
            notebooks[session_id] = notebook

        return {"session_id": session_id}
    except Exception as e:
        # Clean up kernel if it was created
        if kernel_id is not None:
            try:
                remote_client.shutdown_kernel(kernel_id)
            except Exception as cleanup_err:
                print(
                    f"Warning: Failed to cleanup kernel {kernel_id}: {cleanup_err}",
                    file=sys.stderr,
                )
        return {"error": f"Failed to create session: {str(e)}"}


@mcp.tool(
    "execute_code",
    description=(
        "Executes code (Python or bash) within a persistent session, retaining "
        "past results (e.g., variables, imports). Similar to a Jupyter notebook. "
        "Requires a valid session_id obtained from create_session. "
        "Bash commands (e.g., 'ls', 'pwd') work directly without wrappers and "
        "can be used to install packages."
    ),
)
async def execute_code(code: str, session_id: str) -> dict[str, list[str] | str]:
    """Executes the provided code and returns the result.

    :param code: The code to execute (Python or bash commands).
    :type code: str
    :param session_id: Valid session identifier obtained from create_session.
    :type session_id: str
    :return: A dictionary with 'error' and 'result' keys (each containing a list of
        strings), and 'session_id' key (containing the session ID string).
    :rtype: dict
    """
    global sessions, notebooks, remote_client

    try:
        # Restore from disk if not already loaded in memory
        await ensure_session_available(session_id)

        # Validate session and get objects under lock
        session, notebook = await get_session_and_notebook(session_id)

        # Execute code
        result: dict[str, list[str]] = await notebook.execute_new_code(code)

        # Update last access time
        session.touch()
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        # Add session_id to the response
        response: dict[str, list[str] | str] = {
            "error": result["error"],
            "result": result["result"],
            "session_id": session_id,
        }

        if len(result["error"]) == 0:
            await notebook.dump_to_file()

        return response
    except ValueError as e:
        # Session validation error
        return {
            "error": [str(e)],
            "result": [],
            "session_id": session_id,
        }
    except Exception:
        return {
            "error": [traceback.format_exc()],
            "result": [],
            "session_id": session_id,
        }


@mcp.tool(
    "download_file",
    description=(
        "Downloads a file from the session directory and returns its "
        "full content. Requires a valid session_id. Returns file "
        "content as text or base64-encoded binary depending on file "
        "type. For large files, use list_dir to discover paths and "
        "reference them directly in execute_code instead of "
        "downloading."
    ),
)
async def download_file(session_id: str, path: str) -> dict[str, str]:
    """Downloads a file from the session directory.

    Returns the full content of a file from the sandbox.

    :param session_id: Valid session identifier.
    :type session_id: str
    :param path: File path relative to session directory.
    :type path: str
    :return: Dictionary with 'content', 'encoding' ('text' or 'base64'), or 'error'.
    :rtype: dict[str, str]
    """
    from jupyter_interpreter_mcp.session import detect_content_type, validate_path

    global sessions, notebooks

    try:
        # Restore from disk if not already loaded in memory
        await ensure_session_available(session_id)

        # Validate session and get objects under lock
        session, notebook = await get_session_and_notebook(session_id)

        # Validate path
        validated_path = validate_path(session.directory, path)

        # Read file content via kernel
        code = f"""
import os
import base64

file_path = {repr(validated_path)}
if not os.path.exists(file_path):
    print("FILE_NOT_FOUND")
else:
    with open(file_path, 'rb') as f:
        content_bytes = f.read()

    # Return base64-encoded content
    print("FILE_CONTENT_START")
    print(base64.b64encode(content_bytes).decode('ascii'))
    print("FILE_CONTENT_END")
"""

        result = await notebook.execute_new_code(code)

        if result["error"]:
            return {"error": "; ".join(result["error"])}

        output = "".join(result["result"])

        if "FILE_NOT_FOUND" in output:
            return {"error": f"File not found: {path}"}

        # Extract base64 content
        if "FILE_CONTENT_START" in output and "FILE_CONTENT_END" in output:
            start_idx = output.index("FILE_CONTENT_START") + len("FILE_CONTENT_START")
            end_idx = output.index("FILE_CONTENT_END")
            base64_content = output[start_idx:end_idx].strip()

            # Decode to check content type
            content_bytes = base64.b64decode(base64_content)
            content_type = detect_content_type(path, content_bytes)

            if content_type == "binary":
                # Return as base64
                response = {
                    "content": base64_content,
                    "encoding": "base64",
                    "filename": os.path.basename(path),
                }
            else:
                # Decode as text
                text_content = content_bytes.decode("utf-8")
                response = {
                    "content": text_content,
                    "encoding": "text",
                    "filename": os.path.basename(path),
                }

            # Update last access
            session.touch()
            await remote_client.update_session_metadata(
                session.kernel_id, session.directory, session.last_access
            )

            return response
        else:
            return {"error": "Failed to read file content"}

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Download failed: {str(e)}"}


UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB for file path uploads


@mcp.tool(
    "upload_file_path",
    description=(
        "Uploads a file from the host filesystem to the session directory using "
        "a local absolute path. Streams the file in 8 MB chunks, making it "
        "suitable for large files. Requires a valid session_id. "
        "The host_path must be an absolute path within the allowed upload "
        "directories. Sensitive files (.env, .ssh/, credentials, etc.) are "
        "blocked. Set overwrite=False to prevent overwriting existing files. "
        "NOTE: The sandbox is an isolated environment -- this tool bridges the "
        "host filesystem to the sandbox so code can access the file."
    ),
)
async def upload_file_path(
    session_id: str,
    host_path: str,
    destination_path: str,
    overwrite: bool = True,
) -> dict[str, str]:
    """Upload a file from the host filesystem to the sandbox by path.

    Reads the file at *host_path* on the host, validates security
    constraints, and streams the content to the sandbox session directory
    at *destination_path* using chunked writes.

    :param session_id: Valid session identifier.
    :type session_id: str
    :param host_path: Absolute path to the file on the host filesystem.
        Must reside within the allowed upload directories (configured via
        the ``ALLOWED_UPLOAD_DIRS`` environment variable).
    :type host_path: str
    :param destination_path: Destination path relative to the session
        directory inside the sandbox.
    :type destination_path: str
    :param overwrite: If ``True`` (default), overwrite an existing file at
        the destination.  If ``False``, return an error when the
        destination already exists.
    :type overwrite: bool
    :return: Dictionary with ``sandbox_path`` on success or ``error`` key.
    :rtype: dict[str, str]
    """
    from jupyter_interpreter_mcp.session import (
        is_sensitive_file,
        validate_host_path,
        validate_path,
    )

    global sessions, notebooks

    try:
        # Restore from disk if not already loaded in memory
        await ensure_session_available(session_id)

        # Validate session and get objects under lock
        session, notebook = await get_session_and_notebook(session_id)

        # 3.1 Validate host_path is absolute (done inside validate_host_path)
        # 3.2 Security: check host_path against allowed directories
        resolved_host = validate_host_path(host_path)

        # 3.3 Security: check against sensitive file patterns
        if is_sensitive_file(resolved_host):
            return {
                "error": (
                    f"Upload blocked: '{os.path.basename(host_path)}' matches a "
                    "sensitive file pattern"
                )
            }

        # 3.4 File existence check
        if not os.path.exists(resolved_host):
            return {"error": f"Host file not found: {host_path}"}

        if not os.path.isfile(resolved_host):
            return {"error": f"Host path is not a file: {host_path}"}

        # 3.5 Permission check
        if not os.access(resolved_host, os.R_OK):
            return {"error": f"Permission denied: cannot read {host_path}"}

        # 3.6 Validate destination path within session directory
        validated_dest = validate_path(session.directory, destination_path)

        # 3.7 Overwrite protection
        if not overwrite:
            check_code = f"""
import os
print("EXISTS" if os.path.exists({repr(validated_dest)}) else "NOT_EXISTS")
"""
            check_result = await notebook.execute_new_code(check_code)
            if check_result["error"]:
                return {"error": "; ".join(check_result["error"])}
            check_output = "".join(check_result["result"]).strip()
            if "EXISTS" in check_output and "NOT_EXISTS" not in check_output:
                return {
                    "error": (
                        f"Destination already exists: {destination_path} "
                        "(set overwrite=True to replace)"
                    )
                }

        # 3.8 Chunked file streaming
        # Ensure destination directory exists
        mkdir_code = f"""
import os
os.makedirs(os.path.dirname({repr(validated_dest)}), exist_ok=True)
print("DIR_READY")
"""
        mkdir_result = await notebook.execute_new_code(mkdir_code)
        if mkdir_result["error"]:
            return {"error": "; ".join(mkdir_result["error"])}

        # Stream the file in chunks
        file_size = os.path.getsize(resolved_host)
        bytes_sent = 0

        with open(resolved_host, "rb") as f:
            first_chunk = True
            while True:
                chunk = f.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break

                chunk_b64 = base64.b64encode(chunk).decode("ascii")
                mode = "wb" if first_chunk else "ab"

                write_code = f"""
import base64
chunk_data = base64.b64decode({repr(chunk_b64)})
with open({repr(validated_dest)}, {repr(mode)}) as f:
    f.write(chunk_data)
print(f"Wrote {{len(chunk_data)}} bytes")
"""
                write_result = await notebook.execute_new_code(write_code)
                if write_result["error"]:
                    return {
                        "error": (
                            f"Upload failed during streaming: "
                            f"{'; '.join(write_result['error'])}"
                        )
                    }

                bytes_sent += len(chunk)
                first_chunk = False

        # Update last access
        session.touch()
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        # Return success with absolute sandbox_path so agents can
        # reference it directly in execute_code calls.
        return {
            "status": "success",
            "sandbox_path": validated_dest,
            "size": str(file_size),
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Upload by path failed: {str(e)}"}


@mcp.tool(
    "list_dir",
    description=(
        "Lists files and directories in a session directory. Requires a valid "
        "session_id. Optionally specify a subdirectory path."
    ),
)
async def list_dir(session_id: str, path: str = "") -> dict[str, list[str] | str]:
    """Lists files and directories in the session directory.

    :param session_id: Valid session identifier.
    :type session_id: str
    :param path: Optional subdirectory path relative to session directory.
    :type path: str
    :return: A dictionary with 'error' or 'result' key.
    :rtype: dict[str, list[str] | str]
    """
    from jupyter_interpreter_mcp.session import validate_path

    global sessions, notebooks

    try:
        # Restore from disk if not already loaded in memory
        await ensure_session_available(session_id)

        # Validate session and get objects under lock
        session, notebook = await get_session_and_notebook(session_id)

        # Validate path
        if path:
            validated_path = validate_path(session.directory, path)
        else:
            validated_path = session.directory

        # List directory via kernel execution
        code = f"""
import os
import json
from datetime import datetime
import stat

dir_path = {repr(validated_path)}
if not os.path.exists(dir_path):
    print("DIR_NOT_FOUND")
elif not os.path.isdir(dir_path):
    print("NOT_A_DIRECTORY")
else:
    entries = []
    for item in sorted(os.listdir(dir_path)):
        full_path = os.path.join(dir_path, item)
        try:
            st = os.lstat(full_path)
        except OSError:
            continue

        mode = stat.filemode(st.st_mode)
        mtime = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

        entry = {{
            'name': item,
            'mode': mode,
            'mtime': mtime
        }}

        if os.path.isdir(full_path):
            entry['type'] = 'directory'
        else:
            entry['type'] = 'file'
            entry['size'] = st.st_size

        entries.append(entry)

    print("DIR_LISTING_START")
    print(json.dumps(entries))
    print("DIR_LISTING_END")
"""

        result = await notebook.execute_new_code(code)

        if result["error"]:
            return {"error": "; ".join(result["error"]), "result": []}

        output = "".join(result["result"])

        if "DIR_NOT_FOUND" in output:
            return {"error": f"Directory not found: {path}", "result": []}
        if "NOT_A_DIRECTORY" in output:
            return {"error": f"Not a directory: {path}", "result": []}

        # Extract listing
        if "DIR_LISTING_START" in output and "DIR_LISTING_END" in output:
            start_idx = output.index("DIR_LISTING_START") + len("DIR_LISTING_START")
            end_idx = output.index("DIR_LISTING_END")
            listing_json = output[start_idx:end_idx].strip()

            entries = json.loads(listing_json)

            # Format output
            result_lines = []
            if not entries:
                result_lines.append("(empty directory)")
            else:
                for entry in entries:
                    item_type = entry["type"]
                    name = entry["name"]
                    mode = entry["mode"]
                    mtime = entry["mtime"]

                    if item_type == "directory":
                        result_lines.append(
                            f"{mode}  {mtime}  {'directory':>10}  {name}"
                        )
                    else:
                        size = entry.get("size", 0)
                        if size < 1024:
                            size_str = f"{size} B"
                        elif size < 1024 * 1024:
                            size_str = f"{size / 1024:.1f} KB"
                        else:
                            size_str = f"{size / (1024 * 1024):.1f} MB"
                        result_lines.append(f"{mode}  {mtime}  {size_str:>10}  {name}")

            # Update last access
            session.touch()
            await remote_client.update_session_metadata(
                session.kernel_id, session.directory, session.last_access
            )

            return {"error": "", "result": result_lines}
        else:
            return {"error": "Failed to retrieve directory listing", "result": []}

    except ValueError as e:
        return {"error": str(e), "result": []}
    except Exception as e:
        return {"error": f"List directory failed: {str(e)}", "result": []}


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
        "--sessions-dir",
        default=os.getenv("SESSIONS_DIR", "/home/jovyan/sessions"),
        help="Base directory for session storage (default: %(default)s)",
    )
    parser.add_argument(
        "--session-ttl",
        type=float,
        default=float(os.getenv("SESSION_TTL", "0")),
        help="Session time-to-live in seconds (0 = no expiry, default: %(default)s)",
    )
    parser.add_argument(
        "--restore-sessions-on-startup",
        action="store_true",
        default=os.getenv("RESTORE_SESSIONS_ON_STARTUP", "").strip().lower()
        in {"1", "true", "yes", "on"},
        help=(
            "Eagerly restore all sessions at startup "
            "(default: %(default)s, on-demand restore is always enabled)"
        ),
    )
    parser.add_argument(
        "--allowed-dir",
        action="append",
        dest="allowed_dirs",
        metavar="PATH",
        help=(
            "Allow file uploads from this directory (can be specified multiple times). "
            "Takes precedence over ALLOWED_UPLOAD_DIRS environment variable. "
            "If neither --allowed-dir nor ALLOWED_UPLOAD_DIRS is set, uploads are "
            "allowed from any directory (subject to sensitive file protection)."
        ),
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"jupyter-interpreter-mcp {version('jupyter-interpreter-mcp')}",
    )

    # Parse arguments (CLI args will override the defaults)
    args = parser.parse_args()

    # Configure allowed upload directories if specified
    if args.allowed_dirs:
        from jupyter_interpreter_mcp.session import set_allowed_upload_dirs

        set_allowed_upload_dirs(args.allowed_dirs)
        print(f"Allowed upload directories: {', '.join(args.allowed_dirs)}")
    elif os.getenv("ALLOWED_UPLOAD_DIRS"):
        print(
            f"Allowed upload directories (from env): {os.getenv('ALLOWED_UPLOAD_DIRS')}"
        )
    else:
        print("Allowed upload directories: all paths (no restriction)")

    # Build configuration with precedence: CLI args > env vars > defaults
    # argparse already handles this via default= parameter
    base_url = args.jupyter_base_url
    token = args.jupyter_token
    sessions_dir_path = args.sessions_dir
    ttl = args.session_ttl

    # Initialize remote client
    global remote_client, sessions_dir, session_ttl
    try:
        if not token:
            raise ValueError(
                "JUPYTER_TOKEN is required "
                "(provide via --jupyter-token or environment variable)"
            )
        remote_client = RemoteJupyterClient(base_url=base_url, auth_token=token)
        sessions_dir = sessions_dir_path
        session_ttl = ttl
        # Validate connection on startup
        remote_client.validate_connection()
        print(f"Connected to Jupyter server at {base_url}")
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

    import asyncio

    # Optional eager restore (on-demand restore is always active in execute_code)
    if args.restore_sessions_on_startup:
        print(f"Restoring sessions from {sessions_dir}...")
        try:
            restored = asyncio.run(restore_sessions_from_disk())
            print(f"Restored {restored} session(s)")
        except Exception as e:
            print(f"Warning: Session restoration failed: {e}", file=sys.stderr)
    else:
        print("Skipping eager startup restore (using on-demand session restore)")

    # Run cleanup of expired sessions
    if session_ttl > 0:
        try:
            cleaned = asyncio.run(cleanup_expired_sessions())
            if cleaned > 0:
                print(f"Cleaned up {cleaned} expired session(s)")
        except Exception as e:
            print(f"Warning: Session cleanup failed: {e}", file=sys.stderr)

    mcp.run()


if __name__ == "__main__":
    main()
