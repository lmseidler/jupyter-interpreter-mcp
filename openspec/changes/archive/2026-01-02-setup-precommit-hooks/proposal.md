# Change: Setup Pre-commit Hooks

## Why

The project currently lacks automated code quality enforcement despite having clear conventions defined in `project.md`. Developers can commit code that doesn't meet formatting, linting, or type-checking standards, leading to inconsistent code quality and potential issues discovered late in the development cycle.

According to `project.md`, the project requires:
- Code formatting with Black
- Linting with Ruff (with auto-fix)
- Type checking with mypy (strict mode with specific flags)
- Python syntax modernization with pyupgrade
- Multiple file validation hooks (TOML, YAML, trailing whitespace, etc.)

Without pre-commit hooks, these checks are manual and error-prone. Setting up the pre-commit framework ensures all code quality standards are automatically enforced before commits are finalized.

## What Changes

- Create `.pre-commit-config.yaml` with all hooks specified in `project.md`:
  - Basic file hygiene hooks (trailing-whitespace, end-of-file-fixer, etc.)
  - Python code quality hooks (ruff, black, pyupgrade, mypy)
  - File validation hooks (check-toml, check-yaml, etc.)
  - Security hooks (debug-statements, check-added-large-files)
- Add pre-commit as a development dependency in `pyproject.toml`
- Configure mypy with required strict flags in `pyproject.toml`
- Configure ruff with appropriate settings in `pyproject.toml`
- Update `.gitignore` to exclude pre-commit cache
- Create developer documentation for installing and using pre-commit hooks

## Impact

### Affected specs
- **NEW**: `code-quality` - Defines automated code quality enforcement requirements

### Affected code
- `.pre-commit-config.yaml` - **CREATED**: Pre-commit hook configuration
- `pyproject.toml` - **MODIFIED**: Add dev dependencies and tool configurations
- `.gitignore` - **MODIFIED**: Exclude pre-commit cache directory
- `README.md` - **MODIFIED**: Add development setup section with pre-commit instructions

### User-facing changes
- Developers must install pre-commit hooks: `pre-commit install`
- Code quality checks run automatically on `git commit`
- Failed checks prevent commits until issues are resolved
- Developers can run hooks manually: `pre-commit run --all-files`
- Auto-fixing tools (ruff, black) will modify files automatically when possible

### Breaking changes
None - this is development tooling setup that doesn't affect runtime behavior or public APIs.

### Dependencies
- Requires pre-commit framework to be installed
- Requires black, ruff, mypy, and pyupgrade to be available (handled by pre-commit)
- All existing code must pass quality checks or be fixed before hooks can be enforced
