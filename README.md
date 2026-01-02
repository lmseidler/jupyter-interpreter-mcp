# Jupyter Interpreter MCP

A Jupyter-based MCP (Model Context Protocol) server for code interpretation. This server provides a persistent code execution environment similar to Jupyter notebooks, allowing you to execute Python code and maintain session state across multiple requests.

## Features

- Persistent code execution sessions (similar to Jupyter notebooks)
- Session management with unique session IDs
- Execute Python code and retrieve results
- Error handling and reporting
- MCP server interface for easy integration

## Requirements

- Python 3.10 or higher
- uv package manager

## Installation

### Production Install

Install the package using `uv`:

```bash
uv pip install .
```

### Development Install

For development, install in editable mode:

```bash
uv pip install -e .
```

This allows you to modify the source code and see changes immediately without reinstalling.

## Usage

### Using uvx (One-off Execution)

Run the MCP server without persistent installation:

```bash
uvx jupyter-interpreter-mcp
```

### Using Installed Command

After installation, run the server using the command-line entry point:

```bash
jupyter-interpreter-mcp
```

### Using Python Module

Run the server as a Python module:

```bash
python -m jupyter_interpreter_mcp
```

## Environment Variables

The server can be configured using environment variables. Create a `.env` file in the project root based on `.env.example`:

- `NOTEBOOKS_FOLDER`: (Optional) Path to the folder where notebook session files are stored. Defaults to `notebooks` directory next to the source code.

**Note**: Notebook storage will eventually be handled by a JupyterHub container in future versions.

## Version Management

Package versions are automatically generated from git tags using `setuptools-scm`. To create a new version:

1. Create a git tag following semantic versioning:
   ```bash
   git tag v0.1.0
   ```

2. The package version will automatically match the tag (e.g., `0.1.0`)

3. If no tags exist, a development version will be generated (e.g., `0.1.0.dev0+<git-hash>`)

## License

MIT
