# Project Context

## Purpose
An MCP (Model Context Protocol) server that provides sandboxed Python code execution capabilities via JupyterHub containers. The server is designed to be launched using `uvx` with a straightforward installation process via `uv` and minimal user configuration.

### Key Goals
- Provide secure, sandboxed Python code execution through JupyterHub containers
- Simple installation and setup process using `uv`
- Launch via `uvx` for easy distribution and usage
- Similar functionality to `https://github.com/akuadane/mcp-code-interpreter` but with fundamentally different setup and architecture

## Tech Stack
- **Language**: Python 3.x
- **Package Manager**: uv (for dependency management and distribution)
- **Launcher**: uvx (for running the MCP server)
- **Execution Environment**: JupyterHub container (sandboxed code execution)
- **Code Formatter**: black
- **Linter**: ruff
- **Type Checker**: mypy
- **Testing**: pytest
- **Pre-commit Hooks**: pre-commit framework with multiple tools

## Project Conventions

### Code Style
- **Formatter**: Black (default configuration)
- **Linter**: Ruff with auto-fix enabled
- **Python Version Upgrade**: pyupgrade for modern Python syntax
- **Import Sorting**: Handled by ruff
- **Line Length**: Follow black's defaults (88 characters)
- **Type Hints**: Required for all public APIs and functions
- **Docstrings**: Required for all public APIs and functions and in sphinx format

### Type Checking
- **Tool**: mypy with strict configuration
- **Required Args**:
  - `--explicit-package-bases`
  - `--check-untyped-defs`
- Type hints are mandatory for all public interfaces
- All code must pass mypy checks before commit

### Pre-commit Hooks
The following hooks run automatically on commit:
- **trailing-whitespace**: Remove trailing whitespace
- **end-of-file-fixer**: Ensure files end with newline
- **check-shebang-scripts-are-executable**: Validate executable scripts
- **check-toml**: Validate TOML syntax
- **check-yaml**: Validate YAML syntax
- **check-added-large-files**: Prevent committing files >10MB
- **debug-statements**: Catch debug statements before commit
- **ruff**: Lint and auto-fix Python code
- **black**: Format Python code
- **pyupgrade**: Upgrade Python syntax to modern patterns
- **mypy**: Type check all code

### Architecture Patterns
- **MCP Server**: Implements Model Context Protocol for code execution
- **Container-based Sandboxing**: JupyterHub container provides isolated execution environment
- **Separation of Concerns**:
  - MCP server handles protocol communication
  - JupyterHub container handles code execution
  - Clear boundary between server and execution environment

### Testing Strategy
- **Framework**: pytest
- **Coverage**: Aim for high test coverage on core functionality
- **Test Types**:
  - Unit tests for individual components
  - Integration tests for MCP server-JupyterHub interaction
  - End-to-end tests for full execution workflows
- All tests must pass before merging

### Git Workflow
- **Branching Strategy**: Feature branch workflow
  - Create a new branch for each feature or issue fix
  - Branch naming: `feature/<description>` or `fix/<description>`
  - Merge to main via pull requests
- **Commit Conventions**: Follow conventional commits format
  - `feat:` for new features
  - `fix:` for bug fixes
  - `docs:` for documentation changes
  - `test:` for test additions/changes
  - `refactor:` for code refactoring
  - `chore:` for maintenance tasks
- **Pre-commit Enforcement**: All pre-commit hooks must pass before pushing

## Domain Context

### MCP (Model Context Protocol)
- Protocol for enabling AI assistants to interact with external tools and services
- This server exposes Python code execution as an MCP capability
- Clients can send Python code for execution and receive results

### JupyterHub Container Sandboxing
- JupyterHub container provides isolated execution environment
- Prevents code execution from affecting host system
- Each execution session runs in controlled environment
- Security is critical - all user code is untrusted

### uvx Distribution Model
- Server is designed to be run via `uvx` for zero-install execution
- Users can run without manual installation: `uvx jupyter-interpreter-mcp`
- Dependencies managed by `uv` for fast, reliable installation

## Important Constraints

### Security Constraints
- All executed code must run in sandboxed JupyterHub container
- No direct host system access from executed code
- Input validation required for all code execution requests
- Resource limits should be enforced on execution environment

### Technical Constraints
- Must be compatible with `uvx` launcher
- Requires JupyterHub container to be running
- User configuration should be minimal but necessary
- Installation process must be straightforward using `uv`

### Compatibility
- Python 3.x required (specify minimum version in project config)
- Container runtime required for JupyterHub
- MCP protocol compliance required

## External Dependencies

### Required Services
- **JupyterHub Container**: Must be running and accessible for code execution
- Container runtime (Docker, Podman, etc.) to run JupyterHub

### Key Python Libraries
- MCP SDK/libraries for protocol implementation
- Jupyter client libraries for container communication
- HTTP client for container API communication
- Type stubs: pydantic, pytest, pandas-stubs, matplotlib, types-tabulate

### Development Tools
- uv: Package management and dependency resolution
- uvx: Server launcher
- pre-commit: Git hook management
- All tools specified in pre-commit configuration
