#!/usr/bin/env python3
"""Launch Taxonomica from a source checkout."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from taxonomica.game.cli import main


if __name__ == "__main__":
    main(PROJECT_ROOT)
