#!/usr/bin/env python3
"""Styx DR restore test harness (issue #15). See docs/operate/dr-restore-test.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from drtest.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
