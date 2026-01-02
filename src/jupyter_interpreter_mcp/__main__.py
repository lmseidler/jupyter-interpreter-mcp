"""Module entry point for jupyter-interpreter-mcp."""

import sys
from jupyter_interpreter_mcp.server import main

if __name__ == "__main__":
    # Handle --version flag
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        from importlib.metadata import version

        print(f"jupyter-interpreter-mcp {version('jupyter-interpreter-mcp')}")
        sys.exit(0)

    main()
