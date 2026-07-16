# Test Stub Audit -- Module Path Dependency Map

Generated from `git show 9878b9c:tests/<file>` (parent commit before test deletion in `dd59f00`).

## Summary

| Stat | Count |
|------|-------|
| Total test files in audit | 29 |
| Files that existed in git history | 25 |
| Files that never existed in git (placeholders) | 4 |
| Total test functions across all files | 280 |
| Unique `sys.modules` stub keys across all files | 78 |
| Files using `hatsume_plugin` (underscore alias) | 7 |
| Files using only `hatsume-plugin` (hyphen) | 18 |

---

## Placeholder Files (Never Committed)

These files appeared in `git status` as working-tree deletions but have no commit history:

| File | Notes |
|------|-------|
| `tests/test_image_generation.py` | Never committed; empty or minimal placeholder |
| `tests/test_likes.py` | Never committed; empty or minimal placeholder |
| `tests/test_pipeline.py` | Never committed; empty or minimal placeholder |
| `tests/test_video_generation.py` | Never committed; empty or minimal placeholder |

---

## Per-File Audit

### 1. `tests/test_agent_dispatch.py`
- **Tests count**: 5
- **Module under test**: `graph/agents.py` (agent registry, `register_agent`, `get_agent_list`, `get_agent_context`)
- **Load method**: Direct `from hatsume.plugins.hatsume_plugin.graph.agents import ...`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin` | Alias | Underscore alias for hyphen package |
| `nonebot` | External | Stub with `.require = lambda` |
| `nonebot.adapters` | External | With `.Bot` class |
| `nonebot.adapters.onebot` | External | Package stub |
| `nonebot.adapters.onebot.v11` | External | `.Message`, `.MessageSegment`, `.GroupMessageEvent` |
| `nonebot_plugin_localstore` | External | `.get_plugin_data_file` |
| `apscheduler` | External | Package |
| `apscheduler.triggers` | External | Package |
| `apscheduler.triggers.cron` | External | `.CronTrigger` |
| `nonebot_plugin_apscheduler` | External | `.scheduler` with `.scheduled_job` |
| `jieba` | External | `.cut`, `.posseg` |
| `jieba.posseg` | External | `.cut` |

### 2. `tests/test_agent_monitor.py`
- **Tests count**: 5
- **Module under test**: `graph/agents.py` (agent state tracking: `set_agent_state`, `get_agent_state`, `is_agent_running`)
- **Load method**: `importlib.util.spec_from_file_location` loading real `graph/agents.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `langchain_openai` | External | `.ChatOpenAI` mock |
| `langchain.agents` | External | `.create_agent` mock |
| `langchain.messages` | External | `.HumanMessage` mock |
| `hatsume.plugins.hatsume-plugin.graph.agents` | Own module | Loaded via spec, replaces stub |

### 3. `tests/test_agents_command.py`
- **Tests count**: 5
- **Module under test**: `handlers/commands.py` (`handle_agents` command handler) + `graph/agents.py`
- **Load method**: `importlib.util.spec_from_file_location` for both `graph/agents.py` and `handlers/commands.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin` | Alias | Underscore alias for hyphen package |
| `nonebot` | External | Module stub |
| `nonebot.adapters` | External | With `.Bot` class |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | `.Message`, `.MessageSegment`, `.GroupMessageEvent` |
| `hatsume.plugins.hatsume_plugin.infra` | Own module | Stub: `run_cmd`, `run_cmd_async`, `delete_container`, `cleanup_persistent_container`, `ensure_container_running`, `render_html_to_image` |
| `hatsume.plugins.hatsume-plugin.infra` | Own module | Alias to the underscore stub |
| `hatsume.plugins.hatsume_plugin.models` | Own module | Stub: `generate_image_for`, `generate_video_for`, `choose_video_model`, `get_code_model` |
| `hatsume.plugins.hatsume-plugin.models` | Own module | Alias to the underscore stub |
| `hatsume.plugins.hatsume_plugin.config` | Own module | Stub: `ADMIN_QQ_ID`, `SKILLS_DIR` |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Alias to the underscore stub |
| `hatsume.plugins.hatsume_plugin.state` | Own module | Stub: `ConversationState` |
| `hatsume.plugins.hatsume-plugin.state` | Own module | Alias to the underscore stub |
| `hatsume.plugins.hatsume_plugin.utils` | Own module | Stub: `get_qq_avatar_url`, `get_group_member_name`, `search_group_members` |
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Alias to the underscore stub |
| `hatsume.plugins.hatsume_plugin.handlers.chat` | Own module | Stub: `start_chat`, `user_chat_handle` |

### 4. `tests/test_ai_json_output.py`
- **Tests count**: 11
- **Module under test**: `prompts.py` (role sys prompt) + JSON parsing logic replicated from `ai.py` (the `graph/nodes.py` module)
- **Load method**: `importlib.util.spec_from_file_location` for `prompts.py`; JSON parsing tested via replicated pure functions
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub: `BOT_QQ_ID` |
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Stub: `message_to_json` |
| `hatsume.plugins.hatsume-plugin.prompts` | Own module | Loaded via spec, replaces stub |

### 5. `tests/test_auto_create.py`
- **Tests count**: 4
- **Module under test**: `timer/executor.py` (`_random_next_trigger` function)
- **Load method**: `importlib.util.spec_from_file_location` for `config.py`, `timer/__init__.py`, `timer/store.py`, `timer/executor.py` (loads real code)
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Stub: `get_group_member_name` |
| `nonebot` | External | Stub: `get_bot`, `get_driver`, `require` |
| `nonebot_plugin_apscheduler` | External | Stub: `.scheduler` with `add_job`, `remove_job` |
| `apscheduler` | External | Package |
| `apscheduler.triggers` | External | Package |
| `apscheduler.triggers.date` | External | `.DateTrigger` |
| `hatsume.plugins.hatsume-plugin.timer.store` | Own module | Loaded via spec, replaces stub |

### 6. `tests/test_auto_response.py`
- **Tests count**: 7
- **Module under test**: `timer/executor.py` (`_random_response_trigger` function) + `timer/store.py` (auto_response CRUD)
- **Load method**: `importlib.util.spec_from_file_location` for real timer modules
- **`sys.modules` stubs**: Same as test_auto_create.py (see above)

### 7. `tests/test_background_shell_agent.py`
- **Tests count**: 9
- **Module under test**: `graph/agents.py` (`background_shell` agent handler) + `infra.py` background process functions
- **Load method**: `importlib.util.spec_from_file_location` for real agents.py; rest stubbed
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin.config` | Own module | Stub: `DOCKER_ENV_PATH`, `SHELL_MAX_OUTPUT`, `SHELL_TIMEOUT` |
| `hatsume.plugins.hatsume_plugin.infra` | Own module | Stub: `run_cmd`, `start_background_cmd`, etc. |
| `hatsume.plugins.hatsume_plugin.graph.nodes.ai` | Own module | **NOTE: References `graph.nodes.ai` (old submodule). Now `graph.nodes` is a flat module.** |
| `hatsume.plugins.hatsume_plugin.graph.tools` | Own module | Stub: `dispatch_agent`, `configure_agent_notification_callback` |
| `hatsume.plugins.hatsume_plugin.prompts` | Own module | Stub: prompt constants |
| `hatsume.plugins.hatsume_plugin.models` | Own module | Stub: `get_code_model`, etc. |
| `nonebot` | External | Module stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | Message types |
| `langchain.messages` | External | `.HumanMessage` mock |

### 8. `tests/test_background_shell_infra.py`
- **Tests count**: 7
- **Module under test**: `infra.py` (`read_background_output`, `kill_background_cmd`, `_BACKGROUND_PROCS` dict)
- **Load method**: `importlib.util.spec_from_file_location` for real `infra.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin` | Alias | Underscore alias |
| `hatsume.plugins.hatsume_plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume_plugin.infra` | Own module | Loaded via spec |

### 9. `tests/test_background_shell_prompts.py`
- **Tests count**: 3
- **Module under test**: `prompts.py` (background shell decision/resolution prompt constants)
- **Load method**: `importlib.util.spec_from_file_location` for real `prompts.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin` | Alias | Underscore alias |
| `hatsume.plugins.hatsume_plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume_plugin.prompts` | Own module | Loaded via spec |

### 10. `tests/test_background_shell_stdin.py`
- **Tests count**: 6
- **Module under test**: `graph/agents.py` (`write_stdin_to_background`, `_STDIN_PENDING` dict)
- **Load method**: `importlib.util.spec_from_file_location` for real `graph/agents.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin` | Alias | Underscore alias |

### 11. `tests/test_background_shell_stdin_integration.py`
- **Tests count**: 4
- **Module under test**: `graph/agents.py` (full stdin injection flow)
- **Load method**: `importlib.util.spec_from_file_location` for real `graph/agents.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin` | Alias | Underscore alias |

### 12. `tests/test_chat_send.py`
- **Tests count**: 25
- **Module under test**: `handlers/chat.py` (`send()` branching logic via simulated `ConversationState`)
- **Load method**: `importlib.util.spec_from_file_location` for real `state.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub: `CONTEXT_QUEUE_LEN`, `CONTEXT_QUEUE_OVERLAP_LEN`, `IMAGE_RATE_LIMIT_SECONDS`, `VIDEO_RATE_LIMIT_SECONDS`, `USER_INPUT_CONFIRM_DURING_TIME` |
| `hatsume.plugins.hatsume-plugin.state` | Own module | Loaded via spec |

### 13. `tests/test_config_mimo.py`
- **Tests count**: 10 (all `@pytest.mark.skip`)
- **Module under test**: `config.py` (mimo provider constants and branches)
- **Load method**: `importlib.util.spec_from_file_location("config_under_test", CONFIG_PATH)` -- direct file load, no sys.modules stubs needed
- **`sys.modules` stubs**: None (loads config.py as `config_under_test` directly)

### 14. `tests/test_container_lifecycle.py`
- **Tests count**: 16
- **Module under test**: `infra.py` (container refcount lifecycle: `_acquire_subprocess`, `_release_subprocess`, `_start_stop_timer`, `_stop_container_after_grace`)
- **Load method**: `importlib.util.spec_from_file_location` for real `infra.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume_plugin` | Alias | Underscore alias |
| `hatsume.plugins.hatsume_plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume_plugin.infra` | Own module | Loaded via spec |

### 15. `tests/test_conversation.py`
- **Tests count**: 11
- **Module under test**: `handlers/chat.py` (`start_new_conversation` function), originally from deleted `handlers/conversation.py`
- **Load method**: `importlib.util.spec_from_file_location` for real `state.py` and `handlers/chat.py`; everything else fully stubbed
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub: multiple config constants |
| `hatsume.plugins.hatsume-plugin.state` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.graph` | Own module | Package stub |
| `hatsume.plugins.hatsume-plugin.graph.nodes` | Own module | Stub: `bind_state`, `reset_memory_record_context`, `set_current_query_user_id`, `get_role_sys_prompt`, `append_auxiliary_message` |
| `hatsume.plugins.hatsume-plugin.graph.builder` | Own module | Stub: `graph` with `ainvoke` |
| `hatsume.plugins.hatsume-plugin.graph.tools` | Own module | Stub: `configure_agent_notification_callback`, `configure_tool_callbacks` |
| `hatsume.plugins.hatsume-plugin.graph.agents` | Own module | Stub: `get_agent_list`, `get_agent_handler` |
| `hatsume.plugins.hatsume-plugin.handlers.chat` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.handlers.commands` | Own module | Stub: `_wire_conv_state` |
| `hatsume.plugins.hatsume-plugin.handlers.pipeline` | Own module | Stub: `get_human_message` |
| `hatsume.plugins.hatsume-plugin.infra` | Own module | Stub: `run_cmd`, `ensure_container_running` |
| `hatsume.plugins.hatsume-plugin.prompts` | Own module | Stub: `HTML_GENERATION_PROMPT` |
| `hatsume.plugins.hatsume-plugin.memory.store` | Own module | Stub: `get_mem_list`, `add_mem` |
| `hatsume.plugins.hatsume-plugin.memory.retrieval` | Own module | Stub: `query_mems` |
| `nonebot` | External | Module stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | `.Message`, `.MessageSegment`, `.GroupMessageEvent` |

### 16. `tests/test_deepseek_provider.py`
- **Tests count**: 4
- **Module under test**: `config.py` (Deepseek constants: `DEEPSEEK_BASE_URL`, `DEEPSEEK_V4_PRO`, `get_deepseek_api_key`) and `models.py` (`get_code_model`)
- **Load method**: Direct `from hatsume.plugins.hatsume_plugin.config import ...` and `from hatsume.plugins.hatsume_plugin.models import ...` (imports with underscore alias path)
- **`sys.modules` stubs**: None (relies on conftest or import-time package hierarchy setup not visible in this file)

### 17. `tests/test_file_transfer.py`
- **Tests count**: 18
- **Module under test**: `handlers/commands.py` (file_transfer path validation: `_validate_path`, `_check_file_size`, `_is_regular_file`) -- originally from a `file_transfer` module
- **Load method**: `importlib.util.spec_from_file_location` for real `handlers/commands.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.file_transfer` | Own module | **NOTE: `file_transfer` module no longer exists; logic moved to `handlers/commands.py`** |
| `nonebot` | External | Module stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | Message types |

### 18. `tests/test_forward.py`
- **Tests count**: 17
- **Module under test**: `handlers/forward.py` (forward message parsing: `parse_forward_messages`, `collect_people_from_messages`)
- **Load method**: `importlib.util.spec_from_file_location` for real `handlers/forward.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `nonebot.adapters` | External | With `.Bot` class |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Stub: `get_qq_avatar_url`, etc. |
| `hatsume.plugins.hatsume-plugin.handlers.forward` | Own module | Loaded via spec (real module) |

### 19. `tests/test_graph_nodes.py`
- **Tests count**: 26
- **Module under test**: `graph/nodes.py` (all graph nodes: `human_node`, `chat_end_detect_node`, `ai_node`, `finish_conversation_node`, `append_auxiliary_message`, `detect_agent_notification`)
- **Load method**: `importlib.util.spec_from_file_location` for real `graph/nodes.py`; extensive external stubs
- **`sys.modules` stubs**: (30+ keys, largest set)

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume` | Package | Empty package |
| `hatsume.plugins` | Package | Empty package |
| `hatsume.plugins.hatsume-plugin` | Package | Main package |
| `hatsume.plugins.hatsume-plugin.graph` | Package | Graph package |
| `hatsume.plugins.hatsume-plugin.memory` | Package | Memory package |
| `hatsume.plugins.hatsume-plugin.infra` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.prompts` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.skills` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.models` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.store` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.retrieval` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.graph.tools` | Own module | Partially stubbed |
| `hatsume.plugins.hatsume-plugin.graph.nodes` | Own module | Loaded via spec (real module) |
| `nonebot` | External | Stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | Message types |
| `nonebot_plugin_localstore` | External | Stub |
| `langchain` | External | Package |
| `langchain.messages` | External | Stub |
| `langchain.agents` | External | Stub |
| `langchain_core` | External | Package |
| `langchain_core.messages` | External | Stub |
| `langchain_core.tools` | External | Stub |
| `langchain_community` | External | Package |
| `langchain_community.tools` | External | Stub |
| `langgraph` | External | Package |
| `langgraph.graph` | External | Stub |
| `openai` | External | Stub |

### 20. `tests/test_membersearch.py`
- **Tests count**: 17
- **Module under test**: `utils/__init__.py` (`search_group_members`), `graph/tools.py` (`membersearch` tool), `handlers/commands.py` (`handle_membersearch` command)
- **Load method**: `importlib.util.spec_from_file_location` for real `utils.py`, `graph/tools.py`, `handlers/commands.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `nonebot` | External | Stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | Message types |
| `nonebot.params` | External | Stub |
| `langchain` | External | Package |
| `langchain.messages` | External | Stub |
| `langchain.agents` | External | Stub |
| `langchain_core` | External | Package |
| `langchain_core.messages` | External | Stub |
| `langchain_core.tools` | External | Stub |
| `langchain_community` | External | Package |
| `langchain_community.tools` | External | Stub |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.models` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.infra` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.store` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.retrieval` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.skills` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.timer` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.graph.tools` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.state` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.handlers.commands` | Own module | Loaded via spec (real module) |

### 21. `tests/test_memory_db.py`
- **Tests count**: 8
- **Module under test**: `memory/db.py` (SQLite storage layer: `init_db`, `insert_memory`, `load_all_memories`, `delete_expired_memories`, migration)
- **Load method**: `importlib.util.spec_from_file_location` for real `memory/db.py`; builds package hierarchy with `hatsume.plugins.hatsume-plugin` path
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume` | Package | Empty package |
| `hatsume.plugins` | Package | Empty package |
| `hatsume.plugins.hatsume-plugin` | Package | Main package |
| `hatsume.plugins.hatsume-plugin.memory` | Package | Memory package |
| `hatsume.plugins.hatsume-plugin.memory.tokenizer` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.memory.store` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.memory.db` | Own module | Loaded via spec (real module) |

### 22. `tests/test_memory_utils.py`
- **Tests count**: 6
- **Module under test**: `memory/store.py` (`add_mem`, embedding rebuild logic, `init_tokenized_corpus`) and `memory/retrieval.py` (`query_mems`)
- **Load method**: `importlib.util.spec_from_file_location` for real memory modules
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `hatsume` | Package | Empty package |
| `hatsume.plugins` | Package | Empty package |
| `hatsume.plugins.hatsume-plugin` | Package | Main package |
| `hatsume.plugins.hatsume-plugin.memory` | Package | Memory package |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.state` | Own module | Stub: `ConversationState` |
| `hatsume.plugins.hatsume-plugin.memory.db` | Own module | Loaded via spec (real module) |
| `nonebot` | External | Stub |
| `nonebot_plugin_localstore` | External | Stub |
| `apscheduler` | External | Package |
| `apscheduler.triggers` | External | Package |
| `apscheduler.triggers.cron` | External | `.CronTrigger` |
| `rank_bm25` | External | Stub |

### 23. `tests/test_omni_model.py`
- **Tests count**: 15
- **Module under test**: `config.py` (mimo/omni provider constants), `models.py` (model factories: `get_mimo_api_model`, `get_omni_model`), and image-to-text pipeline logic
- **Load method**: `importlib.util.spec_from_file_location` for real `config.py` and `models.py`
- **`sys.modules` stubs**:

| Stub key | Type | Notes |
|----------|------|-------|
| `nonebot` | External | Module stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | Message types |
| `langchain_openai` | External | `.ChatOpenAI`, `.OpenAIEmbeddings` mocks |
| `volcenginesdkarkruntime` | External | `.Ark` mock |
| `PIL` | External | Package |
| `PIL.Image` | External | `.open` mock |
| `requests` | External | `.get` mock |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.models` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.prompts` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.handlers.pipeline` | Own module | Stub |

### 24. `tests/test_random_acg_photo.py`
- **Tests count**: 5
- **Module under test**: `graph/tools.py` (`random_acg_photo` tool)
- **Load method**: `importlib.util.spec_from_file_location` for real `graph/tools.py`
- **`sys.modules` stubs**: (20 keys, mirrors test_tools.py setup)

| Stub key | Type | Notes |
|----------|------|-------|
| `nonebot` | External | Stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | Message types |
| `nonebot.params` | External | Stub |
| `langchain` | External | Package |
| `langchain.messages` | External | Stub |
| `langchain.agents` | External | Stub |
| `langchain_core` | External | Package |
| `langchain_core.messages` | External | Stub |
| `langchain_core.tools` | External | Stub |
| `langchain_community` | External | Package |
| `langchain_community.tools` | External | Stub |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.models` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.infra` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.store` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.retrieval` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.graph.tools` | Own module | Loaded via spec (real module) |

### 25. `tests/test_tools.py`
- **Tests count**: 27
- **Module under test**: `graph/tools.py` (all tools: `get_avatar`, `generate_image`, `generate_video`, `query_memory`, `respond_to_shell`, `choose_image_model`, rate limiters, HTML capture flag)
- **Load method**: `importlib.util.spec_from_file_location` for real `graph/tools.py`
- **`sys.modules` stubs**: (25 keys, most extensive)

| Stub key | Type | Notes |
|----------|------|-------|
| `nonebot` | External | Stub |
| `nonebot.adapters` | External | With `.Bot` |
| `nonebot.adapters.onebot` | External | Package |
| `nonebot.adapters.onebot.v11` | External | Message types |
| `nonebot.params` | External | Stub |
| `langchain` | External | Package |
| `langchain.messages` | External | Stub |
| `langchain.agents` | External | Stub |
| `langchain_core` | External | Package |
| `langchain_core.messages` | External | Stub |
| `langchain_core.tools` | External | Stub |
| `langchain_community` | External | Package |
| `langchain_community.tools` | External | Stub |
| `langchain_openai` | External | `.ChatOpenAI` mock |
| `volcenginesdkarkruntime` | External | `.Ark` mock |
| `hatsume.plugins.hatsume-plugin.config` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.models` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.utils` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.infra` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.store` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.memory.retrieval` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.graph.tools` | Own module | Loaded via spec (real module) |
| `hatsume.plugins.hatsume-plugin.state` | Own module | Stub: `ConversationState` |
| `hatsume.plugins.hatsume-plugin.handlers.commands` | Own module | Stub |
| `hatsume.plugins.hatsume-plugin.prompts` | Own module | Stub |

---

## Key Findings for Module-Path Rewrite

### 1. The Hyphen vs Underscore Alias Pattern

The project directory is `hatsume-plugin` (with hyphen), but Python cannot import hyphens in package names. The test files handle this in two ways:

**Pattern A: Both hyphen and underscore in sys.modules (dual registration)**

Files like `test_agent_dispatch.py` and `test_agents_command.py` register BOTH:
- `hatsume.plugins.hatsume-plugin.*` (hyphen, the "real" path)
- `hatsume.plugins.hatsume_plugin.*` (underscore, the import alias)

This is done via:
```python
alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
alias.__path__ = [str(PLUGIN_DIR)]
sys.modules["hatsume.plugins.hatsume_plugin"] = alias
```

**Pattern B: Hyphen only (no underscore alias)**

Files like `test_graph_nodes.py`, `test_conversation.py`, `test_memory_db.py` use only `hatsume.plugins.hatsume-plugin.*` paths. These tests load the real module via spec and register it under the hyphen path. Internal imports within the loaded module that reference `hatsume.plugins.hatsume_plugin.*` would fail unless the alias also exists.

**Pattern C: Underscore only (some test files)**

`test_deepseek_provider.py` imports directly from `hatsume.plugins.hatsume_plugin.config` without any explicit sys.modules setup -- this likely depends on test runner conftest setup.

**Files using `hatsume_plugin` (underscore) aliases:**
| File | Notes |
|------|-------|
| `test_agent_dispatch.py` | Creates alias for package hierarchy |
| `test_agents_command.py` | Creates alias for 7 submodules |
| `test_background_shell_agent.py` | Uses underscore for all 7 stubs |
| `test_background_shell_infra.py` | Uses underscore for 3 stubs |
| `test_background_shell_prompts.py` | Uses underscore for 3 stubs |
| `test_background_shell_stdin.py` | Uses underscore |
| `test_background_shell_stdin_integration.py` | Uses underscore |
| `test_container_lifecycle.py` | Uses underscore for 3 stubs |
| `test_deepseek_provider.py` | Imports from underscore path directly |

### 2. Modules Referenced by Tests That Have Been Restructured

| Old path (in stubs) | Current state | Affected tests |
|---------------------|---------------|----------------|
| `hatsume.plugins.hatsume_plugin.graph.nodes.ai` | Merged into `graph/nodes.py` (flat module, no `ai` submodule) | `test_background_shell_agent.py` |
| `hatsume.plugins.hatsume-plugin.file_transfer` | Module no longer exists; logic moved to `handlers/commands.py` | `test_file_transfer.py` |
| `hatsume.plugins.hatsume-plugin.handlers.conversation` | Merged into `handlers/chat.py` | `test_conversation.py` (already loads `chat.py`) |
| `hatsume.plugins.hatsume-plugin.graph.nodes` (as package with submodules `ai`, `detect`, `finish`, `human`) | Now a single flat `graph/nodes.py` module | `test_graph_nodes.py` (loads nodes.py directly, unaffected) |

### 3. Most Commonly Stubbed External Dependencies

These appear across many test files as sys.modules stubs:

| External module | File count | Typical stub |
|-----------------|------------|--------------|
| `nonebot` | 15 | Module with `.get_bot()`, `.require()` |
| `nonebot.adapters` | 15 | Package with `.Bot` class |
| `nonebot.adapters.onebot` | 14 | Package |
| `nonebot.adapters.onebot.v11` | 14 | `.Message`, `.MessageSegment`, `.GroupMessageEvent` |
| `langchain` | 5 | Package |
| `langchain.messages` | 5 | `.HumanMessage` |
| `langchain.agents` | 5 | `.create_agent` |
| `langchain_core` | 5 | Package |
| `langchain_core.messages` | 4 | Stub |
| `langchain_core.tools` | 4 | Stub |
| `langchain_community` | 4 | Package |
| `langchain_community.tools` | 4 | Stub |
| `langchain_openai` | 4 | `.ChatOpenAI`, `.OpenAIEmbeddings` |
| `langgraph` | 1 | Package (`test_graph_nodes.py`) |
| `langgraph.graph` | 1 | Stub (`test_graph_nodes.py`) |
| `nonebot_plugin_localstore` | 4 | `.get_plugin_data_file` |
| `nonebot_plugin_apscheduler` | 3 | `.scheduler` |
| `apscheduler` | 4 | Package |
| `apscheduler.triggers` | 4 | Package |
| `apscheduler.triggers.cron` | 2 | `.CronTrigger` |
| `apscheduler.triggers.date` | 2 | `.DateTrigger` |
| `jieba` | 1 | `.cut`, `.posseg` (`test_agent_dispatch.py`) |
| `jieba.posseg` | 1 | `.cut` (`test_agent_dispatch.py`) |
| `rank_bm25` | 1 | Stub (`test_memory_utils.py`) |
| `volcenginesdkarkruntime` | 2 | `.Ark` (`test_omni_model.py`, `test_tools.py`) |
| `PIL` / `PIL.Image` | 1 | Image mock (`test_omni_model.py`) |
| `requests` | 1 | `.get` mock (`test_omni_model.py`) |
| `openai` | 1 | Package stub (`test_graph_nodes.py`) |
| `nonebot.params` | 3 | Stub (`test_membersearch.py`, `test_random_acg_photo.py`, `test_tools.py`) |

### 4. Most Commonly Stubbed Own Modules

These project-internal modules are stubbed (not loaded as real code) across multiple tests:

| Own module | File count | Typical stub contents |
|------------|------------|----------------------|
| `config` | 16 | `BOT_QQ_ID`, `ADMIN_QQ_ID`, `CONTEXT_QUEUE_LEN`, `DOCKER_ENV_PATH`, rate limits, model constants |
| `models` | 9 | `generate_image_for`, `generate_video_for`, `get_code_model`, `choose_video_model` |
| `utils` | 9 | `get_qq_avatar_url`, `get_group_member_name`, `message_to_json` |
| `infra` | 8 | `run_cmd`, `ensure_container_running`, `render_html_to_image` |
| `memory.store` | 7 | `get_mem_list`, `add_mem` |
| `memory.retrieval` | 6 | `query_mems` |
| `prompts` | 6 | Prompt string constants |
| `state` | 5 | `ConversationState` |
| `graph.tools` | 5 | Tool callbacks, dispatch functions |
| `handlers.commands` | 4 | `_wire_conv_state` |
| `handlers.pipeline` | 2 | `get_human_message` |
| `skills` | 2 | Stub |
| `timer` | 1 | Stub |

### 5. How Each Test Loads Its Module Under Test

| Test file | Module under test | Load method |
|-----------|------------------|-------------|
| `test_agent_dispatch.py` | `graph/agents.py` | Direct `from ... import` |
| `test_agent_monitor.py` | `graph/agents.py` | `spec_from_file_location` |
| `test_agents_command.py` | `handlers/commands.py` + `graph/agents.py` | `spec_from_file_location` |
| `test_ai_json_output.py` | `prompts.py` + replicated JSON logic | `spec_from_file_location` + pure functions |
| `test_auto_create.py` | `timer/executor.py` | `spec_from_file_location` |
| `test_auto_response.py` | `timer/executor.py` + `timer/store.py` | `spec_from_file_location` |
| `test_background_shell_agent.py` | `graph/agents.py` | `spec_from_file_location` |
| `test_background_shell_infra.py` | `infra.py` | `spec_from_file_location` |
| `test_background_shell_prompts.py` | `prompts.py` | `spec_from_file_location` |
| `test_background_shell_stdin.py` | `graph/agents.py` | `spec_from_file_location` |
| `test_background_shell_stdin_integration.py` | `graph/agents.py` | `spec_from_file_location` |
| `test_chat_send.py` | `state.py` (ConversationState) | `spec_from_file_location` |
| `test_config_mimo.py` | `config.py` | `spec_from_file_location` (as `config_under_test`) |
| `test_container_lifecycle.py` | `infra.py` | `spec_from_file_location` |
| `test_conversation.py` | `state.py` + `handlers/chat.py` | `spec_from_file_location` |
| `test_deepseek_provider.py` | `config.py` + `models.py` | Direct `from ... import` |
| `test_file_transfer.py` | `handlers/commands.py` | `spec_from_file_location` |
| `test_forward.py` | `handlers/forward.py` | `spec_from_file_location` |
| `test_graph_nodes.py` | `graph/nodes.py` | `spec_from_file_location` |
| `test_membersearch.py` | `utils/__init__.py` + `graph/tools.py` + `handlers/commands.py` | `spec_from_file_location` |
| `test_memory_db.py` | `memory/db.py` | `spec_from_file_location` |
| `test_memory_utils.py` | `memory/store.py` + `memory/retrieval.py` + `memory/tokenizer.py` | `spec_from_file_location` |
| `test_omni_model.py` | `config.py` + `models.py` | `spec_from_file_location` |
| `test_random_acg_photo.py` | `graph/tools.py` | `spec_from_file_location` |
| `test_tools.py` | `graph/tools.py` | `spec_from_file_location` |

### 6. Tests That Need `utils` Not As A Single File

Note: `utils` was restructured from `utils.py` (single file) to `utils/__init__.py` (package). Tests that load utils via `spec_from_file_location` (`test_membersearch.py`, `test_ai_json_output.py`, `test_auto_create.py`, etc.) may need path updates.

- Old path: `PLUGIN_DIR / "utils.py"` (12 test files reference utils)
- New path: `PLUGIN_DIR / "utils" / "__init__.py"`

However, since `spec_from_file_location` uses the exact file path, tests that do `spec_from_file_location(name, PLUGIN_DIR / "utils.py")` will break. Tests that only stub utils (don't load the real file) are unaffected.

Let me check which tests load utils via spec vs stub...

Tests that **load real utils via spec**:
- `test_membersearch.py` -- loads `UTILS_PATH = .../utils.py` -- **needs path update to `utils/__init__.py`**

Tests that **stub utils only** (no spec load):
- `test_agents_command.py`
- `test_ai_json_output.py`
- `test_auto_create.py`
- `test_auto_response.py`
- `test_forward.py`
- `test_omni_model.py`
- `test_random_acg_photo.py`
- `test_tools.py`
- `test_graph_nodes.py`
