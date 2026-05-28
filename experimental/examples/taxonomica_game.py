#!/usr/bin/env python3
"""Compatibility launcher for the Taxonomica game.

Prefer running `python play.py` from the repository root.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from taxonomica.game.cli import main


if __name__ == "__main__":
    main(PROJECT_ROOT)
