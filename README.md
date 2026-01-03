# Jupyter Interpreter MCP

A remote Jupyter-based MCP (Model Context Protocol) server for code interpretation. This server connects to a remote Jupyter server (running in a Docker container or cloud instance) and provides a persistent, sandboxed code execution environment similar to Jupyter notebooks.

## Architecture

```
MCP Server → RemoteJupyterClient → Jupyter REST API → Remote Kernel
                                          ↓
                              Direct ZMQ Connection
                                          ↓
                              Container Filesystem
```

All code executes within the remote Jupyter container, providing isolation and security. Session history files are stored in the container filesystem, not on the host.

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
  -p 50000-50100:50000-50100 \
  jupyter/minimal-notebook:latest
```

Port mappings:
- `8889:8888` - HTTP API access (mapped to 8889 on host to avoid conflicts)
- `50000-50100:50000-50100` - ZMQ ports for kernel communication (~20 concurrent kernels)

Alternatively, you can use `--network=host` in your `docker run` command to eliminate the need for mapping the 50xxx ports.
However, this will expose the Jupyter server to the host network, which may be a security risk.

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

Start the server using uvx:

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

The server will validate the connection to Jupyter on startup and fail with a clear error message if the connection cannot be established.

## Configuration

All configuration is done via environment variables:

### Required

- `JUPYTER_BASE_URL`: URL of remote Jupyter server (default: `http://localhost:8888`)
- `JUPYTER_TOKEN`: Authentication token (preferred method)

### Optional

- `NOTEBOOKS_FOLDER`: Path to notebooks folder in remote container (default: `/home/jovyan/notebooks`)
- `ZMQ_PORT_RANGE_START`: Start of ZMQ port range (default: `50000`)
- `ZMQ_PORT_RANGE_END`: End of ZMQ port range (default: `50100`)

## Tools

TODO

## Development

### Installing Development Dependencies

```bash
uv pip install -e ".[dev,test]"
```

## Security Considerations

- **Sandboxing**: Code executes in isolated Docker container, not on host
- **Authentication**: Token or username/password authentication required
- **Network**: Use HTTPS for production (configure via `JUPYTER_BASE_URL`)
- **ZMQ Security**: Connections use HMAC-SHA256 signature verification
- **File Isolation**: All paths relative to container filesystem

## License

MIT
