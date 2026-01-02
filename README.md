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

## Development Setup

### Installing Development Dependencies

To work on this project, you'll need to install the development dependencies:

```bash
uv pip install -e ".[dev]"
```

This installs the package in editable mode along with development tools including:
- `pre-commit` - Git hooks for code quality
- `black` - Code formatter
- `ruff` - Fast Python linter
- `mypy` - Static type checker
- `pyupgrade` - Python syntax modernizer

### Setting Up Pre-commit Hooks

Pre-commit hooks automatically check your code quality before each commit. To install them:

```bash
pre-commit install
```

Once installed, the hooks will run automatically on `git commit`. The hooks perform:
- File hygiene checks (trailing whitespace, end-of-file fixes)
- File validation (TOML, YAML syntax)
- Large file detection (warns on files >10MB)
- Debug statement detection
- Code formatting with `black`
- Linting with `ruff` (with auto-fix)
- Python syntax upgrades with `pyupgrade` (Python 3.10+)
- Type checking with `mypy`

### Running Code Quality Checks Manually

You can run all pre-commit hooks manually on all files:

```bash
pre-commit run --all-files
```

Or run individual tools:

```bash
# Format code with black
black src/

# Lint and auto-fix with ruff
ruff check --fix src/

# Upgrade Python syntax
pyupgrade --py310-plus src/**/*.py

# Type check with mypy
mypy src/jupyter_interpreter_mcp
```

## License

MIT
