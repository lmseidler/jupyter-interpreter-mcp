# code-quality Specification

## Purpose
TBD - created by archiving change setup-precommit-hooks. Update Purpose after archive.
## Requirements
### Requirement: Pre-commit Framework Configuration
The project SHALL use the pre-commit framework to automatically enforce code quality standards before commits are finalized.

#### Scenario: Pre-commit config file exists
- **WHEN** a developer clones the repository
- **THEN** a `.pre-commit-config.yaml` file SHALL be present in the project root
- **AND** the file SHALL define all required hooks as specified in project conventions

#### Scenario: Hooks are installable
- **WHEN** a developer runs `pre-commit install`
- **THEN** the pre-commit hooks SHALL be installed to `.git/hooks/pre-commit`
- **AND** the installation SHALL complete without errors

### Requirement: Code Formatting Enforcement
The project SHALL automatically format Python code using Black before commits.

#### Scenario: Black formatting hook runs
- **WHEN** a developer commits Python files
- **THEN** the Black hook SHALL automatically format the code
- **AND** the commit SHALL proceed if no changes are needed
- **AND** the commit SHALL fail if files are reformatted, requiring the developer to stage the changes

#### Scenario: Black uses default configuration
- **WHEN** Black formats code
- **THEN** it SHALL use the default line length of 88 characters
- **AND** it SHALL use Black's standard formatting rules

### Requirement: Code Linting Enforcement
The project SHALL automatically lint and fix Python code using Ruff before commits.

#### Scenario: Ruff linting hook runs
- **WHEN** a developer commits Python files
- **THEN** the Ruff hook SHALL check for linting issues
- **AND** it SHALL automatically fix issues when possible
- **AND** the commit SHALL fail if unfixable issues remain

#### Scenario: Ruff configuration is specified
- **WHEN** Ruff runs
- **THEN** it SHALL use the configuration from `pyproject.toml`
- **AND** it SHALL target the minimum Python version (3.10+)
- **AND** it SHALL have auto-fix enabled

### Requirement: Type Checking Enforcement
The project SHALL enforce type checking using mypy with strict configuration before commits.

#### Scenario: Mypy type checking hook runs
- **WHEN** a developer commits Python files
- **THEN** the mypy hook SHALL check for type errors
- **AND** the commit SHALL fail if type errors are found
- **AND** mypy SHALL use strict mode with required flags

#### Scenario: Mypy uses required flags
- **WHEN** mypy runs via pre-commit
- **THEN** it SHALL use the `--explicit-package-bases` flag
- **AND** it SHALL use the `--check-untyped-defs` flag
- **AND** it SHALL use configuration from `pyproject.toml`

### Requirement: Python Syntax Modernization
The project SHALL automatically upgrade Python syntax to modern patterns using pyupgrade before commits.

#### Scenario: Pyupgrade hook runs
- **WHEN** a developer commits Python files
- **THEN** the pyupgrade hook SHALL modernize syntax patterns
- **AND** it SHALL target Python 3.10+ syntax
- **AND** the commit SHALL fail if files are modified, requiring the developer to stage the changes

### Requirement: File Hygiene Enforcement
The project SHALL enforce basic file hygiene standards before commits.

#### Scenario: Trailing whitespace is removed
- **WHEN** a developer commits any text file
- **THEN** the trailing-whitespace hook SHALL remove trailing whitespace
- **AND** the commit SHALL fail if changes are made, requiring restaging

#### Scenario: Files end with newline
- **WHEN** a developer commits any text file
- **THEN** the end-of-file-fixer hook SHALL ensure the file ends with exactly one newline
- **AND** the commit SHALL fail if changes are made, requiring restaging

#### Scenario: Shebang scripts are executable
- **WHEN** a developer commits a file with a shebang
- **THEN** the check-shebang-scripts-are-executable hook SHALL verify it has executable permissions
- **AND** the commit SHALL fail if the file is not executable

### Requirement: File Format Validation
The project SHALL validate file formats for configuration files before commits.

#### Scenario: TOML files are validated
- **WHEN** a developer commits TOML files
- **THEN** the check-toml hook SHALL validate TOML syntax
- **AND** the commit SHALL fail if syntax errors are found

#### Scenario: YAML files are validated
- **WHEN** a developer commits YAML files
- **THEN** the check-yaml hook SHALL validate YAML syntax
- **AND** the commit SHALL fail if syntax errors are found

### Requirement: Large File Prevention
The project SHALL prevent accidentally committing large files.

#### Scenario: Large files are blocked
- **WHEN** a developer tries to commit a file larger than 10MB
- **THEN** the check-added-large-files hook SHALL block the commit
- **AND** the developer SHALL receive an error message about the file size

### Requirement: Debug Statement Detection
The project SHALL detect and prevent committing debug statements.

#### Scenario: Debug statements are caught
- **WHEN** a developer commits Python files containing debug statements
- **THEN** the debug-statements hook SHALL detect them
- **AND** the commit SHALL fail with information about which statements were found

### Requirement: Development Dependencies
The project SHALL provide pre-commit as an optional development dependency.

#### Scenario: Dev dependencies are installable
- **WHEN** a developer runs `uv pip install -e ".[dev]"`
- **THEN** pre-commit SHALL be installed
- **AND** all other development tools SHALL be available

#### Scenario: Dev dependencies are documented
- **WHEN** a developer reads `pyproject.toml`
- **THEN** the `[project.optional-dependencies]` section SHALL list all dev dependencies
- **AND** it SHALL include pre-commit and any other required development tools

### Requirement: Tool Configuration in pyproject.toml
The project SHALL centralize tool configuration in `pyproject.toml`.

#### Scenario: Ruff configuration exists
- **WHEN** Ruff runs
- **THEN** it SHALL read configuration from `[tool.ruff]` in `pyproject.toml`
- **AND** it SHALL read linting rules from `[tool.ruff.lint]`

#### Scenario: Mypy configuration exists
- **WHEN** mypy runs
- **THEN** it SHALL read configuration from `[tool.mypy]` in `pyproject.toml`
- **AND** the configuration SHALL include all required strict settings

#### Scenario: Black configuration exists if needed
- **WHEN** Black runs
- **THEN** it SHALL use default configuration OR read from `[tool.black]` if customization is needed

### Requirement: Pre-commit Documentation
The project SHALL provide clear documentation for setting up and using pre-commit hooks.

#### Scenario: README includes development setup
- **WHEN** a developer reads the README.md
- **THEN** it SHALL include a "Development Setup" section
- **AND** it SHALL document installing development dependencies
- **AND** it SHALL document installing pre-commit hooks
- **AND** it SHALL document running hooks manually

#### Scenario: README includes troubleshooting
- **WHEN** a developer encounters pre-commit issues
- **THEN** the README SHALL provide troubleshooting guidance
- **AND** it SHALL document the `--no-verify` bypass option
- **AND** it SHALL explain when bypassing hooks is appropriate

### Requirement: Git Configuration
The project SHALL properly configure git to work with pre-commit.

#### Scenario: Pre-commit cache is gitignored
- **WHEN** pre-commit runs and creates cache files
- **THEN** the `.pre-commit-cache/` directory SHALL be listed in `.gitignore`
- **AND** cache files SHALL not be committed to version control

#### Scenario: Pre-commit config is version controlled
- **WHEN** developers clone the repository
- **THEN** the `.pre-commit-config.yaml` file SHALL be present
- **AND** it SHALL be tracked in version control
