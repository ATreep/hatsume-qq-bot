"""Bot identity and behavioral constants; model configuration lives in YAML."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env.prod")

def _get_int_env(name: str) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else 0


def _get_float_env(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    try:
        return float(value) if value else default
    except ValueError:
        return default


SANDBOX_COMPUTER_USE_MAX_ITERATIONS: int = 30


# ---------------------------------------------------------------------------
# Bot identity
# ---------------------------------------------------------------------------
BOT_QQ_ID: int = _get_int_env("BOT_QQ_ID")
BOT_DISPLAY_NAME: str = "初芽"
AGENT_QQ_EMAIL = os.getenv("AGENT_QQ_EMAIL", "")
ADMIN_QQ_ID: str = os.getenv("ADMIN_QQ_ID", "")
GITHUB_ACCOUNT = os.getenv("GITHUB_ACCOUNT", "")
HUGGINGFACE_ACCOUNT = os.getenv("HUGGINGFACE_ACCOUNT", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

# Non-model service credentials remain deployment settings.
PIXELS_API_KEY: str = os.environ.get("PIXELS_API_KEY", "")
PEXELS_BASE_URL = "https://api.pexels.com"

# ---------------------------------------------------------------------------
# Behavioral constants
# ---------------------------------------------------------------------------
USER_INPUT_CONFIRM_DURING_TIME: int = 7
CONTEXT_QUEUE_LEN: int = 60
CONTEXT_QUEUE_OVERLAP_LEN: int = 7
GENERATE_IMAGE_RATE_LIMIT_SECONDS: int = 60
IMAGE_MAX_SIZE_BYTES: int = 9 * 1024 * 1024
IMAGE_MAX_PIXELS: int = 36_000_000
MESSAGE_MAX_LENGTH: int = 2000
REPLY_MAX_LENGTH: int = 1500
MAX_FORWARD_DEPTH: int = 3
MAX_REAL_AT_SEGMENTS: int = 3
FORWARD_API_TIMEOUT_SECONDS: int = 10
LONG_MSG_THRESHOLD: int = 500
POKE_GROUP_WHITELIST: frozenset[int] = frozenset({})

# ---------------------------------------------------------------------------
# Chat tone (runtime personality layer)
# ---------------------------------------------------------------------------
LIVELY_TONE_ENABLED: bool = True

# ---------------------------------------------------------------------------
# Todo list
# ---------------------------------------------------------------------------
TODO_MAX_ITEMS: int = 15
TODO_EXPIRY_SECONDS: int = 72 * 60 * 60

# ---------------------------------------------------------------------------
# Auto response timer
# ---------------------------------------------------------------------------
AUTO_RESPONSE_GROUP_BLACKLIST: frozenset[int] = frozenset(
    {376347217, 579996918, 902317662}
)
AUTO_RESPONSE_MIN_INTERVAL_MINUTES: int = 180
AUTO_RESPONSE_MAX_INTERVAL_MINUTES: int = 360
AUTO_RESPONSE_QUIET_START_HOUR: int = 2
AUTO_RESPONSE_QUIET_END_HOUR: int = 6
# ---------------------------------------------------------------------------
# Memory constants
# ---------------------------------------------------------------------------
MAX_MEMORY_LIMIT: int = 50
SCORE_THRESHOLD: float = 0.1
EMBEDDING_SIMILARITY_THRESHOLD: float = 0.4
EMBEDDING_WEIGHT: float = 0.5
MEMORY_EXPIRY_DAYS: int = 150

# ---------------------------------------------------------------------------
# Docker / shell
# ---------------------------------------------------------------------------
DOCKER_ENV_PATH: Path = Path(
    os.getenv("DOCKER_ENV_PATH", str(Path(__file__).resolve().parent / "virtual"))
).expanduser()
SHELL_TIMEOUT: int = 300

# ---------------------------------------------------------------------------
# Timer module
# ---------------------------------------------------------------------------
TIMER_TOLERANCE_MINUTES: int = 5
TIMER_MAX_FREQUENCY_POINTS: int = 5
TIMER_MAX_EXACT_POINTS: int = 10

# ---------------------------------------------------------------------------
# Skill module
# ---------------------------------------------------------------------------
SKILLS_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "hatsume-plugin" / "skills"
COMMON_SKILLS_DIR: Path = SKILLS_DIR
GROUP_SKILLS_DIR: Path = SKILLS_DIR / "groups"

# MCP server definitions are JSON files, isolated by QQ group in the same
# fashion as group-local Skills.  The directory is intentionally separate from
# the Skill tree so MCP credentials and lifecycle state have an independent
# ownership boundary.
MCP_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "hatsume-plugin" / "mcp"
MCP_GROUPS_DIR: Path = MCP_DIR / "groups"

# ---------------------------------------------------------------------------
# Hook module
# ---------------------------------------------------------------------------
HOOKS_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "hatsume-plugin" / "hooks"
HOOK_MAX_ACTIVE_PER_GROUP: int = 5
HOOK_MIN_INTERVAL_SECONDS: int = 300
HOOK_DEFAULT_INTERVAL_SECONDS: int = 900
HOOK_DEFAULT_TIMEOUT_SECONDS: int = 15
HOOK_MAX_TIMEOUT_SECONDS: int = 60

CONTAINER_NAME_BASE = "hatsume-space"
