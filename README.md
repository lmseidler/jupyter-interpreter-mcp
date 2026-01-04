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

TODO

## Development

### Installing Development Dependencies

```bash
uv pip install -e ".[dev,test]"
```

## License

MIT
