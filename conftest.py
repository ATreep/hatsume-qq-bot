"""Pytest conftest: add plugin directory to sys.path so imports work."""

import sys
from pathlib import Path

_plugin_dir = Path(__file__).resolve().parent / "hatsume" / "plugins" / "hatsume-plugin"
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))
