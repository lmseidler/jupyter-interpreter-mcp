# Jupyter Interpreter MCP
A remote Jupyter-based MCP (Model Context Protocol) server for code interpretation. This server connects to a remote Jupyter server (e.g. running in a Docker container or cloud instance) and provides a persistent, sandboxed code execution environment similar to Jupyter notebooks. Supports both Python and bash command execution.

## Architecture
```
MCP Server → RemoteJupyterClient → Jupyter REST API → Remote Kernel
                                          ↓
                              WebSocket Connection
                                          ↓
                           Jupyter server Filesystem
```
All code executes within the remote Jupyter server. Session history files are stored in the server's filesystem, not on the host. You can execute both Python code and bash commands (e.g., ls, pwd, cat file.txt). Requirements

## Requirements

- Python 3.10 or higher
- uv package manager
- Network access to a Jupyter server

## Quick Start

### 1. (Optional) Start Jupyter Container

This is only necessary if you don't use any other remote instance of Jupyter.
Run a Jupyter container with the required port mappings, e.g.:

```bash
docker run -d \
  --name jupyter-notebook \
  -p 8889:8888 \
  jupyter/minimal-notebook:latest
```

### 2. Get Authentication Token

Create a new token for accessing the Jupyter server or use an existing token.

### 3. Run the MCP server

#### Using uvx

Start the server using uvx:

```bash
uvx jupyter-interpreter-mcp --jupyter-base-url http://localhost:8889 --jupyter-token abc123def456... --sessions-dir /home/jovyan/sessions --session-ttl 3600
```

or to add it to e.g. Claude Code:

```json
{
  "mcpServers": {
    "jupyter-interpreter-mcp": {
      "command": "uvx",
      "args": [
        "jupyter-interpreter-mcp",
        "--jupyter-base-url",
        "http://localhost:8889",
        "--jupyter-token",
        "abc123def456...",
        "--sessions-dir",
        "/home/jovyan/sessions",
        "--session-ttl",
        "3600",
        "--restore-sessions-on-startup"
      ]
    }
  }
}
```

#### From source

Create a `.env` file in the project root:

```bash
JUPYTER_BASE_URL=http://localhost:8889
JUPYTER_TOKEN=abc123def456...
SESSIONS_DIR=/home/jovyan/sessions
SESSION_TTL=3600  # Optional: session expiry in seconds (0 = never expire)
RESTORE_SESSIONS_ON_STARTUP=false  # Optional: eager restore all sessions on startup
```

See `.env.example` for full configuration options and Docker setup instructions.

You can then install and run the server using uv:

```bash
uv pip install .
uv run jupyter-interpreter-mcp
```

---

The server will validate the connection to Jupyter on startup and fail with a clear error message if the connection cannot be established.

## Session-Based Workflow

The server uses a session-based architecture where each session has:
- A unique **UUID-based session ID**
- An **isolated directory** on the Jupyter server at `{sessions-dir}/{session-id}/`
- A **persistent Jupyter kernel** that maintains execution state (variables, imports)
- **On-demand restoration** on access after restart (with optional eager restore at startup)

### Typical Workflow

1. **Create a session** using `create_session`
2. **Execute code** in the session using `execute_code`
3. **Upload/download files** within the session directory using `upload_file_path` and `download_file`
4. **List files** in the session directory using `list_dir`

Sessions automatically expire after the configured TTL (time-to-live) period.

## Tools

### create_session

Creates a new isolated session with a dedicated directory and Jupyter kernel.

**Parameters:** None

**Returns:**
A dictionary containing:
- `session_id` (string): UUID identifier for the session

**Example usage:**
```python
result = create_session()
# Returns: {
#   "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
# }
```

### execute_code

Executes code (Python or bash) within a persistent session, retaining past results (e.g., variables, imports). Similar to a Jupyter notebook.

**Parameters:**
- `code` (string, required): The code to execute (Python or bash commands)
- `session_id` (string, required): The session ID from `create_session`

**Returns:**
A dictionary containing:
- `result` (list of strings): Output from the code execution
- `error` (list of strings): Any errors that occurred during execution
- `session_id` (string): The session ID used

**Example usage:**
```python
# Create a session first
session = create_session()
session_id = session["session_id"]

# Execute code in the session
result = execute_code(code="x = 42\nprint(x)", session_id=session_id)
# Returns: {"result": ["42"], "error": [], "session_id": "a1b2c3d4-..."}

# Subsequent execution - reuses the session state
result = execute_code(code="print(x * 2)", session_id=session_id)
# Returns: {"result": ["84"], "error": [], "session_id": "a1b2c3d4-..."}

# Bash commands
result = execute_code(code="ls -la", session_id=session_id)
```

### download_file

Download a file from the session directory.

**Parameters:**
- `session_id` (string, required): The session ID
- `path` (string, required): Relative path within session directory

**Returns:**
A dictionary containing:
- `content` (string): File content (base64-encoded for binary, plain text otherwise)
- `encoding` (string): Either `"base64"` or `"text"`
- `filename` (string): The basename of the downloaded file

**Example usage:**
```python
# Download text file
result = download_file(session_id=session_id, path="script.py")
# Returns: {"content": "print('Hello, World!')", "encoding": "text", "filename": "script.py"}

# Download binary file
result = download_file(session_id=session_id, path="images/logo.png")
# Returns: {"content": "iVBORw0KGgo...", "encoding": "base64", "filename": "logo.png"}
```

### list_dir

List files and directories within the session directory.

**Parameters:**
- `session_id` (string, required): The session ID
- `path` (string, optional): Subdirectory path within session (defaults to session root)

**Returns:**
A dictionary containing:
- `error` (string): Empty string on success, error message on failure
- `result` (list of strings): Formatted file/directory listing

**Example usage:**
```python
# List session root
result = list_dir(session_id=session_id)

# List subdirectory
result = list_dir(session_id=session_id, path="images")
```

### upload_file_path
Upload a file from the host filesystem to the session directory by providing its absolute path. Only files within allowed directories are permitted, and sensitive files (`.env`, `.ssh/`, credentials, etc.) are blocked.

**Parameters:**
- `session_id` (string, required): The session ID
- `host_path` (string, required): Absolute path to the file on the host filesystem
- `destination_path` (string, required): Relative path within session directory
- `overwrite` (boolean, optional): Whether to overwrite an existing file (default: `true`)

**Returns:**
A dictionary containing:
- `status` (string): `"success"` if the upload succeeded
- `sandbox_path` (string): Absolute path inside the sandbox
- `size` (string): File size in bytes

**Example usage:**
```python
result = upload_file_path(
    session_id=session_id,
    host_path="/home/user/data/dataset.csv",
    destination_path="data/dataset.csv",
    overwrite=False
)
```

## Path Security Configuration

The `upload_file_path` tool restricts which host filesystem paths can be uploaded for security. You can configure allowed directories using either a command-line argument or an environment variable.

### Configuration Methods (in order of precedence)

#### 1. `--allowed-dir` CLI Argument

Pass one or more `--allowed-dir` arguments when starting the server:

```bash
# Allow uploads from a single directory
jupyter-interpreter-mcp --allowed-dir /home/user/projects

# Allow uploads from multiple directories
jupyter-interpreter-mcp \
  --allowed-dir /home/user/projects \
  --allowed-dir /home/user/data
```

#### 2. `ALLOWED_UPLOAD_DIRS` Environment Variable

Set the `ALLOWED_UPLOAD_DIRS` environment variable to a colon-separated list of absolute directory paths:

```bash
# Allow uploads from multiple directories
export ALLOWED_UPLOAD_DIRS=/home/user/projects:/home/user/data

# Or in your .env file
ALLOWED_UPLOAD_DIRS=/home/user/projects:/home/user/data
```

#### 3. Allow all

Using the `--allow-all` flag will allow uploads from any directory on the host filesystem.

#### 4. Default Behavior

**When neither `--allowed-dir` nor `ALLOWED_UPLOAD_DIRS` is set, uploads are allowed only from the current working directory** on the host filesystem. Sensitive file protection (see below) is always active regardless of this setting.

### MCP Client Configuration Examples

#### OpenCode

In your `opencode.jsonc` (global config at `~/.config/opencode/opencode.json` or per-project):

```jsonc
{
  "mcp": {
    "jupyter-interpreter": {
      "type": "local",
      "command": [
        "uv", "run", "--project", "/path/to/jupyter-interpreter-mcp",
        "jupyter-interpreter-mcp",
        "--allowed-dir", "/home/user/projects",
        "--jupyter-base-url", "http://localhost:8888",
        // ... other args
      ],
      // Or use environment variables:
      "environment": {
        "ALLOWED_UPLOAD_DIRS": "/home/user/projects:/home/user/data"
      }
    }
  }
}
```

For most use cases, either use the environment variable approach with hardcoded paths, or rely on the "allow all" default with sensitive file protection.

#### Claude Desktop / Cursor

In `claude_desktop_config.json` or `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "jupyter-interpreter": {
      "command": "jupyter-interpreter-mcp",
      "args": [
        "--allowed-dir", "/home/user/projects",
        "--jupyter-base-url", "http://localhost:8888"
      ],
      "env": {
        "JUPYTER_TOKEN": "your-token-here"
      }
    }
  }
}
```

### Sensitive File Protection

Regardless of allowed directories, the following file patterns are **always blocked** from upload:
- `.env` files (e.g., `.env`, `.env.local`)
- SSH keys and configuration (`.ssh/`)
- GPG keys (`.gnupg/`)
- AWS credentials (`.aws/`)
- Docker credentials (`.docker/config.json`)
- Generic credential files (`credentials.json`, `credentials.yaml`)
- Netrc files (`.netrc`)
- NPM/PyPI tokens (`.npmrc`, `.pypirc`)
- Secret/token files (`secret.json`, `tokens.yaml`, etc.)
- Git credentials (`.git-credentials`)

## Development

### Installing Development Dependencies

```bash
uv pip install -e ".[dev,test]"
```

### Testing

Tests can be run using pytest.
If you're using [mcpo](https://github.com/open-webui/mcpo) you can start the server using e.g. the following command:
```bash
uvx mcpo --port 8000 -- uv run --directory /path/to/jupyter-interpreter-mcp jupyter-interpreter-mcp
```
For this, a configured `.env` file is required.
You can then test the MCP server endpoint at [http://localhost:8000/docs](http://localhost:8000/docs).

## License

MIT
