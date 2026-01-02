# Implementation Tasks

## 1. Package Configuration
- [x] 1.1 Create `pyproject.toml` with package metadata (name, description, license)
- [x] 1.2 Add dependency specifications (mcp, jupyter-client, ipykernel, python-dotenv)
- [x] 1.3 Configure setuptools-scm for dynamic versioning
- [x] 1.4 Define entry point: `jupyter-interpreter-mcp` → `jupyter_interpreter_mcp.server:main`
- [x] 1.5 Set minimum Python version requirement (>=3.10)

## 2. Code Fixes for Package Installation
- [x] 2.1 Fix import in `server.py`: `from notebook import Notebook` → `from jupyter_interpreter_mcp.notebook import Notebook`
- [x] 2.2 Fix syntax error in `server.py` line 17 (FastMCP initialization string)
- [x] 2.3 Fix import in `notebook.py`: `from jupyter_client import KernelManager` → `from jupyter_client.manager import KernelManager`
- [x] 2.4 Add `main()` function in `server.py` to wrap `mcp.run()`
- [x] 2.5 Update `if __name__ == '__main__'` block to call `main()`

## 3. Module Entry Point
- [x] 3.1 Create `src/jupyter_interpreter_mcp/__main__.py`
- [x] 3.2 Import and call `main()` from `server.py` in `__main__.py`

## 4. Notebooks Folder Configuration
- [x] 4.1 Update notebooks folder logic in `server.py` to handle missing env var gracefully
- [x] 4.2 Update notebooks folder logic in `notebook.py` to match `server.py`
- [x] 4.3 Add comment noting future JupyterHub container integration

## 5. Documentation and Examples
- [x] 5.1 Create `.env.example` with template environment variables
- [x] 5.2 Create `README.md` with project description
- [x] 5.3 Add installation instructions (development and production)
- [x] 5.4 Add usage examples (uvx, installed command, module execution)
- [x] 5.5 Document environment variables
- [x] 5.6 Add section on version management (git tags)

## 6. Version Management Setup
- [x] 6.1 Create initial git tag `v0.1.0` for setuptools-scm
- [x] 6.2 Verify version generation works (`python -c "import jupyter_interpreter_mcp; print(jupyter_interpreter_mcp.__version__)"`)

## 7. Testing and Validation
- [x] 7.1 Test editable install: `uv pip install -e .`
- [x] 7.2 Verify command is available: `which jupyter-interpreter-mcp`
- [x] 7.3 Test command execution: `jupyter-interpreter-mcp --help` or startup
- [x] 7.4 Test module execution: `python -m jupyter_interpreter_mcp`
- [x] 7.5 Test uvx execution: `uvx --from . jupyter-interpreter-mcp` (local test)
- [x] 7.6 Verify version is correctly set
- [ ] 7.7 Run pre-commit hooks if configured (black, ruff, mypy)

## Dependencies
- Tasks 2.x must complete before 7.x (code must be fixed before testing)
- Task 1.x must complete before 7.1 (pyproject.toml needed for installation)
- Task 6.1 should complete before 7.6 (git tag needed for version)
- Tasks 5.x can run in parallel with other implementation tasks

## Notes
- Do not implement JupyterHub container logic - that's future work
- Focus solely on making the package installable and runnable via uv/uvx
- Keep notebooks folder logic simple with sensible defaults for now
