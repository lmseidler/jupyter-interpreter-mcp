# packaging Specification

## Purpose
TBD - created by archiving change setup-uv-packaging. Update Purpose after archive.
## Requirements
### Requirement: Package Metadata Configuration
The package SHALL be configured with standard Python packaging metadata including name, version, description, license, and minimum Python version requirements.

#### Scenario: Package metadata is properly defined
- **WHEN** a user inspects the package configuration
- **THEN** the package name SHALL be "jupyter-interpreter-mcp"
- **AND** the license SHALL be "MIT"
- **AND** the minimum Python version SHALL be 3.10 or higher
- **AND** the description SHALL clearly state it is a Jupyter-based MCP server for code interpretation

### Requirement: Dynamic Version Management
The package version SHALL be automatically derived from git tags using setuptools-scm for consistent version tracking.

#### Scenario: Version from git tag
- **WHEN** a git tag following semver format (e.g., `v0.1.0`) exists
- **THEN** the package version SHALL match the tag (e.g., `0.1.0`)

#### Scenario: Version without git tag
- **WHEN** no git tags exist
- **THEN** the package version SHALL be a development version (e.g., `0.1.0.dev0+<git-hash>`)

### Requirement: Dependency Declaration
The package SHALL declare all required runtime dependencies with appropriate version constraints.

#### Scenario: Core dependencies specified
- **WHEN** the package is installed
- **THEN** the following dependencies SHALL be automatically installed:
  - `mcp` (version >= 1.0.0)
  - `jupyter-client` (version >= 8.0.0)
  - `ipykernel` (version >= 7.0.0)
  - `python-dotenv` (version >= 1.0.0)

### Requirement: Command-Line Entry Point
The package SHALL provide a `jupyter-interpreter-mcp` command-line entry point that launches the MCP server.

#### Scenario: Command available after installation
- **WHEN** a user installs the package with `uv pip install .`
- **THEN** the `jupyter-interpreter-mcp` command SHALL be available in the environment
- **AND** executing the command SHALL start the MCP server

#### Scenario: Entry point references correct module
- **WHEN** the `jupyter-interpreter-mcp` command is invoked
- **THEN** it SHALL call the `main()` function from `jupyter_interpreter_mcp.server`

### Requirement: Module Execution Support
The package SHALL support execution as a Python module using `python -m jupyter_interpreter_mcp`.

#### Scenario: Module execution starts server
- **WHEN** a user runs `python -m jupyter_interpreter_mcp`
- **THEN** the MCP server SHALL start
- **AND** the behavior SHALL be identical to using the command-line entry point

### Requirement: UVX Compatibility
The package SHALL be executable via `uvx` for one-off or temporary installations without persistent installation.

#### Scenario: UVX execution
- **WHEN** a user runs `uvx jupyter-interpreter-mcp`
- **THEN** the package SHALL be temporarily installed and executed
- **AND** the MCP server SHALL start successfully

### Requirement: Editable Development Installation
The package SHALL support editable installation for development workflows using `uv pip install -e .`.

#### Scenario: Editable install reflects code changes
- **WHEN** a developer installs with `uv pip install -e .`
- **AND** modifies source code
- **THEN** the changes SHALL be immediately available without reinstalling
- **AND** the `jupyter-interpreter-mcp` command SHALL execute the modified code

### Requirement: Module Import Structure
The package SHALL use proper relative imports to ensure it functions correctly when installed as a package.

#### Scenario: Cross-module imports work when installed
- **WHEN** the package is installed (not run from source directory)
- **THEN** `server.py` SHALL successfully import from `notebook.py`
- **AND** all module imports SHALL use the `jupyter_interpreter_mcp` package namespace

### Requirement: Environment Variable Documentation
The package SHALL provide an `.env.example` file documenting available environment variables for future configuration.

#### Scenario: Example file exists
- **WHEN** a user clones the repository
- **THEN** a `.env.example` file SHALL be present
- **AND** it SHALL contain commented examples of environment variables
- **AND** it SHALL include placeholder for `NOTEBOOKS_FOLDER` (for future use)

### Requirement: Installation Documentation
The package SHALL include comprehensive README.md documentation covering installation, usage, and version management.

#### Scenario: README includes installation methods
- **WHEN** a user reads the README.md
- **THEN** it SHALL document installation via `uv pip install .` (production)
- **AND** it SHALL document installation via `uv pip install -e .` (development)
- **AND** it SHALL document execution via `uvx jupyter-interpreter-mcp` (one-off)
- **AND** it SHALL document module execution via `python -m jupyter_interpreter_mcp`

#### Scenario: README documents version management
- **WHEN** a user reads the README.md
- **THEN** it SHALL explain how versions are generated from git tags
- **AND** it SHALL provide examples of creating version tags
- **AND** it SHALL explain the tag format (e.g., `v0.1.0`)

### Requirement: Build System Configuration
The package SHALL use setuptools as the build backend with proper configuration for setuptools-scm integration.

#### Scenario: Build system properly configured
- **WHEN** a user builds the package
- **THEN** setuptools SHALL be used as the build backend
- **AND** setuptools-scm SHALL be listed as a build dependency
- **AND** the build SHALL complete successfully
