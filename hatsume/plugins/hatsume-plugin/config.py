"""Plugin configuration: environment, model names, behavioral constants."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Literal
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env.prod")


def _get_int_env(name: str) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else 0


# ---------------------------------------------------------------------------
# Bot identity
# ---------------------------------------------------------------------------
BOT_QQ_ID: int = _get_int_env("BOT_QQ_ID")
AGENT_QQ_EMAIL = os.getenv("AGENT_QQ_EMAIL", "")
ADMIN_QQ_ID: str = os.getenv("ADMIN_QQ_ID", "")
GITHUB_ACCOUNT = os.getenv("GITHUB_ACCOUNT", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "ATreep/hatsume-qq-bot")

# ---------------------------------------------------------------------------
# API keys — read from environment
# ---------------------------------------------------------------------------
ARK_PLAN_API_KEY: str = os.environ.get("ARK_PLAN_API_KEY", "")
ARK_API_KEY: str = os.environ.get("ARK_API_KEY", "")
SILICONFLOW_API_KEY: str = os.environ.get("SILICONFLOW_API_KEY", "")
OPENCODE_API_KEY: str = os.environ.get("OPENCODE_API_KEY", "")
KEGEAI_API_KEY = os.environ.get("KEGEAI_API_KEY", "")
ZHTH_API_KEY = os.environ.get("ZHTH_API_KEY", "")
DS_API_KEY = os.environ.get("DS_API_KEY", "")
AR_API_KET = os.environ.get("AR_API_KEY", "")
RUOLI_API_KEY = os.environ.get("ROULI_API_KEY", "")

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


# ---------------------------------------------------------------------------
# Model names
# ---------------------------------------------------------------------------
DOUBAO_2_LITE: str = "doubao-seed-2-0-lite"
DOUBAO_2_MINI: str = "doubao-seed-2-0-mini"
DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
SEEDREAM_5_0_LITE: str = "doubao-seedream-5.0-lite"
SEEDANCE_1_5: str = "doubao-seedance-1-5-pro-251215"
SEEDANCE_1_0: str = "doubao-seedance-1-0-pro-250528"
GPT_IMAGE_2 = "gpt-image-2:stable"
GROK_IMAGINE_IMAGE = "grok-imagine-image:stable"
GPT_5_6_LUNA_XHIGH = "gpt-5.6-luna-xhigh:stable"
GPT_5_6_LUNA = "gpt-5.6-luna"
GPT_5_4_NANO = "gpt-5.4-nano-2026-03-17:stable"
GPT_5_6_TERRA = "gpt-5.6-terra"
GPT_5_5 = "gpt-5.5"
GEMINI_3_5_FLASH = "gemini-3.5-flash"
GROK_4_5 = "grok-4.5"

ADVANCE_MODEL_NAME: str = GPT_5_6_TERRA 
LITE_MODEL_NAME =  GPT_5_6_LUNA


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
EMBEDDING_MODEL: str = "BAAI/bge-m3"

# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
PROVIDER: Literal["volc", "volc_plan", "kege", "zhth", "ar", "ruoli"] = "ruoli"

def get_base_url(
    provider: Literal["volc", "volc_plan", "sf", "kege", "zhth", "ar", "ruoli"] = PROVIDER,
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
 

def get_api_key(
    provider: Literal["volc", "volc_plan", "sf", "kege", "zhth", "ar", "ruoli"] = PROVIDER,
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

# ---------------------------------------------------------------------------
# Behavioral constants
# ---------------------------------------------------------------------------
USER_INPUT_CONFIRM_DURING_TIME: int = 10
CONTEXT_QUEUE_LEN: int = 60
CONTEXT_QUEUE_OVERLAP_LEN: int = 7
VIDEO_RATE_LIMIT_SECONDS: int = 60
GENERATE_IMAGE_RATE_LIMIT_SECONDS: int = 60
IMAGE_MAX_SIZE_BYTES: int = 9 * 1024 * 1024
IMAGE_MAX_PIXELS: int = 36_000_000
MESSAGE_MAX_LENGTH: int = 2000
REPLY_MAX_LENGTH: int = 200
MAX_FORWARD_DEPTH: int = 3
FORWARD_API_TIMEOUT_SECONDS: int = 10
LONG_MSG_THRESHOLD: int = 500

# ---------------------------------------------------------------------------
# Auto response timer
# ---------------------------------------------------------------------------
AUTO_RESPONSE_GROUP_ID: int = _get_int_env("AUTO_RESPONSE_GROUP_ID")
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

CONTAINER_NAME="hatsume-space-kali"
