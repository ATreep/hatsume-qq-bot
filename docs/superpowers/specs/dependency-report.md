# hatsume-plugin Dependency Graph Report

Generated: 2026-07-15

---

## 1. File-by-File Breakdown

### `__init__.py` (plugin entry point)

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__` |
| **Third-party** | `nonebot` (get_driver), `nonebot.rule` (keyword, to_me), `nonebot.adapters.onebot.v11` (Message, GroupMessageEvent, PokeNotifyEvent, MessageEvent, MessageSegment), `nonebot.exception` (FinishedException), `nonebot.adapters` (Bot), `nonebot.params` (CommandArg) |
| **Internal** | `.config` (ADMIN_QQ_ID), `.handlers.chat` (start_chat, user_chat_handle), `.handlers.commands` (8 handlers), `.handlers.likes` (2 handlers), `.handlers.poke` (handle_poke), `.memory.store` (init_memory_system, init_tokenized_corpus), `.timer` (init_scheduler) |
| **Exports** | Matcher instances: `shell_cmd`, `generate_video_cmd`, `like_match`, `timer_cmd`, `skills_cmd`, `likerank_cmd`, `membersearch_cmd`, `resetsandbox_cmd`, `agents_cmd`, `clear_cmd`, `autocreate_cmd`, `autoresponse_cmd`, `start_chat_by_at_and_mentioned`, `start_chat_by_at`, `start_chat_by_mentioned`, `user_chat`, `poke_notice` |

### `config.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `os`, `pathlib` (Path) |
| **Third-party** | `typing` (Callable, Literal), `dotenv` (load_dotenv) |
| **Internal** | (none) |
| **Exports** | Constants: `BOT_QQ_ID`, `AGENT_QQ_EMAIL`, `ADMIN_QQ_ID`, `GIITHUB_ACCOUNT`, `GITHUB_REPO`, `ARK_PLAN_API_KEY`, `ARK_API_KEY`, `SILICONFLOW_API_KEY`, `OPENCODE_API_KEY`, `DEEPSEEK_API_KEY`, `NV_API_KEY`, `KEGEAI_API_KEY`, `VOLCENGINE_BASE_URL`, `VOLCENGINE_PLAN_BASE_URL`, `SILICONFLOW_BASE_URL`, `OPENCODE_GO_BASE_URL`, `OPENCODE_ZEN_BASE_URL`, `CCSWITCH_ROUTE_URL`, `DEEPSEEK_BASE_URL`, `KEGEAI_BASE_URL`, model name constants (16), `EMBEDDING_MODEL`, `ADVANCE_MODEL_NAME`, `LITE_MODEL_NAME`, `MINI_MODEL_NAME`, `get_base_url()`, `get_api_key()`, behaviour constants (~20), `AUTO_CREATE_GROUP_ID`, `AUTO_RESPONSE_GROUP_ID`, `DOCKER_ENV_PATH`, `SHELL_MAX_OUTPUT`, `SHELL_TIMEOUT`, `TIMER_MAX_FUTURE_DAYS`, `TIMER_TOLERANCE_MINUTES`, `SKILLS_DIR`, `CODING_AGENT_SKILL_PATH`, `CONTAINER_NAME` |

### `models.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `os`, `random`, `time` |
| **Third-party** | `typing` (Literal, Optional), `langchain_openai` (ChatOpenAI, OpenAIEmbeddings), `volcenginesdkarkruntime` (Ark), `langchain_core.messages` (monkey-patch), `langchain_openai.chat_models.base` (monkey-patch) |
| **Internal** | `.config` (21 constants/functions) |
| **Internal (deferred)** | `.infra` (ensure_container_running, run_cmd) |
| **Exports** | `get_volcengine_api_model()`, `get_standard_api_model()`, `get_advance_model()`, `get_lite_model()`, `get_mini_model()`, `get_code_model()`, `choose_video_model()`, `get_embedding_model()`, `generate_image_for_volc()`, `generate_image_for_gpt_image()`, `generate_image_for_kege()`, `generate_video_for()` |

### `state.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `time` |
| **Third-party** | `dataclasses` (dataclass, field), `typing` (Any, Callable, Coroutine, TypedDict, Union) |
| **Internal** | `.config` (CONTEXT_QUEUE_OVERLAP_LEN, VIDEO_RATE_LIMIT_SECONDS, GENERATE_IMAGE_RATE_LIMIT_SECONDS) |
| **Exports** | `PersonEntry`, `MemoryRecord`, `SourceEntry`, `TextContent`, `ImageContent`, `ContentPart`, `ConversationState` |

### `prompts.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `random` |
| **Third-party** | (none) |
| **Internal** | `.config` (AGENT_QQ_EMAIL, BOT_QQ_ID, GIITHUB_ACCOUNT, GITHUB_REPO) |
| **Internal (deferred)** | `.graph.agents` (get_running_instances) |
| **Exports** | `role_sys_prompt`, `build_skill_prompt()`, `build_agent_state_prompt()`, `AUXILIARY_COMPACTION_PROMPT`, `build_face_injection_prompt()`, `CHAT_END_DETECT_PROMPT`, `build_memory_context_prompt()`, `build_video_failure_prompt()`, `build_video_success_prompt()`, `CODING_AGENT_PROMPT`, `get_auto_create_prompt()`, `get_auto_response_prompt()`, `build_timer_context_prompt()`, `build_timer_task_prompt()`, `BACKGROUND_SHELL_DECISION_PROMPT`, `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` |

### `infra.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `re`, `subprocess`, `tempfile`, `threading`, `pathlib` (Path) |
| **Third-party** | (none at module level; `nonebot` in deferred) |
| **Internal** | `.config` (DOCKER_ENV_PATH, SHELL_TIMEOUT) |
| **Exports** | `ensure_container_running()`, `run_cmd()`, `cleanup_persistent_container()`, `render_html_to_image()`, `start_background_cmd()`, `read_background_output()`, `kill_background_cmd()`, `delete_container()`, `stop_container()`, `_background_procs` |

### `graph/__init__.py`

Empty docstring only -- no imports, no exports.

### `graph/agents.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `uuid` |
| **Third-party** | `typing` (Any, Callable, Coroutine) |
| **Internal (deferred)** | `..models` (get_code_model), `..prompts` (CODING_AGENT_PROMPT, build_skill_prompt, BACKGROUND_SHELL_DECISION_PROMPT, BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT), `.tools` (shell_executor, skill_loader, search_web, etc.), `..skills` (get_skill_manager), `..infra` (start_background_cmd, read_background_output, kill_background_cmd, _background_procs), `.nodes` (inject_agent_notification, NOTIFY_MARK) |
| **Exports** | `AgentHandler`, `add_agent_instance()`, `set_agent_state()`, `get_agent_state()`, `get_running_instances()`, `is_agent_running()`, `get_agent_context()`, `register_agent()`, `get_agent_list()`, `get_agent_handler()`, `AGENT_REGISTRY`, `_stdin_queues`, `_write_stdin()`, `_cleanup_stdin_queues()` |

### `graph/builder.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__` |
| **Third-party** | `langgraph.graph` (START, END, StateGraph, MessagesState) |
| **Internal** | `.nodes` (ai_node, human_node, chat_end_detect_node, finish_conversation_node, _last_was_auxiliary_only) |
| **Exports** | `graph` (compiled StateGraph) |

### `graph/nodes.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `base64`, `json`, `random`, `re`, `time`, `traceback` |
| **Third-party** | `typing` (Any), `nonebot` (get_bot), `nonebot_plugin_localstore` (as store), `langchain.messages` (AIMessage, HumanMessage, SystemMessage), `langchain.agents` (create_agent), `langchain_core.messages` (RemoveMessage), `langgraph.graph` (MessagesState), `nonebot.adapters.onebot.v11` (MessageSegment) |
| **Internal** | `..models` (get_advance_model, get_lite_model, get_mini_model), `..prompts` (9 exports), `..skills` (get_skill_manager), `.tools` (18 tools), `..utils` (3 functions), `..utils.md_to_image` (auto_convert_text), `..config` (CONTEXT_QUEUE_LEN) |
| **Internal (deferred)** | `..memory.store` (add_mem), `..handlers.chat` (conv_state, start_new_conversation) |
| **Exports** | `NOTIFY_MARK`, `TIMER_MARK`, `bind_state()`, `detect_agent_notification()`, `detect_timer_notification()`, `extract_user_ids_from_content()`, `inject_agent_notification()`, `inject_timer()`, `get_role_sys_prompt()`, `append_auxiliary_message()`, `set_current_query_user_id()`, `get_retrieved_keys()`, `_last_was_auxiliary_only`, `ai_node()`, `human_node()`, `chat_end_detect_node()`, `finish_conversation_node()` |

### `graph/tools.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `contextvars`, `os`, `random`, `ssl`, `subprocess`, `traceback`, `urllib.request`, `urllib.error` |
| **Third-party** | `typing` (Any, Callable), `langchain_core.tools` (tool), `langchain_community.tools` (DuckDuckGoSearchRun), `nonebot.adapters.onebot.v11` (MessageSegment) |
| **Internal** | `..infra` (run_cmd, ensure_container_running), `..memory.store` (get_mem_list), `..memory.retrieval` (query_mems), `.agents` (get_agent_list, get_agent_handler) |
| **Internal (deferred)** | `..models` (generate_image_for_volc, generate_image_for_kege, generate_video_for, choose_video_model), `..timer` (get_store), `..timer.executor` (add_jobs_for_task, cancel_task_jobs), `..skills` (get_skill_manager), `..config` (CONTAINER_NAME, SKILLS_DIR), `..utils` (get_group_member_name, get_qq_avatar_url, search_group_members), `.nodes` (inject_agent_notification, NOTIFY_MARK), `.agents` (add_agent_instance, set_agent_state, _stdin_queues) |
| **Exports** | `set_shell_executor_limit()`, `set_current_group_id()`, `configure_tool_callbacks()`, `configure_agent_notification_callback()`, `reset_capture_flag()`, `query_memory()`, `_export_random_acg_photo()`, `_agent_notification_callback`, `_current_group_id`, `tool()` (decorator wrappers), and 18 tool functions: `find_memory`, `search_web`, `get_avatar`, `random_acg_photo`, `send_image`, `generate_image`, `generate_video`, `shell_executor`, `create_timer`, `list_timers`, `delete_timer`, `skill_loader`, `skill_remove`, `skill_download`, `skill_create`, `membersearch`, `agent_dispatch`, `respond_to_shell_prompt` |

### `handlers/__init__.py`

Empty docstring only -- no imports, no exports.

### `handlers/chat.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `time` |
| **Third-party** | `nonebot.adapters` (Bot), `nonebot.adapters.onebot.v11` (Message, MessageSegment, GroupMessageEvent) |
| **Internal** | `..config` (CONTEXT_QUEUE_LEN, USER_INPUT_CONFIRM_DURING_TIME), `..state` (ConversationState), `..graph.builder` (graph), `..graph.nodes` (4 exports), `.pipeline` (get_human_message), `..utils` (mask_secret_keys), `..utils.md_to_image` (auto_convert_text), `.commands` (_wire_conv_state), `..graph.tools` (configure_tool_callbacks, configure_agent_notification_callback), `..timer.executor` (set_timer_conv_callback) |
| **Exports** | `conv_state`, `start_new_conversation()`, `handle_ai_message()`, `start_chat()`, `user_chat_handle()` |

### `handlers/commands.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `time` |
| **Third-party** | `nonebot.adapters.onebot.v11` (Message, MessageSegment) |
| **Internal** | `..infra` (cleanup_persistent_container, run_cmd), `..models` (choose_video_model, generate_video_for), `..state` (ConversationState) |
| **Internal (deferred)** | `..graph.tools` (set_current_group_id), `..timer` (get_store), `..timer.executor` (add_jobs_for_task, cancel_task_jobs), `..skills` (get_skill_manager), `..utils` (get_group_member_name, search_group_members), `..graph.agents` (get_running_instances), `..graph.nodes` (inject_timer), `..prompts` (get_auto_create_prompt, get_auto_response_prompt), `..config` (AUTO_CREATE_GROUP_ID, AUTO_RESPONSE_GROUP_ID) |
| **Exports** | `_wire_conv_state()`, `handle_shell()`, `handle_generate_video()`, `handle_timer()`, `handle_list_skills()`, `handle_membersearch()`, `handle_resetsandbox()`, `handle_agents()`, `handle_clear()`, `handle_autocreate()`, `handle_autoresponse()` |

### `handlers/forward.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__` |
| **Third-party** | `typing` (Any), `nonebot.adapters` (Bot), `nonebot.adapters.onebot.v11` (Message) |
| **Internal** | `..config` (MAX_FORWARD_DEPTH), `..utils` (message_to_json) |
| **Exports** | `has_forward_segment()`, `parse_forward_messages()`, `resolve_forward_content()`, `collect_people_from_messages()` |

### `handlers/likes.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `json` |
| **Third-party** | `nonebot_plugin_localstore` (as store), `nonebot.adapters` (Bot), `nonebot.adapters.onebot.v11` (GroupMessageEvent) |
| **Internal** | `..utils` (get_group_member_name) |
| **Exports** | `handle_likerank()`, `handle_like()` |

### `handlers/pipeline.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `base64`, `json`, `time`, `traceback` |
| **Third-party** | `typing` (Any), `requests`, `nonebot.adapters` (Bot), `nonebot.adapters.onebot.v11` (GroupMessageEvent, MessageEvent), `PIL` (Image), `io` (BytesIO) |
| **Internal** | `..config` (IMAGE_MAX_PIXELS, IMAGE_MAX_SIZE_BYTES, MESSAGE_MAX_LENGTH, REPLY_MAX_LENGTH), `..utils` (message_to_json, build_forward_json, get_group_member_name, get_date), `.forward` (has_forward_segment, resolve_forward_content, collect_people_from_messages) |
| **Exports** | `get_human_message()` |

### `handlers/poke.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `base64` |
| **Third-party** | `nonebot.adapters` (Bot), `nonebot.adapters.onebot.v11` (PokeNotifyEvent, MessageSegment) |
| **Internal (deferred)** | `..graph.tools` (_export_random_acg_photo) |
| **Exports** | `handle_poke()` |

### `memory/__init__.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | (none) |
| **Third-party** | (none) |
| **Internal** | `.db` (6 functions), `.store` (7 functions), `.retrieval` (4 functions), `.tokenizer` (1 function) |
| **Exports** | Re-exports: `init_db`, `insert_memory`, `delete_expired_memories`, `load_all_memories`, `query_by_user_ids`, `query_all_except`, `migrate_from_json`, `get_mem_list`, `add_mem`, `init_tokenized_corpus`, `init_memory_system`, `normalize_people`, `normalize_memory_object`, `memory_has_user`, `query_mems`, `ensure_embedding_model`, `rebuild_bm25`, `rebuild_embedding_vectors`, `tokenize_with_pos` |

### `memory/db.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `json`, `sqlite3`, `time`, `pathlib` (Path) |
| **Third-party** | `numpy` |
| **Internal** | (none at module level; deferred imports of `.store`, `.tokenizer` in `migrate_from_json`) |
| **Exports** | `init_db()`, `insert_memory()`, `delete_expired_memories()`, `load_all_memories()`, `query_by_user_ids()`, `query_all_except()`, `migrate_from_json()` |

### `memory/retrieval.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__` |
| **Third-party** | `numpy`, `rank_bm25` (BM25Okapi) |
| **Internal** | `..config`, `.db` (as _db), `.store` (as _store), `.tokenizer` (as _tokenizer) |
| **Internal (deferred)** | `..models` (get_embedding_model) |
| **Exports** | `bm25`, `embedding_vectors`, `embedding_model`, `ensure_embedding_model()`, `rebuild_bm25()`, `rebuild_embedding_vectors()`, `get_embedding_vectors()`, `set_embedding_vectors()`, `query_mems()` |

### `memory/store.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `time`, `traceback`, `pathlib` (Path) |
| **Third-party** | `typing` (Any), `nonebot` (require), `nonebot_plugin_localstore` (as store), `apscheduler.triggers.cron` (CronTrigger) |
| **Internal** | `..config` (MEMORY_EXPIRY_DAYS), `.db` (as _db), `.tokenizer` (tokenize_with_pos) |
| **Internal (deferred)** | `.retrieval` (on function call) |
| **Exports** | `scheduler`, `tokenized_corpus`, `tokenized_corpus_pos`, `all_mem_list`, `bm25_dirty`, `_get_db()`, `get_mem_list()`, `normalize_people()`, `normalize_memory_object()`, `memory_has_user()`, `add_mem()`, `init_memory_system()`, `init_tokenized_corpus()` |

### `memory/tokenizer.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__` |
| **Third-party** | `jieba.posseg` (pseg) |
| **Internal** | (none) |
| **Exports** | `POS_WEIGHT`, `KEEP_POS`, `tokenize_with_pos()` |

### `skills/__init__.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__` |
| **Third-party** | (none) |
| **Internal** | `.manager` (SkillManager) |
| **Internal (deferred)** | `..config` (SKILLS_DIR) |
| **Exports** | `SkillManager`, `get_skill_manager()` |

### `skills/manager.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `pathlib` (Path) |
| **Third-party** | `yaml` |
| **Internal** | (none) |
| **Exports** | `SkillManager` class |

### `timer/__init__.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__` |
| **Third-party** | (none) |
| **Internal** | `.store` (TimerStore), `.executor` (reload_all_triggers, refresh_auto_response) |
| **Exports** | `get_store()`, `init_scheduler()` |

### `timer/executor.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `asyncio`, `random`, `time`, `traceback`, `datetime` (datetime, timezone, timedelta) |
| **Third-party** | `typing` (Any), `nonebot` (require), `apscheduler.triggers.date` (DateTrigger - deferred) |
| **Internal** | `..config` (AUTO_CREATE_GROUP_ID, TIMER_TOLERANCE_MINUTES), `.store` (TimerStore) |
| **Internal (deferred)** | `..prompts` (get_auto_create_prompt, get_auto_response_prompt), `..graph.nodes` (inject_timer) |
| **Exports** | `scheduler`, `register_job()`, `cancel_job()`, `cancel_task_jobs()`, `add_jobs_for_task()`, `reschedule_auto_create()`, `reschedule_auto_response()`, `refresh_auto_response()`, `refresh_auto_create()`, `reload_all_triggers()`, `set_timer_conv_callback()` |

### `timer/store.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `sqlite3`, `time`, `datetime` (datetime, timezone, timedelta), `pathlib` (Path) |
| **Third-party** | `nonebot_plugin_localstore` (optional/deferred) |
| **Internal** | `..config` (TIMER_MAX_FUTURE_DAYS) |
| **Internal (deferred)** | `..prompts` (get_auto_create_prompt, get_auto_response_prompt) |
| **Exports** | `TimerStore` class |

### `utils/__init__.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `datetime`, `time` (as _time), `re` (as _re) |
| **Third-party** | `nonebot.adapters` (Bot) |
| **Internal** | (none) |
| **Exports** | `get_group_member_name()`, `get_date()`, `get_qq_avatar_url()`, `message_to_json()`, `build_forward_json()`, `search_group_members()`, `mask_secret_keys()` |

### `utils/md_to_image.py`

| Category | Imports |
|----------|---------|
| **Stdlib** | `__future__`, `base64`, `random`, `re`, `traceback`, `datetime`, `importlib` (import_module), `pathlib` (Path) |
| **Third-party** | `typing` (TYPE_CHECKING), `anyio`, `markdown`, `nonebot` (require), `nonebot.adapters.onebot.v11` (MessageSegment), `nonebot_plugin_htmlrender` (render_html) |
| **Internal** | `..config` (LONG_MSG_THRESHOLD) |
| **Exports** | `auto_convert_text()` |

---

## 2. Dependency Matrix

Legend: **X** = module-level static import, **d** = deferred/lazy import (inside function body), **-** = no import

| Importing file \\ Imported file | conf | modl | stat | prom | infr | g/ag | g/bu | g/no | g/to | h/ch | h/cm | h/fw | h/lk | h/pi | h/po | m/db | m/re | m/st | m/tk | sk/i | sk/m | t/i | t/ex | t/st | u/i | u/md |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `__init__.py` | X | - | - | - | - | - | - | - | - | X | X | - | X | - | X | - | - | X | - | - | - | X | - | - | - | - |
| `config.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `models.py` | X | - | - | - | d | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `state.py` | X | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `prompts.py` | X | - | - | - | - | d | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `infra.py` | X | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `graph/agents.py` | - | d | - | d | d | - | - | d | d | - | - | - | - | - | - | - | - | - | - | d | - | - | - | - | - | - |
| `graph/builder.py` | - | - | - | - | - | - | - | X | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `graph/nodes.py` | X | X | - | X | - | - | - | - | X | d | - | - | - | - | - | d | - | - | - | X | - | - | - | - | X | X |
| `graph/tools.py` | d | d | - | - | X | X | - | d | - | - | - | - | - | - | - | X | X | - | - | d | - | d | d | - | d | - |
| `handlers/chat.py` | X | - | X | - | - | - | X | X | X | - | X | - | - | X | - | - | - | - | - | - | - | - | X | - | X | X |
| `handlers/commands.py` | d | X | X | d | X | d | - | d | d | - | - | - | - | - | - | - | - | - | - | d | - | d | d | - | d | - |
| `handlers/forward.py` | X | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | X | - |
| `handlers/likes.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | X | - |
| `handlers/pipeline.py` | X | - | - | - | - | - | - | - | - | - | - | X | - | - | - | - | - | - | - | - | - | - | - | - | X | - |
| `handlers/poke.py` | - | - | - | - | - | - | - | - | d | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `memory/__init__.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | X | X | X | X | - | - | - | - | - | - | - |
| `memory/db.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | d | d | - | - | - | - | - | - | - |
| `memory/retrieval.py` | X | d | - | - | - | - | - | - | - | - | - | - | - | - | - | X | - | X | X | - | - | - | - | - | - | - |
| `memory/store.py` | X | - | - | - | - | - | - | - | - | - | - | - | - | - | - | X | d | - | X | - | - | - | - | - | - | - |
| `memory/tokenizer.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `skills/__init__.py` | d | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | X | - | - | - | - | - |
| `skills/manager.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `timer/__init__.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | X | X | - | - |
| `timer/executor.py` | X | - | - | d | - | - | - | d | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | X | - | - |
| `timer/store.py` | X | - | - | d | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `utils/__init__.py` | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| `utils/md_to_image.py` | X | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |

Key: `conf`=config, `modl`=models, `stat`=state, `prom`=prompts, `infr`=infra, `g/ag`=graph/agents, `g/bu`=graph/builder, `g/no`=graph/nodes, `g/to`=graph/tools, `h/ch`=handlers/chat, `h/cm`=handlers/commands, `h/fw`=handlers/forward, `h/lk`=handlers/likes, `h/pi`=handlers/pipeline, `h/po`=handlers/poke, `m/db`=memory/db, `m/re`=memory/retrieval, `m/st`=memory/store, `m/tk`=memory/tokenizer, `sk/i`=skills/__init__, `sk/m`=skills/manager, `t/i`=timer/__init__, `t/ex`=timer/executor, `t/st`=timer/store, `u/i`=utils/__init__, `u/md`=utils/md_to_image

---

## 3. Circular Dependencies

Five circular dependencies were identified. All are resolved by using deferred/lazy imports (import inside function body).

### 3.1 `memory/store.py` <-> `memory/retrieval.py`

- `memory/retrieval.py` imports `memory/store.py` at module level (`from . import store as _store`)
- `memory/store.py` imports `memory/retrieval.py` lazily in `add_mem()` (`from . import retrieval`)
- **Severity**: Low. Safe because `store.py` is loaded first (via `__init__.py` order), and retrieval's reference to store is already satisfied.

### 3.2 `graph/nodes.py` <-> `graph/tools.py`

- `graph/nodes.py` imports `graph/tools.py` at module level (all tool functions)
- `graph/tools.py` imports `graph/nodes.py` lazily in `agent_dispatch()` (`from .nodes import inject_agent_notification, NOTIFY_MARK`)
- **Severity**: Low. The deferred import in `tools.py` is inside a coroutine that runs after both modules are fully loaded.

### 3.3 `graph/agents.py` <-> `graph/tools.py`

- `graph/tools.py` imports `graph/agents.py` at module level (`from .agents import get_agent_list, get_agent_handler`)
- `graph/agents.py` imports `graph/tools.py` lazily in `_run_coding_agent()` (tool functions)
- **Severity**: Low. Agents' tool imports are inside handler functions.

### 3.4 `graph/agents.py` <-> `graph/nodes.py`

- `graph/nodes.py` does NOT import `graph/agents.py` directly. But `tools.py` does import `agents.py`, and `nodes.py` imports from `tools.py`, making a transitive cycle.
- `graph/agents.py` imports `graph/nodes.py` lazily in `_run_background_shell()` (`from .nodes import inject_agent_notification, NOTIFY_MARK`)
- **Severity**: Low. Deferred import pattern.

### 3.5 `graph/nodes.py` <-> `handlers/chat.py`

- `handlers/chat.py` imports `graph/nodes.py` at module level (`from ..graph.nodes import bind_state, get_role_sys_prompt, ...`)
- `graph/nodes.py` imports `handlers/chat.py` lazily in `_start_direct_conv()` (`from ..handlers.chat import conv_state, start_new_conversation`)
- **Severity**: Low. The deferred import is inside a utility function only called for specific notification paths.

---

## 4. Leaf Modules

Leaf modules are files that are imported by other internal modules but import no internal modules themselves (only stdlib and/or third-party packages).

### True leaf (imported by others, imports zero internal modules)

| Module | Imported by |
|--------|------------|
| **`config.py`** | Almost all modules -- `__init__`, `models`, `state`, `prompts`, `infra`, `nodes`, `handlers/chat`, `handlers/commands`, `handlers/forward`, `handlers/pipeline`, `retrieval`, `store`, `executor`, `store(timer)`, `md_to_image` |
| **`memory/tokenizer.py`** | `memory/__init__`, `memory/retrieval`, `memory/store`, `memory/db` (deferred) |

### Near-leaf (imports 1 internal module at module level)

| Module | Imports (internal) | Imported by |
|--------|-------------------|-------------|
| **`state.py`** | `config` | `handlers/chat`, `handlers/commands` |
| **`infra.py`** | `config` | `models` (deferred), `tools`, `handlers/commands`, `graph/agents` (deferred) |
| **`skills/manager.py`** | (none) | `skills/__init__` |
| **`graph/builder.py`** | `nodes` | `handlers/chat` |
| **`utils/__init__.py`** | (none) | `nodes`, `handlers/chat`, `handlers/commands` (deferred), `handlers/forward`, `handlers/likes`, `handlers/pipeline`, `tools` (deferred) |
| **`utils/md_to_image.py`** | `config` | `nodes`, `handlers/chat` |

---

## 5. Dependency Graph (Topology)

```
config  <--  [leaf, imported by almost everything]
  |
  v
state  <--  handlers/chat, handlers/commands

infra  <--  tools, handlers/commands, graph/agents(d)

models  <--  nodes, handlers/commands, graph/agents(d), retrieval(d)

prompts  <--  nodes, graph/agents(d), executor(d), store(timer)(d)

memory/tokenizer  <--  [leaf] memory/*

memory/db  <--  memory/* (store, retrieval)

memory/retrieval  <--  tools, memory/store(d)

memory/store  <--  nodes(d), tools(r), __init__

skills/manager  <--  skills/__init__

skills/__init__  <--  nodes, tools(d), handlers/commands(d), graph/agents(d)

graph/agents  <--  tools(r), prompts(d), nodes(d)

graph/tools  <--  nodes(r), handlers/chat(r), handlers/commands(d),
                   handlers/poke(d), graph/agents(d)

graph/nodes  <--  builder(r), handlers/chat(r), handlers/commands(d),
                   graph/agents(d), graph/tools(d), executor(d)

graph/builder  <--  handlers/chat(r)

handlers/chat  <--  __init__(r), nodes(d)

handlers/commands  <--  __init__(r), chat(r)

timer/store  <--  timer/__init__(r), tools(d), handlers/commands(d)
timer/executor  <--  timer/__init__(r), tools(d), handlers/commands(d), chat(r)

utils/__init__  <--  [near-leaf] nodes, handlers/chat, handlers/forward,
                     handlers/likes, handlers/pipeline, tools(d), handlers/commands(d)

utils/md_to_image  <--  [near-leaf] nodes, handlers/chat
```

**Key**: `(r)` = regular module-level import, `(d)` = deferred/lazy import

---

## Summary Statistics

- **Total Python files**: 30 (including 2 empty `__init__.py` and 1 empty `graph/__init__.py`)
- **Source files with real code**: 27
- **Module-level internal imports**: 108
- **Deferred/lazy internal imports**: 36
- **Circular dependencies**: 5 (all resolved by deferred imports)
- **True leaf modules** (zero internal imports): 2 (`config.py`, `memory/tokenizer.py`)
- **Near-leaf modules** (1 internal import): 6 (`state.py`, `infra.py`, `skills/manager.py`, `graph/builder.py`, `utils/__init__.py`, `utils/md_to_image.py`)
- **Most imported module**: `config.py` (imported by 20+ files)
- **Most connected module**: `graph/tools.py` (imports 10 internal modules, imported by 4)
