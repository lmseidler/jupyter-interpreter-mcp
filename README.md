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
uvx jupyter-interpreter-mcp --jupyter-base-url http://localhost:8889 --jupyter-token abc123def456... --notebooks-folder /home/jovyan/notebooks
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
        "--notebooks-folder",
        "/home/jovyan/notebooks"
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
NOTEBOOKS_FOLDER=/home/jovyan/notebooks
```

See `.env.example` for full configuration options and Docker setup instructions.

You can then install and run the server using uv:

```bash
uv pip install .
uv run jupyter-interpreter-mcp
```

---

The server will validate the connection to Jupyter on startup and fail with a clear error message if the connection cannot be established.

## Tools

### execute_code

Executes code (Python or bash) within a persistent session, retaining past results (e.g., variables, imports). Similar to a Jupyter notebook.

**Parameters:**
- `code` (string, required): The code to execute (Python or bash commands)
- `session_id` (integer, optional): A unique identifier used to associate multiple code execution requests with the same logical session. If this is the first request, you may omit it or set it to 0. The system will generate and return a new session_id, which should be reused in follow-up requests to maintain continuity within the same session.

**Returns:**
A dictionary containing:
- `result` (list of strings): Output from the code execution
- `error` (list of strings): Any errors that occurred during execution
- `session_id` (integer): The session ID to use for subsequent requests

**Example usage:**
```python
# First execution - creates a new session
result = execute_code(code="x = 42\nprint(x)")
# Returns: {"result": ["42"], "error": [], "session_id": 1704380400}

# Subsequent execution - reuses the session
result = execute_code(code="print(x * 2)", session_id=1704380400)
# Returns: {"result": ["84"], "error": [], "session_id": 1704380400}

# Bash commands
result = execute_code(code="ls -la", session_id=1704380400)
```

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
