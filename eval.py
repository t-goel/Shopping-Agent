"""Run evaluation from a checkout without PYTHONPATH or an editable install."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = str(ROOT / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from shopping_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
