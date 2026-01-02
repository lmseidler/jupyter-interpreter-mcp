# Change: Setup uv-based Packaging and Distribution

## Why

The project currently lacks proper Python package configuration, making it impossible to install or distribute via `uv` or run with `uvx`. Users cannot execute the MCP server without manually running Python files directly. We need to establish the foundational packaging infrastructure to enable the distribution model specified in `project.md`.

**Note**: Notebook storage will eventually be handled by a JupyterHub container (future work). This change focuses solely on making the package installable and runnable with `uv`/`uvx`.

## What Changes

- Add `pyproject.toml` with package metadata, dependencies, and entry point configuration
- Configure `setuptools-scm` for automatic version management from git tags
- Fix module imports to work when package is installed (relative imports)
- Fix syntax error in `server.py` (malformed FastMCP initialization string)
- Add `__main__.py` to enable `python -m jupyter_interpreter_mcp` execution
- Create `.env.example` to document environment variables for future use
- Create `README.md` with installation and usage instructions
- Update notebooks folder path logic to use sensible defaults (prepare for future JupyterHub integration)
- Add MIT license metadata to package configuration

## Impact

### Affected specs
- **NEW**: `packaging` - Defines package structure, dependencies, and distribution requirements

### Affected code
- `pyproject.toml` - **CREATED**: Package configuration and build system
- `src/jupyter-interpreter-mcp/server.py` - **MODIFIED**: Fix imports and syntax, add main() entry point
- `src/jupyter-interpreter-mcp/notebook.py` - **MODIFIED**: Fix imports for installed package
- `src/jupyter-interpreter-mcp/__main__.py` - **CREATED**: Module execution entry point
- `.env.example` - **CREATED**: Environment variable template
- `README.md` - **CREATED**: User documentation

### User-facing changes
- Users can install with: `uv pip install -e .` (development) or `uv pip install .` (production)
- Users can run with: `uvx jupyter-interpreter-mcp`
- Package version automatically derived from git tags via `setuptools-scm`
- Command `jupyter-interpreter-mcp` available after installation

### Breaking changes
None - this is the initial packaging setup.

### Dependencies
- Requires git tags for version generation (e.g., `v0.1.0`)
- No new external dependencies beyond what's already installed
