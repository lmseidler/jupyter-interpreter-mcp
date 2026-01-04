# Jupyter Interpreter MCP

A remote Jupyter-based MCP (Model Context Protocol) server for code interpretation. This server connects to a remote Jupyter server (running in a Docker container or cloud instance) and provides a persistent, sandboxed code execution environment similar to Jupyter notebooks. Supports both Python and bash command execution.

## Architecture

```
MCP Server → RemoteJupyterClient → Jupyter REST API → Remote Kernel
                                          ↓
                              WebSocket Connection
                                          ↓
                              Container Filesystem
```

All code executes within the remote Jupyter container, providing isolation and security. Session history files are stored in the container filesystem, not on the host. You can execute both Python code and bash commands (e.g., `ls`, `pwd`, `cat file.txt`).

## Requirements

- Python 3.10 or higher
- uv package manager
- Docker (for running Jupyter container)
- Network access to Jupyter server

## Quick Start

### 1. Start Jupyter Container

Run a Jupyter container with the required port mappings, e.g.:

```bash
docker run -d \
  --name jupyter-notebook \
  -p 8889:8888 \
  jupyter/minimal-notebook:latest
```

Port mappings:
- `8889:8888` - HTTP API access (mapped to 8889 on host to avoid conflicts)

### 2. Get Authentication Token

Create a new token for accessing the JupyterLab or use an existing token.

### 3. Configure Environment

Create a `.env` file in the project root:

```bash
JUPYTER_BASE_URL=http://localhost:8889
JUPYTER_TOKEN=abc123def456...
NOTEBOOKS_FOLDER=/home/jovyan/notebooks
```

See `.env.example` for full configuration options and Docker setup instructions.

### 4. Run the MCP server

TODO: Start the server using uvx:

```bash
uvx jupyter-interpreter-mcp
```

or to add it to e.g. Claude Code:

```json
{
  "mcpServers": {
    "jupyter-interpreter-mcp": {
      "command": "uvx",
      "args": [
        "jupyter-interpreter-mcp"
      ]
    }
  }
}
```

Currently you need to install it first:

```bash
uv pip install .
```

and then run it:

```bash
uv run jupyter-interpreter-mcp
```

The server will validate the connection to Jupyter on startup and fail with a clear error message if the connection cannot be established.

## Configuration

All configuration is done via environment variables:

### Required

- `JUPYTER_BASE_URL`: URL of remote Jupyter server (default: `http://localhost:8888`)
- `JUPYTER_TOKEN`: Authentication token

### Optional

- `NOTEBOOKS_FOLDER`: Path to notebooks folder in remote container (default: `/home/jovyan/notebooks`)

## Tools

TODO

## Development

### Installing Development Dependencies

```bash
uv pip install -e ".[dev,test]"
```

## Security Considerations

- **Sandboxing**: Code executes in isolated Docker container, not on host
- **Authentication**: Token authentication required
- **Network**: Use HTTPS for production (configure via `JUPYTER_BASE_URL`)
- **WebSocket Security**: Connections use token-based authentication
- **File Isolation**: All paths relative to container filesystem

## License

MIT
