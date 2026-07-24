"""
src/main.py
~~~~~~~~~~~
Master launcher — delegates all logic to src/interfaces/cli.py.

Usage:
    python -m src.main [OPTIONS]

See src/interfaces/cli.py for full option documentation.
"""

from __future__ import annotations

import sys

from src.interfaces.cli import main

if __name__ == "__main__":
    sys.exit(main())
