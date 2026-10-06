"""Plugin configuration: environment, model names, behavioral constants."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Literal
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env.prod")

TYPESAFE_API_KEY: str = os.getenv("TYPESAFE_API_KEY", "") or os.getenv("DREX_API_KEY", "")
TYPESAFE_BASE_URL: str = os.getenv("TYPESAFE_BASE_URL", "https://drex.nace.ai").rstrip("/")
TYPESAFE_DEFAULT_MODEL: str = os.getenv("TYPESAFE_DEFAULT_MODEL", "drex-latest")


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

# ---------------------------------------------------------------------------
# API keys — read from environment
# ---------------------------------------------------------------------------
ARK_PLAN_API_KEY: str = os.environ.get("ARK_PLAN_API_KEY", "")
ARK_API_KEY: str = os.environ.get("ARK_API_KEY", "")
SILICONFLOW_API_KEY: str = os.environ.get("SILICONFLOW_API_KEY", "")
# OPENCODE_API_KEY: str = os.environ.get("OPENCODE_API_KEY", "")
OPENCODE_API_KEY: str = "public"
KEGEAI_API_KEY = os.environ.get("KEGEAI_API_KEY", "")
ZHTH_API_KEY = os.environ.get("ZHTH_API_KEY", "")
DS_API_KEY = os.environ.get("DS_API_KEY", "")
AR_API_KET = os.environ.get("AR_API_KEY", "")
RUOLI_API_KEY = os.environ.get("ROULI_API_KEY", "")
PIXELS_API_KEY: str = os.environ.get("PIXELS_API_KEY", "")
WAWAPI_API_KEY: str = os.environ.get("WAWAPI_API_KEY", "")
WAWAPI_IMAGE_API_KEY: str = os.environ.get("WAWAPI_IMAGE_API_KEY", "")
ALI_API_KEY: str = os.environ.get("ALI_API_KEY", "")
MI_API_KEY: str = os.environ.get("MI_API_KEY", "")
SENSENOVA_API_KEY: str = os.environ.get("SENSENOVA_API_KEY", "")
HIYO_API_KEY: str = os.environ.get("HIYO_API_KEY", default="")
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")

# ---------------------------------------------------------------------------
# External service URLs
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Base URLs (No `v1` suffix)
# ---------------------------------------------------------------------------

## Attention: add `/v3` to volc and volc_plan baseurl.
VOLCENGINE_BASE_URL: str = "https://ark.cn-beijing.volces.com/api"
VOLCENGINE_PLAN_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/plan"
SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn"
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen"
KEGEAI_BASE_URL = "https://ai.kegeai.top"
ZHTH_BASE_URL = "https://api.zhehentiaohe.cn"
DS_BASE_URL = "https://api.deepseek.com"
AR_BASE_URL = "https://agentrouter.org"
RUOLI_BASE_URL = "https://ruoli.dev"
PEXELS_BASE_URL = "https://api.pexels.com"
WAWAPI_BASE_URL = "https://wawapii.com"
ALI_BASE_URL = "https://ws-1h26pj40tzf8hqys.cn-beijing.maas.aliyuncs.com/compatible-mode"
MI_BASE_URL = "https://api.xiaomimimo.com"
SENSENOVA_BASE_URL: str = "https://token.sensenova.cn/v1"
HIYO_BASE_URL: str = "https://codex.hiyo.top"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/alpha"


# ---------------------------------------------------------------------------
# Model names
# ---------------------------------------------------------------------------
DOUBAO_2_LITE: str = "doubao-seed-2-0-lite"
DOUBAO_2_MINI: str = "doubao-seed-2-0-mini"
DEEPSEEK_FLASH = "deepseek-flash"
MIMO_2_6_FLASH = "mimo-v2.6-flash"
DEEPSEEK_V4_1_FLASH = "deepseek-v4.1-flash"
SEEDREAM_5_0_LITE: str = "doubao-seedream-5.0-lite"
SEEDREAM_4_0 = "doubao-seedream-4-0-250828"
SEEDANCE_1_5: str = "doubao-seedance-1-5-pro-251215"
SEEDANCE_1_0: str = "doubao-seedance-1-0-pro-250528"
GPT_IMAGE_2 = "gpt-image-2:stable"
GPT_6_LUNA = "gpt-6-luna"
GPT_5_5 = "gpt-5.5"
GEMINI_3_8_FLASH = "gemini-3.8-flash"
GROK_4_6 = "grok-4.6"
GROK_IMAGINE_IMAGE = "grok-imagine-image:stable"
LAGUNA_S_2_1_FREE = "laguna-s-2.1-free"
QWEN_3_7_FLASH = "qwen3.7-flash"
QWEN_3_8_FLASH = "qwen3.8-flash"
JEV_1_13 = "jev-1.13"
SENSENOVA_U1_5_FAST: str = "sensenova-u1.5-fast"
SENSENOVA_U1_5_LITE: str = "sensenova-u1.5-lite"
MERCURY_DECISION = "inception/mercury-decide:free"



ADVANCE_MODEL_NAME: str = GPT_6_LUNA
LITE_MODEL_NAME: str =  GPT_6_LUNA
CODING_MODEL_NAME: str = GPT_6_LUNA


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
EMBEDDING_MODEL: str = "BAAI/bge-m3"

# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
PROVIDER: Literal["volc", "volc_plan", "kege", "zhth", "ar", "ruoli", "ds", "waw", "ali", "mi", "hiyo", "zen"] = "hiyo"

def get_base_url(
    provider: Literal["volc", "volc_plan", "sf", "kege", "zhth", "ar", "ruoli", "ds", "waw", "ali", "mi", "hiyo", "zen"] = PROVIDER,
) -> str:
    match provider:
        case "volc_plan":
            return VOLCENGINE_PLAN_BASE_URL
        case "volc":
            return VOLCENGINE_BASE_URL
        case "sf":
            return SILICONFLOW_BASE_URL
        case "kege":
            return KEGEAI_BASE_URL
        case "zhth":
            return ZHTH_BASE_URL
        case "ar":
            return AR_BASE_URL
        case "ruoli":
            return RUOLI_BASE_URL
        case "ds":
            return DS_BASE_URL
        case "waw":
            return WAWAPI_BASE_URL
        case "ali":
            return ALI_BASE_URL
        case "mi":
            return MI_BASE_URL
        case "hiyo":
            return HIYO_BASE_URL
        case "zen":
            return OPENCODE_ZEN_BASE_URL

def get_api_key(
    provider: Literal["volc", "volc_plan", "sf", "kege", "zhth", "ar", "ruoli", "ds", "waw", "ali", "mi", "hiyo", "zen"] = PROVIDER,
) -> Callable[[], str]:
    match provider:
        case "volc_plan":
            return lambda: ARK_PLAN_API_KEY
        case "volc":
            return lambda: ARK_API_KEY
        case "sf":
            return lambda: SILICONFLOW_API_KEY
        case "kege":
            return lambda: KEGEAI_API_KEY
        case "zhth":
            return lambda: ZHTH_API_KEY
        case "ar":
            return lambda: AR_API_KET
        case "ruoli":
            return lambda: RUOLI_API_KEY
        case "ds":
            return lambda: DS_API_KEY
        case "waw":
            return lambda: WAWAPI_API_KEY
        case "ali":
            return lambda: ALI_API_KEY
        case "mi":
            return lambda: MI_API_KEY
        case "hiyo":
            return lambda: HIYO_API_KEY
        case "zen":
            return lambda: OPENCODE_API_KEY

# ---------------------------------------------------------------------------
# Behavioral constants
# ---------------------------------------------------------------------------
USER_INPUT_CONFIRM_DURING_TIME: int = 7
CONTEXT_QUEUE_LEN: int = 60
CONTEXT_QUEUE_OVERLAP_LEN: int = 7
VIDEO_RATE_LIMIT_SECONDS: int = 60
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
