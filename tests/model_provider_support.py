"""Load provider modules without executing the bot plugin's startup hooks."""

import importlib
import sys
import types
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin"
PACKAGE = "_hatsume_provider_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(PLUGIN)]
    sys.modules[PACKAGE] = package
config = importlib.import_module(f"{PACKAGE}.model_config")
commands = importlib.import_module(f"{PACKAGE}.model_commands")
