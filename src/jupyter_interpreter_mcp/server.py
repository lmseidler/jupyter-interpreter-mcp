import asyncio
import base64
import json
import os
import posixpath
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
remote_client: RemoteJupyterClient = None  # type: ignore
sessions_dir: str = os.getenv("SESSIONS_DIR", "/home/jovyan/sessions")
jupyter_root: str = os.getenv("JUPYTER_ROOT", "/home/jovyan")
session_ttl: float = float(os.getenv("SESSION_TTL", "0"))

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


async def _validate_session_and_path(
    session_id: str,
    path: str,
) -> tuple[Session, str]:
    """Validate *session_id* and *path*; return ``(session, api_path)``.

    *api_path* is the Jupyter Contents API path derived by resolving *path*
    relative to the session sandbox directory and then expressing the result
    relative to *jupyter_root* using POSIX separators.

    :param session_id: Session identifier to validate.
    :type session_id: str
    :param path: File/directory path relative to the session directory.
    :type path: str
    :return: Tuple of the validated :class:`~jupyter_interpreter_mcp.session.Session`
        object and the Contents API path string.
    :rtype: tuple[Session, str]
    :raises ValueError: If the session is not found, has expired, or *path*
        escapes the session sandbox.
    """
    from jupyter_interpreter_mcp.session import validate_path

    global sessions, jupyter_root

    await ensure_session_available(session_id)

    async with registry_lock:
        if session_id not in sessions:
            raise ValueError(f"Session {session_id} not found")
        session = sessions[session_id]
        if session.is_expired(session_ttl):
            raise ValueError(f"Session {session_id} has expired")

    validated_path = validate_path(session.directory, path)
    jupyter_root_abs = posixpath.normpath(jupyter_root)
    api_path = posixpath.relpath(validated_path, jupyter_root_abs)
    return session, api_path


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
        "Executes code (Python or bash) within a persistent session. Past results "
        "(e.g., variables, imports) can be reused, similar to a Jupyter notebook. "
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
    from jupyter_interpreter_mcp.remote import JupyterConnectionError
    from jupyter_interpreter_mcp.session import detect_content_type, is_sensitive_file

    global remote_client

    try:
        session, api_path = await _validate_session_and_path(session_id, path)

        # Prevent access to sensitive files within the sandbox
        if is_sensitive_file(Path(api_path)):
            return {"error": "Access to this file is restricted for security reasons."}

        # Fetch file content via Contents API
        try:
            contents = remote_client.get_file_contents(api_path)
        except JupyterConnectionError:
            return {"error": f"File not found: {path}"}

        file_format = contents.get("format", "text")
        raw_content = contents.get("content", "")
        filename = os.path.basename(path)

        if file_format == "base64":
            # Binary file — decode to check content type then return appropriately
            content_bytes = base64.b64decode(raw_content)
            content_type = detect_content_type(path, content_bytes)
            if content_type == "binary":
                response: dict[str, str] = {
                    "content": raw_content,
                    "encoding": "base64",
                    "filename": filename,
                }
            else:
                response = {
                    "content": content_bytes.decode("utf-8"),
                    "encoding": "text",
                    "filename": filename,
                }
        elif file_format == "text":
            # Text file
            response = {
                "content": raw_content,
                "encoding": "text",
                "filename": filename,
            }
        else:
            # Other formats (e.g. JSON notebooks) — serialize to text to avoid non-string content
            try:
                serialized_content = json.dumps(raw_content, ensure_ascii=False)
            except TypeError:
                serialized_content = str(raw_content)
            response = {
                "content": serialized_content,
                "encoding": "text",
                "filename": filename,
            }

        # Update last access
        session.touch()
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        return response

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Download failed: {str(e)}"}


@mcp.tool(
    "upload_file_path",
    description=(
        "Uploads a file from the host filesystem to the session directory using "
        "a local absolute path. Uploads files up to 100 MB via the Jupyter "
        "Contents API. Requires a valid session_id. "
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
    constraints, and uploads the content to the sandbox session directory
    at *destination_path* via the Jupyter Contents API (single PUT request).

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
    )

    global remote_client

    try:
        # Validate session and destination path together.
        session, api_dest = await _validate_session_and_path(
            session_id, destination_path
        )

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
        # (already done by _validate_session_and_path above; api_dest is ready)

        # 3.7 Overwrite protection via Contents API existence check
        if not overwrite:
            if remote_client.check_exists(api_dest):
                return {
                    "error": (
                        f"Destination already exists: {destination_path} "
                        "(set overwrite=True to replace)"
                    )
                }

        # 3.8 Ensure destination parent directory exists via Contents API
        parent_api_path = os.path.dirname(api_dest)
        if parent_api_path:
            remote_client.create_directory(parent_api_path)

        # 3.9 Read the full file and upload via a single PUT request.
        # The Jupyter Contents API delivers the file as a single JSON payload;
        # Tornado's default max_body_size is 100 MB. Reject files larger than
        # this to avoid silent OOM / server-side rejection.
        MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
        file_size = os.path.getsize(resolved_host)
        if file_size > MAX_UPLOAD_BYTES:
            return {
                "error": (
                    f"File too large to upload ({file_size:,} bytes). "
                    f"Maximum supported size is {MAX_UPLOAD_BYTES:,} bytes (100 MB)."
                )
            }

        with open(resolved_host, "rb") as f:
            file_bytes = f.read()

        file_b64 = base64.b64encode(file_bytes).decode("ascii")
        remote_client.put_contents(api_dest, file_b64, format="base64")

        # Update last access
        session.touch()
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        # Return success with relative sandbox_path so agents can
        # reference it directly in execute_code calls.
        return {
            "status": "success",
            "sandbox_path": destination_path,
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
    global remote_client, sessions_dir, jupyter_root

    try:
        session, api_path = await _validate_session_and_path(session_id, path)

        jupyter_root_abs = posixpath.normpath(jupyter_root)
        sessions_dir_abs = posixpath.normpath(sessions_dir)

        # Confirm the resolved path is still within the Jupyter root.
        # api_path is relative to jupyter_root by construction; re-joining
        # gives the absolute form for the commonpath check.
        validated_abs = posixpath.normpath(posixpath.join(jupyter_root_abs, api_path))

        try:
            # Ensure sessions_dir is under the Jupyter root
            if (
                posixpath.commonpath([jupyter_root_abs, sessions_dir_abs])
                != jupyter_root_abs
            ):
                return {
                    "error": (
                        f"sessions_dir ({sessions_dir_abs}) is not "
                        f"under the Jupyter root "
                        f"({jupyter_root_abs}); "
                        "please check configuration."
                    ),
                    "result": [],
                }

            # Ensure the requested path is also under the Jupyter root
            if (
                posixpath.commonpath([jupyter_root_abs, validated_abs])
                != jupyter_root_abs
            ):
                return {
                    "error": (
                        f"Path {validated_abs} is outside the Jupyter root "
                        f"({jupyter_root_abs}); refusing to access it."
                    ),
                    "result": [],
                }
        except ValueError:
            # Paths on different drives or otherwise incomparable
            return {
                "error": (
                    "Invalid path configuration: "
                    "sessions_dir and Jupyter root "
                    "are incompatible."
                ),
                "result": [],
            }

        # Get contents via Jupyter Contents API
        # Using sync method from RemoteJupyterClient as per codebase pattern
        response = remote_client.get_contents(api_path)

        if response.get("type") != "directory":
            return {"error": f"Not a directory: {path}", "result": []}

        entries = response.get("content", [])
        result_lines = []

        if not entries:
            result_lines.append("(empty directory)")
        else:
            # Sort entries: directories first, then alphabetically
            sorted_entries = sorted(
                entries,
                key=lambda x: (x.get("type") != "directory", x.get("name", "").lower()),
            )

            for entry in sorted_entries:
                name = entry.get("name", "unknown")
                item_type = entry.get("type", "unknown")
                mtime = entry.get("last_modified", "unknown")

                if item_type == "directory":
                    result_lines.append(f"directory {name} - modified: {mtime}")
                else:
                    size = entry.get("size", 0)
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                    result_lines.append(
                        f"{item_type} {name} ({size_str}) - modified: {mtime}"
                    )

        # Update last access
        session.touch()
        # Still update metadata on remote side for persistence
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        return {"error": "", "result": result_lines}

    except ValueError as e:
        return {"error": str(e), "result": []}
    except Exception as e:
        return {"error": f"List directory failed: {str(e)}", "result": []}


@mcp.tool(
    "read_file",
    description=(
        "Reads a text file from the session directory and returns its content "
        "with 1-indexed line numbers. Requires a valid session_id. "
        "Use offset and limit to page through large files without filling the "
        "context window (default: first 200 lines). "
        "Binary files are not supported; use download_file for those."
    ),
)
async def read_file(
    session_id: str,
    path: str,
    offset: int = 1,
    limit: int = 200,
) -> dict[str, object]:
    """Read a text file from the session sandbox with optional line windowing.

    Returns up to *limit* lines starting at 1-indexed line *offset*, each
    prefixed with its line number (``"42: content"``).  Metadata fields
    indicate the total line count and whether the result was truncated.

    :param session_id: Valid session identifier.
    :type session_id: str
    :param path: File path relative to the session directory.
    :type path: str
    :param offset: 1-indexed line number to start reading from (default 1).
    :type offset: int
    :param limit: Maximum number of lines to return (default 200).
    :type limit: int
    :return: Dictionary with ``lines`` (list of numbered line strings),
        ``total_lines``, ``offset``, ``limit``, ``truncated``, and
        ``path``; or ``error`` on failure.
    :rtype: dict[str, object]
    """
    from jupyter_interpreter_mcp.remote import JupyterConnectionError
    from jupyter_interpreter_mcp.session import is_sensitive_file

    global remote_client

    try:
        if offset < 1:
            return {"error": "offset must be >= 1"}
        if limit < 1:
            return {"error": "limit must be >= 1"}

        # Sensitive-file guard.
        if is_sensitive_file(path):
            return {
                "error": (
                    f"Access blocked: '{os.path.basename(path)}' matches a "
                    "sensitive file pattern"
                )
            }

        session, api_path = await _validate_session_and_path(session_id, path)

        try:
            contents = remote_client.get_file_contents(api_path)
        except JupyterConnectionError:
            return {"error": f"File not found: {path}"}

        # Binary files cannot be read as text lines.
        file_format = contents.get("format", "text")
        raw_content = contents.get("content", "")
        if file_format == "base64":
            return {
                "error": (
                    "Binary files cannot be read with read_file. "
                    "Use download_file to retrieve binary content."
                )
            }

        # Only plain text content is supported here. Other formats (e.g., JSON)
        # may return non-string content (dict/list) from the Jupyter Contents API.
        if file_format != "text":
            return {
                "error": (
                    f"Unsupported file format '{file_format}' for read_file. "
                    "Only text files can be read as lines. "
                    "Use download_file for binary or structured content."
                )
            }

        if not isinstance(raw_content, str):
            return {
                "error": (
                    "Unsupported content type for read_file; expected text "
                    "content but received a non-text value from the server."
                )
            }

        # Split into lines and apply offset/limit window.
        all_lines = raw_content.splitlines()
        total_lines = len(all_lines)

        # Clamp offset to valid range (1-indexed → 0-indexed).
        start_idx = max(0, offset - 1)
        end_idx = start_idx + limit
        window = all_lines[start_idx:end_idx]
        truncated = end_idx < total_lines

        numbered = [f"{start_idx + 1 + i}: {line}" for i, line in enumerate(window)]

        session.touch()
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        return {
            "lines": numbered,
            "total_lines": total_lines,
            "offset": offset,
            "limit": limit,
            "truncated": truncated,
            "path": path,
        }

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Read failed: {str(e)}"}


@mcp.tool(
    "write_file",
    description=(
        "Writes text content to a file in the session directory, creating or "
        "overwriting it. Requires a valid session_id. Parent directories are "
        "created automatically. Binary uploads should use upload_file_path "
        "instead."
    ),
)
async def write_file(
    session_id: str,
    path: str,
    content: str,
) -> dict[str, object]:
    """Write (create or overwrite) a text file in the session sandbox.

    :param session_id: Valid session identifier.
    :type session_id: str
    :param path: Destination file path relative to the session directory.
    :type path: str
    :param content: Text content to write.
    :type content: str
    :return: Dictionary with ``status``, ``path``, and ``bytes_written`` on
        success; or ``error`` on failure.
    :rtype: dict[str, object]
    """
    from jupyter_interpreter_mcp.session import is_sensitive_file

    global remote_client

    try:
        # Basic path validation: reject empty paths and directory-like paths.
        if not path or not path.strip():
            return {"error": "Invalid path: destination path must not be empty."}
        if path.endswith("/"):
            return {
                "error": (
                    "Invalid path: destination path must not end with '/'; "
                    "please provide a file name."
                )
            }

        # Sensitive-file guard.
        if is_sensitive_file(path):
            return {
                "error": (
                    f"Write blocked: '{os.path.basename(path)}' matches a "
                    "sensitive file pattern"
                )
            }

        session, api_path = await _validate_session_and_path(session_id, path)

        # Ensure parent directory exists before writing.
        parent_api_path = posixpath.dirname(api_path)
        if parent_api_path:
            remote_client.create_directory(parent_api_path)

        remote_client.put_contents(api_path, content, format="text")

        session.touch()
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        return {
            "status": "ok",
            "path": path,
            "bytes_written": len(content.encode("utf-8")),
        }

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Write failed: {str(e)}"}


@mcp.tool(
    "edit_file",
    description=(
        "Edits a text file in the session directory by replacing an exact "
        "substring (old_string) with new_string. Requires a valid session_id. "
        "Three matching strategies are tried in order: exact, line-trimmed "
        "(leading/trailing whitespace ignored per line), and "
        "indentation-flexible (common indent level stripped before comparing). "
        "By default the match must be unique; set replace_all=True to replace "
        "every occurrence. Use read_file first to confirm the exact content."
    ),
)
async def edit_file(
    session_id: str,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, object]:
    """Edit a text file by replacing a substring in the session sandbox.

    :param session_id: Valid session identifier.
    :type session_id: str
    :param path: File path relative to the session directory.
    :type path: str
    :param old_string: The text to find and replace.  Must be non-empty.
    :type old_string: str
    :param new_string: The replacement text.
    :type new_string: str
    :param replace_all: Replace all occurrences instead of requiring a unique
        match (default ``False``).
    :type replace_all: bool
    :return: Dictionary with ``status``, ``path``, and ``replacements`` on
        success; or ``error`` on failure.
    :rtype: dict[str, object]
    """
    from jupyter_interpreter_mcp.editing import EditError, find_and_replace
    from jupyter_interpreter_mcp.remote import JupyterConnectionError
    from jupyter_interpreter_mcp.session import is_sensitive_file

    global remote_client

    try:
        # Sensitive-file guard.
        if is_sensitive_file(path):
            return {
                "error": (
                    f"Edit blocked: '{os.path.basename(path)}' matches a "
                    "sensitive file pattern"
                )
            }

        session, api_path = await _validate_session_and_path(session_id, path)

        # Fetch current file content.
        try:
            contents = remote_client.get_file_contents(api_path)
        except JupyterConnectionError:
            return {"error": f"File not found: {path}"}

        # Binary files cannot be edited as text.
        file_format = contents.get("format", "text")
        raw_content = contents.get("content", "")
        if file_format == "base64":
            return {
                "error": (
                    "Binary files cannot be edited with edit_file. "
                    "Use execute_code to manipulate binary content."
                )
            }

        # Only plain-text files with string content are supported.
        if file_format != "text" or not isinstance(raw_content, str):
            return {
                "error": (
                    f"Unsupported file format for editing: {file_format!r}. "
                    "Only text files with string content can be edited."
                )
            }

        # Apply the replacement.
        try:
            new_content, count = find_and_replace(
                raw_content, old_string, new_string, replace_all=replace_all
            )
        except EditError as e:
            return {"error": str(e)}

        # Write the updated content back.
        remote_client.put_contents(api_path, new_content, format="text")

        session.touch()
        await remote_client.update_session_metadata(
            session.kernel_id, session.directory, session.last_access
        )

        return {
            "status": "ok",
            "path": path,
            "replacements": count,
        }

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Edit failed: {str(e)}"}


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
        "--jupyter-root",
        default=os.getenv("JUPYTER_ROOT", "/home/jovyan"),
        help=(
            "Root directory of the remote Jupyter server filesystem. "
            "Used to derive Contents API paths. (default: %(default)s)"
        ),
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
            "only allowed from the current working directory."
        ),
    )
    parser.add_argument(
        "--allow-all",
        dest="allow_all",
        action="store_true",
        help="Allow uploads from all directories.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"jupyter-interpreter-mcp {version('jupyter-interpreter-mcp')}",
    )

    # Parse arguments (CLI args will override the defaults)
    args = parser.parse_args()

    # Configure allowed upload directories from CLI args only.
    # The env var (ALLOWED_UPLOAD_DIRS) and CWD fallback are handled lazily
    # by get_allowed_upload_dirs() in session.py.
    from jupyter_interpreter_mcp.session import (
        get_allowed_upload_dirs,
        set_allowed_upload_dirs,
    )

    if args.allow_all:
        set_allowed_upload_dirs([])
        print("Allowing uploads from all directories")
    elif args.allowed_dirs:
        set_allowed_upload_dirs(args.allowed_dirs)

    if not args.allow_all:
        print(f"Allowed upload directories: {', '.join(get_allowed_upload_dirs())}")

    # Build configuration with precedence: CLI args > env vars > defaults
    # argparse already handles this via default= parameter
    base_url = args.jupyter_base_url
    token = args.jupyter_token
    sessions_dir_path = args.sessions_dir
    jupyter_root_path = args.jupyter_root
    ttl = args.session_ttl

    # Initialize remote client
    global remote_client, sessions_dir, jupyter_root, session_ttl
    try:
        if not token:
            raise ValueError(
                "JUPYTER_TOKEN is required "
                "(provide via --jupyter-token or environment variable)"
            )
        remote_client = RemoteJupyterClient(base_url=base_url, auth_token=token)
        sessions_dir = sessions_dir_path
        jupyter_root = jupyter_root_path
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
