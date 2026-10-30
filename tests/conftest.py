"""Test bootstrap: make ``lib/`` and ``thermopt_app/`` importable.

Nothing else: the app does not import Home Assistant, so the tests do not need
the Home Assistant test harness.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "lib"), str(ROOT / "thermopt_app")):
    if path not in sys.path:
        sys.path.insert(0, path)
