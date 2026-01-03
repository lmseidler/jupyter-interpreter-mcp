# Jupyter Interpreter MCP

A remote Jupyter-based MCP (Model Context Protocol) server for code interpretation. This server connects to a remote Jupyter server (running in a Docker container or cloud instance) and provides a persistent, sandboxed code execution environment similar to Jupyter notebooks.

## Features

- Remote Jupyter kernel execution (sandboxed in Docker containers)
- Persistent code execution sessions with session IDs
- Session state stored in remote filesystem
- Execute Python code and retrieve results
- Error handling and reporting
- MCP server interface for easy integration
- Direct ZMQ connections for low-latency execution

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

Run a Jupyter container with the required port mappings:

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

### 2. Get Authentication Token

Retrieve the token from container logs:

```bash
docker logs jupyter-notebook 2>&1 | grep token=
```

Look for output like:
```
http://127.0.0.1:8888/lab?token=abc123def456...
```

Copy the token value (`abc123def456...`).

### 3. Configure Environment

Create a `.env` file in the project root (or in `src/jupyter_interpreter_mcp/`):

```bash
JUPYTER_BASE_URL=http://localhost:8889
JUPYTER_TOKEN=abc123def456...
NOTEBOOKS_FOLDER=/home/jovyan/notebooks
```

See `.env.example` for full configuration options and Docker setup instructions.

### 4. Install and Run

Install the MCP server:

```bash
uv pip install -e .
```

Run the server:

```bash
jupyter-interpreter-mcp
```

The server will validate the connection to Jupyter on startup and fail with a clear error message if the connection cannot be established.

## Installation

### Production Install

```bash
uv pip install .
```

### Development Install

```bash
uv pip install -e ".[dev,test]"
```

This installs the package in editable mode with development and testing dependencies.

## Environment Variables

All configuration is done via environment variables:

### Required

- `JUPYTER_BASE_URL`: URL of remote Jupyter server (default: `http://localhost:8888`)
- `JUPYTER_TOKEN`: Authentication token (preferred method)

**OR**

- `JUPYTER_USERNAME`: Username for basic auth
- `JUPYTER_PASSWORD`: Password for basic auth

**Note**: Standard Jupyter Server uses token authentication. Username/password requires custom Jupyter configuration.

### Optional

- `NOTEBOOKS_FOLDER`: Path to notebooks folder in remote container (default: `/home/jovyan/notebooks`)
- `ZMQ_PORT_RANGE_START`: Start of ZMQ port range (default: `50000`)
- `ZMQ_PORT_RANGE_END`: End of ZMQ port range (default: `50100`)

## Usage

### Using uvx (One-off Execution)

```bash
uvx jupyter-interpreter-mcp
```

### Using Installed Command

```bash
jupyter-interpreter-mcp
```

### Using Python Module

```bash
python -m jupyter_interpreter_mcp
```

## Troubleshooting

### Cannot connect to Jupyter server

```
Failed to connect to Jupyter server at http://localhost:8889: Connection refused
```

**Solutions:**
- Verify container is running: `docker ps`
- Check port mapping: `docker port jupyter-notebook`
- Test HTTP connection: `curl http://localhost:8889/api`

### Authentication failed

```
Authentication failed: 401 Unauthorized
```

**Solutions:**
- Verify token is correct: `docker logs jupyter-notebook 2>&1 | grep token=`
- Token may have changed if container was restarted
- Check token hasn't expired

### Timeout connecting to kernel

```
TimeoutError: Kernel did not respond within 10 seconds
```

**Solutions:**
- Ensure ZMQ ports are mapped: `-p 50000-50100:50000-50100`
- Check firewall rules allow connections to these ports
- Verify kernel is running: `docker exec jupyter-notebook jupyter kernel list`

### Files not persisting

If session files aren't persisting across restarts:
- Check `NOTEBOOKS_FOLDER` points to a path inside the container (`/home/jovyan/notebooks`)
- Consider mounting a volume: `docker run -v ./notebooks:/home/jovyan/notebooks ...`

## Development

### Installing Development Dependencies

```bash
uv pip install -e ".[dev,test]"
```

Development tools:
- `pre-commit` - Git hooks for code quality
- `black` - Code formatter
- `ruff` - Fast Python linter
- `mypy` - Static type checker
- `pyupgrade` - Python syntax modernizer

Testing tools:
- `pytest` - Testing framework
- `pytest-cov` - Coverage reporting
- `pytest-asyncio` - Async test support
- `pytest-mock` - Mocking support
- `testcontainers` - Docker container testing

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest test/unit/

# Integration tests (requires Docker)
pytest test/integration/

# With coverage
pytest --cov=jupyter_interpreter_mcp --cov-report=html
```

### Setting Up Pre-commit Hooks

```bash
pre-commit install
```

Hooks run automatically on commit and perform:
- File hygiene checks
- Code formatting with `black`
- Linting with `ruff`
- Type checking with `mypy`
- Python syntax upgrades

Run manually on all files:

```bash
pre-commit run --all-files
```

### Code Quality Checks

```bash
# Format code
black src/

# Lint and auto-fix
ruff check --fix src/

# Type check
mypy src/jupyter_interpreter_mcp
```

## Migration from Local Execution

Previous versions executed code locally using `KernelManager`. This version requires a remote Jupyter server.

**Breaking Changes:**
- Local kernel execution no longer supported
- Must provide `JUPYTER_BASE_URL` and authentication
- `NOTEBOOKS_FOLDER` now refers to path inside remote environment

**Migration Steps:**
1. Start Jupyter container with required ports
2. Get authentication token
3. Update `.env` file with remote configuration
4. Update `NOTEBOOKS_FOLDER` to container path (e.g., `/home/jovyan/notebooks`)

## Security Considerations

- **Sandboxing**: Code executes in isolated Docker container, not on host
- **Authentication**: Token or username/password authentication required
- **Network**: Use HTTPS for production (configure via `JUPYTER_BASE_URL`)
- **ZMQ Security**: Connections use HMAC-SHA256 signature verification
- **File Isolation**: All paths relative to container filesystem

## Advanced Configuration

### Custom Jupyter Images

Use your own Jupyter image with pre-installed packages:

```bash
docker run -d \
  --name jupyter-notebook \
  -p 8889:8888 \
  -p 50000-50100:50000-50100 \
  my-custom-jupyter-image:latest
```

### Cloud Deployment

For cloud-hosted Jupyter servers:

```bash
JUPYTER_BASE_URL=https://jupyter.example.com
JUPYTER_TOKEN=<token>
NOTEBOOKS_FOLDER=/home/jovyan/notebooks
```

Ensure ZMQ ports are accessible through firewalls and security groups.

### Volume Mounting

Persist notebooks across container restarts:

```bash
docker run -d \
  --name jupyter-notebook \
  -p 8889:8888 \
  -p 50000-50100:50000-50100 \
  -v $(pwd)/notebooks:/home/jovyan/notebooks \
  jupyter/minimal-notebook:latest
```

## License

MIT
