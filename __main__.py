"""
CLI Entrypoint for `python -m openproject_mcp`.
"""

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
