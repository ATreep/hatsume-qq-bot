# Quickstart: Random ACG Photo Tool

**Feature**: 030-random-acg-photo-tool
**Date**: 2026-07-11

## Prerequisites

- macOS with Apple Photos.app installed
- "ACG" album exists in Photos with at least one photo
- Terminal/process has Automation permissions for Photos.app (System Preferences → Privacy → Automation)
- Docker sandbox container is configured (existing `hatsume-space-kali`)

## Usage

The tool is invoked automatically by the LLM when a user asks for ACG/anime images. No manual command required.

**Example user prompts that trigger the tool:**
- "来张二次元图"
- "随机发一张ACG图"
- "看看你的动漫收藏"

## Testing

```bash
# Run unit tests (no Photos.app or Docker needed — everything mocked)
python -m pytest tests/test_random_acg_photo.py -xvs

# Manual integration test (requires Photos.app + Docker sandbox)
python -c "
import asyncio
# Set up tool callbacks before calling
from hatsume.plugins.hatsume_plugin.graph.tools import random_acg_photo
result = asyncio.run(random_acg_photo())
print(result)
"
```

## Verification

1. Start the bot: `nb run`
2. In a QQ group, send: `@初芽 随机发张ACG图`
3. Verify bot replies with an image from the ACG album

## Files Changed

| File | Change |
|------|--------|
| `graph/tools.py` | Add `random_acg_photo` @tool (~60 lines) |
| `graph/nodes/ai.py` | Import + register in `chat_agent` tools list (2 lines) |
| `tests/test_random_acg_photo.py` | New: 4 test cases |
