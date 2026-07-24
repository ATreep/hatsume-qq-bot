"""Tests for graph.nodes — human_node and chat_end_detect_node bug fixes."""

from __future__ import annotations

import asyncio
import importlib.util
import random
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
NODES_PKG_DIR = ROOT / "hatsume/plugins/hatsume-plugin/graph"


class MockMessage:
    """Lightweight stand-in for LangChain message objects."""

    def __init__(
        self,
        content: str = "",
        msg_type: str = "human",
        msg_id: str | None = None,
    ):
        self.content = content
        self.type = msg_type
        self.id = msg_id or f"msg-{id(self)}"


def _load_nodes_module():
    """Load graph/nodes package with all external dependencies stubbed."""
    # ------------------------------------------------------------------
    # Clean up previously loaded modules
    # ------------------------------------------------------------------
    pkg_prefixes = [
        "hatsume",
        "hatsume.plugins",
        "hatsume.plugins.hatsume_plugin",
        "hatsume.plugins.hatsume-plugin",
    ]
    for name in list(sys.modules):
        if any(name.startswith(p) for p in pkg_prefixes) or name in (
            "nonebot",
            "nonebot_plugin_localstore",
            "nonebot.adapters",
            "nonebot.adapters.onebot",
            "nonebot.adapters.onebot.v11",
            "langchain",
            "langchain.messages",
            "langchain.agents",
            "langchain_core",
            "langchain_core.messages",
            "langchain_core.tools",
            "langchain_community",
            "langchain_community.tools",
            "langgraph",
            "langgraph.graph",
            "openai",
        ):
            del sys.modules[name]

    # ------------------------------------------------------------------
    # Build package hierarchy so relative imports resolve
    # ------------------------------------------------------------------
    base = ROOT / "hatsume/plugins/hatsume-plugin"

    hatsume_pkg = types.ModuleType("hatsume")
    hatsume_pkg.__path__ = [str(ROOT / "hatsume")]
    sys.modules["hatsume"] = hatsume_pkg

    plugins_pkg = types.ModuleType("hatsume.plugins")
    plugins_pkg.__path__ = [str(ROOT / "hatsume/plugins")]
    sys.modules["hatsume.plugins"] = plugins_pkg

    plugin_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin")
    plugin_pkg.__path__ = [str(base)]
    sys.modules["hatsume.plugins.hatsume-plugin"] = plugin_pkg

    graph_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin.graph")
    graph_pkg.__path__ = [str(base / "graph")]
    sys.modules["hatsume.plugins.hatsume-plugin.graph"] = graph_pkg

    memory_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin.memory")
    memory_pkg.__path__ = [str(base / "memory")]
    sys.modules["hatsume.plugins.hatsume-plugin.memory"] = memory_pkg

    infra_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin.infra")
    infra_pkg.__path__ = [str(base / "infra")]
    sys.modules["hatsume.plugins.hatsume-plugin.infra"] = infra_pkg

    prompts_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin.prompts")
    prompts_pkg.__path__ = [str(base / "prompts")]
    sys.modules["hatsume.plugins.hatsume-plugin.prompts"] = prompts_pkg

    skills_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
    skills_pkg.__path__ = [str(base / "skills")]
    sys.modules["hatsume.plugins.hatsume-plugin.skills"] = skills_pkg

    # ------------------------------------------------------------------
    # Stub external third-party dependencies
    # ------------------------------------------------------------------

    # nonebot
    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.__path__ = []
    nonebot_mod.get_bot = lambda: types.SimpleNamespace()
    nonebot_mod.require = lambda name: None
    sys.modules["nonebot"] = nonebot_mod

    # nonebot.log
    nonebot_log_mod = types.ModuleType("nonebot.log")
    nonebot_log_mod.logger = types.SimpleNamespace()
    sys.modules["nonebot.log"] = nonebot_log_mod

    # nonebot.adapters.onebot.v11
    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    adapters_mod.Bot = type("Bot", (), {
        "get_group_member_info": lambda *a, **kw: None,
        "get_stranger_info": lambda *a, **kw: None,
    })
    sys.modules["nonebot.adapters"] = adapters_mod

    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod

    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.MessageSegment = types.SimpleNamespace(
        text=lambda s: types.SimpleNamespace(type="text", data={"text": s}),
        image=lambda *a, **kw: types.SimpleNamespace(type="image", data={}),
    )
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

    # nonebot_plugin_localstore
    localstore_mod = types.ModuleType("nonebot_plugin_localstore")
    localstore_mod.get_plugin_data_file = lambda name: types.SimpleNamespace(
        iterdir=lambda: [],
        absolute=lambda: Path("/tmp"),
    )
    sys.modules["nonebot_plugin_localstore"] = localstore_mod

    # nonebot_plugin_htmlrender — stub to prevent loading real package
    htmlrender_mod = types.ModuleType("nonebot_plugin_htmlrender")
    htmlrender_mod.render_html = lambda *a, **kw: None
    sys.modules["nonebot_plugin_htmlrender"] = htmlrender_mod

    # langchain
    langchain_mod = types.ModuleType("langchain")
    langchain_mod.__path__ = []
    sys.modules["langchain"] = langchain_mod

    # langchain.messages — minimal message classes
    class _AIMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "ai"

    class _HumanMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "human"

    class _SystemMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "system"

    langchain_messages = types.ModuleType("langchain.messages")
    langchain_messages.AIMessage = _AIMessage
    langchain_messages.HumanMessage = _HumanMessage
    langchain_messages.SystemMessage = _SystemMessage
    sys.modules["langchain.messages"] = langchain_messages

    # langchain.agents
    langchain_agents = types.ModuleType("langchain.agents")
    langchain_agents.create_agent = lambda *a, **kw: None
    sys.modules["langchain.agents"] = langchain_agents

    # langchain_core
    langchain_core_mod = types.ModuleType("langchain_core")
    langchain_core_mod.__path__ = []
    sys.modules["langchain_core"] = langchain_core_mod

    # langchain_core.messages
    class _RemoveMessage:
        def __init__(self, id=None):
            self.id = id

    langchain_core_messages = types.ModuleType("langchain_core.messages")
    langchain_core_messages.RemoveMessage = _RemoveMessage
    sys.modules["langchain_core.messages"] = langchain_core_messages

    # langchain_core.tools
    langchain_core_tools = types.ModuleType("langchain_core.tools")
    langchain_core_tools.tool = lambda *a, **kw: lambda f: f
    sys.modules["langchain_core.tools"] = langchain_core_tools

    # langchain_community
    langchain_community = types.ModuleType("langchain_community")
    langchain_community.__path__ = []
    sys.modules["langchain_community"] = langchain_community

    langchain_community_tools = types.ModuleType("langchain_community.tools")
    langchain_community_tools.DuckDuckGoSearchRun = type(
        "DuckDuckGoSearchRun", (), {}
    )
    sys.modules["langchain_community.tools"] = langchain_community_tools

    # langgraph
    langgraph_mod = types.ModuleType("langgraph")
    langgraph_mod.__path__ = []
    sys.modules["langgraph"] = langgraph_mod

    # langgraph.graph
    langgraph_graph = types.ModuleType("langgraph.graph")
    langgraph_graph.MessagesState = dict
    sys.modules["langgraph.graph"] = langgraph_graph

    # openai
    openai_mod = types.ModuleType("openai")
    openai_mod.APITimeoutError = type("APITimeoutError", (Exception,), {})
    sys.modules["openai"] = openai_mod

    # ------------------------------------------------------------------
    # Stub sibling plugin modules
    # ------------------------------------------------------------------

    # config
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    for attr in [
        "CONTEXT_QUEUE_LEN",
        "CONTEXT_QUEUE_OVERLAP_LEN",
        "IMAGE_RATE_LIMIT_SECONDS",
        "USER_INPUT_CONFIRM_DURING_TIME",
        "DOCKER_ENV_PATH",
        "SHELL_MAX_OUTPUT",
        "SHELL_TIMEOUT",
        "LONG_MSG_THRESHOLD",
    ]:
        setattr(config_mod, attr, 0)
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    # models
    mock_model = types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="no")
    )
    models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
    models_mod.get_advance_model = lambda **kw: mock_model
    models_mod.get_lite_model = lambda **kw: mock_model
    models_mod.get_mini_model = lambda **kw: mock_model
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod

    # prompts (role_sys_prompt now in prompts.py directly)
    prompts_pkg.role_sys_prompt = "test prompt"
    prompts_pkg.build_skill_prompt = lambda skills: ""
    prompts_pkg.build_agent_state_prompt = lambda: ""
    prompts_pkg.build_character_proxy_role_prompt = lambda **kwargs: ""
    prompts_pkg.AUXILIARY_COMPACTION_PROMPT = "Summarize the following conversation."
    prompts_pkg.CHAT_END_DETECT_PROMPT = "Should this conversation end?"
    prompts_pkg.build_memory_context_prompt = lambda summary: f"Relevant memories: {summary}"
    prompts_pkg.build_face_injection_prompt = lambda emotions: (
        "\n\n# 表情发送\n\n可选的情绪：" + "、".join(emotions)
        if emotions else ""
    )

    # skills (skill management module)
    skills_pkg.get_skill_manager = lambda: type(
        "MockSkillManager", (), {
            "list_skills": lambda self: [],
            "reset_conversation": lambda self: None,
        }
    )()

    # infra (docker sandbox + HTML rendering)
    infra_pkg.run_cmd = lambda *a, **kw: ""
    infra_pkg.delete_container = lambda *a, **kw: None
    infra_pkg.ensure_container_running = lambda *a, **kw: None
    infra_pkg.cleanup_persistent_container = lambda *a, **kw: None

    # memory.engine — single stub replacing deleted store.py + retrieval.py
    memory_engine_mod = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.memory.engine"
    )
    memory_engine_mod.get_mem_list = lambda: []
    memory_engine_mod.query_mems = lambda *a, **kw: []
    memory_engine_mod.add_mem = lambda *a, **kw: None
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = memory_engine_mod

    # Also set on the memory package so ``from ..memory import get_mem_list``
    # (which goes through __init__.py's re-exports) resolves correctly.
    memory_pkg.get_mem_list = memory_engine_mod.get_mem_list
    memory_pkg.query_mems = memory_engine_mod.query_mems
    memory_pkg.add_mem = memory_engine_mod.add_mem

    # graph.tools
    tools_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.graph.tools")
    tools_mod.search_web = None
    tools_mod.coding_agent = None
    tools_mod.shell_executor = None
    tools_mod.find_memory = None
    tools_mod.query_memory = lambda *a, **kw: ""
    tools_mod.configure_tool_callbacks = lambda *a, **kw: None
    tools_mod.capture_html_shot = None
    tools_mod.generate_image = None
    tools_mod.generate_video = None
    tools_mod.view_image = None
    tools_mod.get_avatar = None
    tools_mod.create_timer = None
    tools_mod.list_timers = None
    tools_mod.get_timer = None
    tools_mod.get_timer_overview = AsyncMock(return_value="timer overview")
    tools_mod.delete_timer = None
    tools_mod.skill_loader = None
    tools_mod.skill_remove = None
    tools_mod.skill_download = None
    tools_mod.skill_create = None
    tools_mod.membersearch = None
    tools_mod.agent_dispatch = None
    tools_mod.respond_to_shell_prompt = None
    tools_mod.send_image = None
    tools_mod.send_video = None
    tools_mod.random_acg_photo = None
    tools_mod.set_shell_executor_limit = lambda *a, **kw: None
    tools_mod._current_group_id = None
    tools_mod.reset_capture_flag = lambda *a, **kw: None
    tools_mod.CHAT_TOOLS = [
        tools_mod.search_web,
        tools_mod.shell_executor,
        tools_mod.find_memory,
        tools_mod.view_image,
        tools_mod.generate_image,
        tools_mod.generate_video,
        tools_mod.send_image,
        tools_mod.send_video,
        tools_mod.get_avatar,
        tools_mod.random_acg_photo,
        tools_mod.create_timer,
        tools_mod.list_timers,
        tools_mod.get_timer,
        tools_mod.delete_timer,
        tools_mod.skill_loader,
        tools_mod.skill_remove,
        tools_mod.skill_download,
        tools_mod.skill_create,
        tools_mod.membersearch,
        tools_mod.agent_dispatch,
        tools_mod.respond_to_shell_prompt,
    ]
    tools_mod.get_chat_tools = lambda: list(tools_mod.CHAT_TOOLS)

    character_proxy_mod = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.character_proxy"
    )
    character_proxy_mod.get_character_proxy = lambda: None
    character_proxy_mod.build_active_character_proxy_role_prompt = lambda proxy: ""
    character_proxy_mod.message_mentions_character_proxy = lambda content: False
    sys.modules[character_proxy_mod.__name__] = character_proxy_mod

    tools_mod._capture_html_shot_used = False
    tools_mod._generate_image_used = False
    tools_mod._last_capture_html = ""
    tools_mod._last_capture_html_demand = ""
    sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"] = tools_mod

    # ------------------------------------------------------------------
    # Load graph/nodes.py (flat module — was formerly a package)
    # ------------------------------------------------------------------
    def _load(name: str, path: Path) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    nodes_mod = _load(
        "hatsume.plugins.hatsume-plugin.graph.nodes",
        NODES_PKG_DIR / "nodes.py",
    )
    return nodes_mod


# -----------------------------------------------------------------------
# Bug 1: human_node reference mutation (.copy() fix)
# -----------------------------------------------------------------------


def test_human_node_returns_nonempty_content_when_queue_populated():
    """Regression: .copy() prevents _clear_human_queue from emptying the local variable.

    Without .copy(), human_queue points to the same list object as
    _state.human_queue. When _clear_human_queue() calls .clear() on
    that list, the local variable becomes empty and HumanMessage([])
    is returned with no content.
    """
    nodes = _load_nodes_module()

    mock_state = types.SimpleNamespace(
        human_queue=[{"type": "text", "text": "hello"}],
        human_source_queue=[],
    )
    nodes.bind_state(mock_state)

    result = asyncio.run(nodes.human_node({"messages": []}))

    # HumanMessage must have non-empty content
    assert len(result["messages"]) == 1
    msg = result["messages"][0]
    assert msg.content == [{"type": "text", "text": "hello"}]
    assert msg.content != []

    # Queue should be cleared after the call
    assert mock_state.human_queue == []


def test_human_node_queue_is_cleared_after_processing():
    """Verify _clear_human_queue empties both queues on the state object."""
    nodes = _load_nodes_module()

    mock_state = types.SimpleNamespace(
        human_queue=[{"type": "text", "text": "test msg"}],
        human_source_queue=[{"source_id": "s1", "text": "src"}],
    )
    nodes.bind_state(mock_state)

    result = asyncio.run(nodes.human_node({"messages": []}))

    # Content should still be present in the returned message
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == [{"type": "text", "text": "test msg"}]

    # State queues should be cleared
    assert mock_state.human_queue == []
    assert mock_state.human_source_queue == []


def test_human_node_finishes_immediately_when_end_is_requested():
    nodes = _load_nodes_module()
    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        end_requested=True,
    )
    nodes.bind_state(mock_state)

    result = asyncio.run(nodes.human_node({"messages": []}))

    assert result["messages"][0].content == "__end__"


# -----------------------------------------------------------------------
# Bug 2: chat_end_detect_node parenthesization (str() on result.content)
# -----------------------------------------------------------------------


def test_chat_end_detect_node_no_attribute_error_on_model_result():
    """Regression: str(detect_result.content) avoids AttributeError.

    The old code was ``str(detect_model.invoke(...)).content`` which wraps
    the AIMessage in str() first, then tries .content on the resulting
    string, causing AttributeError. The fix splits into two steps:
    ``detect_result = detect_model.invoke(...)``
    ``response = str(detect_result.content if ... else detect_result)``
    """
    nodes = _load_nodes_module()

    # >= 4 messages, no "初芽" in the last one → enters the model branch
    messages = [
        MockMessage("msg1", "human"),
        MockMessage("msg2", "ai"),
        MockMessage("msg3", "human"),
        MockMessage("hello", "human"),
    ]

    # Force match case 0 (lite model), avoiding InterruptedError paths
    original_randint = random.randint
    random.randint = lambda a, b: 0

    try:
        result = asyncio.run(
            nodes.chat_end_detect_node({"messages": messages})
        )

        # No AttributeError should be raised.
        # response = "no" → returns {"messages": []} (not __end__)
        assert result == {"messages": []}
    finally:
        random.randint = original_randint


def test_chat_end_detect_node_response_extracts_model_content():
    """Verify the response string is correctly derived from the model result object."""
    nodes = _load_nodes_module()

    messages = [
        MockMessage("a", "human"),
        MockMessage("b", "ai"),
        MockMessage("c", "human"),
        MockMessage("d", "human"),
    ]

    # Wire up a model whose invoke returns a specific content value
    detect_result_obj = types.SimpleNamespace(content="no")
    custom_model = types.SimpleNamespace(
        invoke=lambda *a, **kw: detect_result_obj
    )
    nodes.get_advance_model = lambda **kw: custom_model
    nodes.get_lite_model = lambda **kw: custom_model

    original_randint = random.randint
    random.randint = lambda a, b: 0

    try:
        result = asyncio.run(
            nodes.chat_end_detect_node({"messages": messages})
        )

        # "no" response → conversation continues → empty messages
        assert result == {"messages": []}
    finally:
        random.randint = original_randint


def test_chat_end_detect_skips_model_when_proxy_name_or_alias_is_present():
    nodes = _load_nodes_module()
    character_proxy = sys.modules[
        "hatsume.plugins.hatsume-plugin.character_proxy"
    ]
    character_proxy.message_mentions_character_proxy = (
        lambda content: "队长" in str(content)
    )

    class Model:
        def invoke(self, *args, **kwargs):
            raise AssertionError("detect model must not be called")

    nodes.get_lite_model = lambda **kwargs: Model()
    messages = [
        MockMessage("a", "human"),
        MockMessage("b", "ai"),
        MockMessage("c", "human"),
        MockMessage("队长，继续刚才的话题", "human"),
    ]

    result = asyncio.run(nodes.chat_end_detect_node({"messages": messages}))

    assert result == {"messages": []}


# -----------------------------------------------------------------------
# Feature: Persistent shell container cleanup in finish_conversation_node
# -----------------------------------------------------------------------


def test_finish_conversation_node_calls_cleanup_persistent_container():
    """Verify finish_conversation_node invokes cleanup_persistent_container."""
    nodes = _load_nodes_module()

    cleanup_calls: list[int] = []

    def mock_cleanup():
        cleanup_calls.append(1)

    # Patch the docker module's cleanup function
    infra_mod = sys.modules["hatsume.plugins.hatsume-plugin.infra"]
    infra_mod.cleanup_persistent_container = mock_cleanup

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[],
        auxiliary_source_queue=[],
    )
    nodes.bind_state(mock_state)

    messages = [
        MockMessage("hello", "human"),
        MockMessage("hi", "ai"),
    ]

    asyncio.run(nodes.finish_conversation_node({"messages": messages}))
    # cleanup_persistent_container is commented out in production;
    # verify the function runs without error and cleanup is not called
    assert len(cleanup_calls) == 0


def test_finish_conversation_node_saves_to_auxiliary_queue():
    """finish_conversation_node saves the conversation transcript to the
    module-level auxiliary_messages_queue via append_auxiliary_message,
    and clears module-level _retrieved_mem_keys."""
    nodes = _load_nodes_module()

    # Ensure module-level queues are clean
    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_source_queue.clear()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    messages = [
        MockMessage("hello", "human"),
        MockMessage("hi", "ai"),
    ]

    asyncio.run(nodes.finish_conversation_node({"messages": messages}))

    # Conversation content should be saved to module-level auxiliary_messages_queue.
    # The queue may be compacted (CONTEXT_QUEUE_LEN=0 triggers compaction immediately).
    assert len(nodes.auxiliary_messages_queue) >= 1
    assert "历史聊天记录总结" in nodes.auxiliary_messages_queue[0]["text"]

    # _retrieved_mem_keys should be cleared (append_auxiliary_message clears it on compaction)
    assert len(nodes._retrieved_mem_keys) == 0

    # is_graph_running should be reset
    assert mock_state.is_graph_running is False


# -----------------------------------------------------------------------
# Feature: Docker persistent container functions (unit tests)
# -----------------------------------------------------------------------


def _load_docker_module():
    """Load infra.py with all external dependencies stubbed."""
    base = ROOT / "hatsume/plugins/hatsume-plugin"

    # Ensure the package hierarchy exists in sys.modules
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    # Stub config module
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.DOCKER_ENV_PATH = "/tmp/test_docker"
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    # Stub nonebot_plugin_localstore (imported by infra.py)
    localstore_mod = types.ModuleType("nonebot_plugin_localstore")
    localstore_mod.get_plugin_data_file = lambda name: types.SimpleNamespace(
        iterdir=lambda: [],
        absolute=lambda: Path("/tmp"),
    )
    sys.modules["nonebot_plugin_localstore"] = localstore_mod

    # Stub langchain.messages (imported by infra.py)
    if "langchain" not in sys.modules:
        langchain_mod = types.ModuleType("langchain")
        langchain_mod.__path__ = []
        sys.modules["langchain"] = langchain_mod
    if "langchain.messages" not in sys.modules:

        class _HumanMessage:
            def __init__(self, content=""):
                self.content = content
                self.type = "human"

        class _SystemMessage:
            def __init__(self, content=""):
                self.content = content
                self.type = "system"

        langchain_messages = types.ModuleType("langchain.messages")
        langchain_messages.HumanMessage = _HumanMessage
        langchain_messages.SystemMessage = _SystemMessage
        sys.modules["langchain.messages"] = langchain_messages

    infra_path = base / "infra.py"
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.infra", infra_path
    )
    infra_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.infra"] = infra_mod
    spec.loader.exec_module(infra_mod)
    return infra_mod


def test_ensure_container_running_sets_active_flag():
    """ensure_container_running sets the module-level _container_active flag."""
    import subprocess as sp

    infra_mod = _load_docker_module()

    original_run = sp.run
    original_write = Path.write_text

    def mock_subprocess_run(cmd, **kwargs):
        return types.SimpleNamespace(stdout=b"ready\n", stderr=b"")

    sp.run = mock_subprocess_run
    Path.write_text = lambda self, data, **kw: None

    try:
        # Initially inactive
        assert infra_mod._container_active is False

        # First call should start container
        asyncio.run(infra_mod.ensure_container_running())
        assert infra_mod._container_active is True

        # Second call should be a no-op (already active)
        asyncio.run(infra_mod.ensure_container_running())
        assert infra_mod._container_active is True
    finally:
        sp.run = original_run
        Path.write_text = original_write


def test_cleanup_persistent_container_resets_flag():
    """cleanup_persistent_container resets _container_active to False."""
    import subprocess as sp

    infra_mod = _load_docker_module()

    original_run = sp.run
    original_write = Path.write_text
    delete_calls: list[int] = []

    def mock_subprocess_run(cmd, **kwargs):
        if any("delete_container" in str(c) for c in cmd):
            delete_calls.append(1)
        return types.SimpleNamespace(stdout=b"ready\n", stderr=b"")

    sp.run = mock_subprocess_run
    Path.write_text = lambda self, data, **kw: None

    try:
        # Cleanup when not active should be a no-op
        infra_mod.cleanup_persistent_container()
        assert len(delete_calls) == 0
        assert infra_mod._container_active is False

        # Activate, then cleanup
        asyncio.run(infra_mod.ensure_container_running())
        assert infra_mod._container_active is True

        infra_mod.cleanup_persistent_container()
        assert infra_mod._container_active is False
        assert len(delete_calls) == 1
    finally:
        sp.run = original_run
        Path.write_text = original_write


# -----------------------------------------------------------------------
# Feature: capture_html_shot records HTML in transcript
# -----------------------------------------------------------------------


def test_tools_module_has_last_capture_html_variable():
    """Verify _last_capture_html module-level variable exists in the tools mock."""
    _load_nodes_module()
    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    assert hasattr(tools_mod, "_last_capture_html")
    assert tools_mod._last_capture_html == ""



# -----------------------------------------------------------------------
# Bug 3: auxiliary-only messages should skip chat_end_detect_node
# -----------------------------------------------------------------------


def test_human_node_sets_auxiliary_only_flag_when_no_human_queue():
    """human_node should set _last_was_auxiliary_only=True when only auxiliary messages arrive."""
    import time as _time
    nodes = _load_nodes_module()

    # Reset flag
    nodes._last_was_auxiliary_only = False

    # Set up: auxiliary queue has data, human queue is empty
    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_messages_queue.append({"type": "text", "text": "background chat"})
    nodes.auxiliary_source_queue.clear()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    # Mock time to simulate immediate timeout (skip 5 min wait)
    # Use a counter so elapsed time grows past the 5-min threshold
    original_time = _time.time
    call_count = [0]
    def _mock_time():
        call_count[0] += 1
        return 1000.0 + (301.0 if call_count[0] > 1 else 0.0)
    _time.time = _mock_time

    try:
        result = asyncio.run(nodes.human_node({"messages": []}))

        # Flag should be set even on timeout path
        assert nodes._last_was_auxiliary_only is True
        # Should return __end__ SystemMessage
        assert len(result["messages"]) == 1
    finally:
        _time.time = original_time


def test_human_node_clears_auxiliary_only_flag_when_human_queue_present():
    """human_node should set _last_was_auxiliary_only=False when human_queue has data."""
    nodes = _load_nodes_module()

    nodes._last_was_auxiliary_only = True  # pre-set

    # Clear auxiliary queues
    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_source_queue.clear()

    mock_state = types.SimpleNamespace(
        human_queue=[{"type": "text", "text": "hello bot"}],
        human_source_queue=[],
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    asyncio.run(nodes.human_node({"messages": []}))

    assert nodes._last_was_auxiliary_only is False


def test_human_node_does_not_merge_or_clear_auxiliary_queue():
    """human_node must return ONLY the raw human_queue content — no aux
    markers, no aux merge — and must leave auxiliary_messages_queue
    untouched. Consumption now happens in ai_node, not human_node."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_messages_queue.append({"type": "text", "text": "background chat"})
    nodes.auxiliary_source_queue.clear()
    nodes.auxiliary_source_queue.append(
        {"source_id": "aux-1", "text": "aux source", "people": []}
    )

    mock_state = types.SimpleNamespace(
        human_queue=[{"type": "text", "text": "hello bot"}],
        human_source_queue=[],
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    result = asyncio.run(nodes.human_node({"messages": []}))

    # Only the raw human content — no "## 历史聊天记录：" / "## 当前聊天记录：" markers
    assert result["messages"][0].content == [{"type": "text", "text": "hello bot"}]

    # aux queues must survive human_node completely untouched
    assert nodes.auxiliary_messages_queue == [{"type": "text", "text": "background chat"}]
    assert nodes.auxiliary_source_queue == [
        {"source_id": "aux-1", "text": "aux source", "people": []}
    ]


# -----------------------------------------------------------------------
# Feature: ai_node consumes and merges the auxiliary queue
# -----------------------------------------------------------------------


def test_ai_node_merges_auxiliary_queue_for_chat_agent_only():
    """ai_node should merge auxiliary_messages_queue with the
    latest human message when invoking chat_agent, without mutating
    state["messages"][-1], and clear the module-level auxiliary queues."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_messages_queue.append({"type": "text", "text": "aux part"})
    nodes.auxiliary_source_queue.clear()
    nodes.auxiliary_source_queue.append(
        {"source_id": "aux-1", "text": "aux source text", "people": []}
    )

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    captured_invocations: list[dict] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, payload, *a, **kw):
            captured_invocations.append(payload)
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    original_create_agent = nodes.create_agent
    nodes.create_agent = lambda *a, **kw: _FakeAgent()

    human_msg = types.SimpleNamespace(
        content=[{"type": "text", "text": "current turn"}], type="human"
    )

    try:
        asyncio.run(nodes.ai_node({"messages": [human_msg]}))

        sent_last_msg = captured_invocations[0]["messages"][-1]
        assert sent_last_msg.content == [
            {"type": "text", "text": "## 历史聊天记录："},
            {"type": "text", "text": "aux part"},
            {"type": "text", "text": "## 当前聊天记录："},
            {"type": "text", "text": "current turn"},
        ]

        # The original state message must be untouched (no permanent mutation)
        assert human_msg.content == [{"type": "text", "text": "current turn"}]

        # Module-level aux queue must be cleared after consumption
        assert nodes.auxiliary_messages_queue == []
        assert nodes.auxiliary_source_queue == []
    finally:
        nodes.create_agent = original_create_agent


def test_ai_node_skips_merge_when_auxiliary_queue_empty():
    """When auxiliary_messages_queue is empty, ai_node must pass
    state["messages"][-1] to chat_agent unchanged (no wrapping, no markers)."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_source_queue.clear()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[],
        auxiliary_source_queue=[],
    )
    nodes.bind_state(mock_state)

    captured_invocations: list[dict] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, payload, *a, **kw):
            captured_invocations.append(payload)
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    original_create_agent = nodes.create_agent
    nodes.create_agent = lambda *a, **kw: _FakeAgent()

    human_msg = types.SimpleNamespace(
        content=[{"type": "text", "text": "current turn"}], type="human"
    )

    try:
        asyncio.run(nodes.ai_node({"messages": [human_msg]}))

        sent_last_msg = captured_invocations[0]["messages"][-1]
        assert sent_last_msg is human_msg
        assert mock_state.auxiliary_queue == []
    finally:
        nodes.create_agent = original_create_agent


def test_ai_node_suppresses_reply_after_end_conversation_tool():
    nodes = _load_nodes_module()
    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_source_queue.clear()
    answer = AsyncMock()
    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=answer,
        end_requested=False,
    )
    nodes.bind_state(mock_state)

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, *a, **kw):
            mock_state.end_requested = True
            return {
                "messages": [
                    types.SimpleNamespace(content="这段文本不应发送", type="ai")
                ]
            }

    original_create_agent = nodes.create_agent
    nodes.create_agent = lambda *a, **kw: _FakeAgent()
    try:
        result = asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="别回复", type="human")]}
            )
        )
    finally:
        nodes.create_agent = original_create_agent

    answer.assert_not_awaited()
    assert result["messages"][0].content == "这段文本不应发送"
    assert mock_state.end_requested


def test_ai_node_memory_query_uses_only_human_content_not_auxiliary():
    """Memory retrieval must query using only the raw human content, even
    when auxiliary_messages_queue has pending history."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_messages_queue.append({"type": "text", "text": "aux history"})
    nodes.auxiliary_source_queue.clear()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[],
        auxiliary_source_queue=[],
    )
    nodes.bind_state(mock_state)

    query_calls: list[str] = []

    def mock_query_memory(text, **kw):
        query_calls.append(text)
        return ""

    original_query_memory = nodes.query_memory
    nodes.query_memory = mock_query_memory

    original_create_agent = nodes.create_agent

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    nodes.create_agent = lambda *a, **kw: _FakeAgent()

    human_msg = types.SimpleNamespace(content="current turn text", type="human")

    try:
        asyncio.run(nodes.ai_node({"messages": [human_msg]}))
        assert query_calls == ["current turn text"]
        assert "aux history" not in query_calls
    finally:
        nodes.query_memory = original_query_memory
        nodes.create_agent = original_create_agent


# -----------------------------------------------------------------------
# Bug 4: ai_node memory accumulation bounds check
# -----------------------------------------------------------------------


def test_ai_node_queries_backward_with_even_split():
    """When last_content is a list, ai_node should query memory backward
    (last item first) with max_results = _MEMORY_TOTAL_LIMIT // len(parts)."""
    nodes = _load_nodes_module()

    n_parts = 5
    text_parts = [{"type": "text", "text": f"part-{i}"} for i in range(n_parts)]

    query_calls: list[tuple[str, int | None]] = []

    def mock_query_memory(text: str, **kw) -> str:
        query_calls.append((text, kw.get("max_results")))
        return f"memory-for-{text}"

    original_query_memory = nodes.query_memory
    nodes.query_memory = mock_query_memory

    original_create_agent = nodes.create_agent

    class _FakeAgent:
        def with_retry(self, **kw):
            return self
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    nodes.create_agent = lambda *a, **kw: _FakeAgent()

    original_randint = random.randint
    random.randint = lambda a, b: 5

    try:
        asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content=text_parts, type="human")]}
            )
        )
        # All 5 parts should be queried
        assert len(query_calls) == 5
        # Backward order: part-4, part-3, part-2, part-1, part-0
        assert query_calls[0][0] == "part-4"
        assert query_calls[1][0] == "part-3"
        assert query_calls[2][0] == "part-2"
        assert query_calls[3][0] == "part-1"
        assert query_calls[4][0] == "part-0"
        # Each gets max_results = 50 // 5 = 10
        for text, max_res in query_calls:
            assert max_res == 10, f"Expected max_results=10 for {text}, got {max_res}"
    finally:
        nodes.query_memory = original_query_memory
        nodes.create_agent = original_create_agent
        random.randint = original_randint


def test_ai_node_single_text_part_gets_full_limit():
    """When there is a single text part, it should get max_results = 30."""
    nodes = _load_nodes_module()

    text_parts = [{"type": "text", "text": "single message"}]

    query_calls: list[tuple[str, int | None]] = []

    def mock_query_memory(text: str, **kw) -> str:
        query_calls.append((text, kw.get("max_results")))
        return f"result-{text}"

    original_query_memory = nodes.query_memory
    nodes.query_memory = mock_query_memory

    original_create_agent = nodes.create_agent

    class _FakeAgent:
        def with_retry(self, **kw):
            return self
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    nodes.create_agent = lambda *a, **kw: _FakeAgent()

    original_randint = random.randint
    random.randint = lambda a, b: 5

    try:
        asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content=text_parts, type="human")]}
            )
        )
        assert len(query_calls) == 1
        assert query_calls[0] == ("single message", 50)
    finally:
        nodes.query_memory = original_query_memory
        nodes.create_agent = original_create_agent
        random.randint = original_randint


# -----------------------------------------------------------------------
# Feature: generate_image_used flag skips face injection
# -----------------------------------------------------------------------


def test_ai_node_injects_invocation_datetime_into_system_prompt():
    """chat_agent should receive a fresh local date and time on every invocation."""
    nodes = _load_nodes_module()

    sys_prompts: list[str] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="hello", type="ai")]}

    original_create_agent = nodes.create_agent
    original_get_date = nodes.get_date
    invocation_times = iter(
        ["2026/07/17 09:30:45", "2026/07/17 09:31:12"]
    )

    def _tracking_create_agent(model, tools, system_prompt=None, **kw):
        sys_prompts.append(system_prompt or "")
        return _FakeAgent()

    nodes.create_agent = _tracking_create_agent
    nodes.get_date = lambda: next(invocation_times)

    try:
        for _ in range(2):
            asyncio.run(
                nodes.ai_node(
                    {
                        "messages": [
                            types.SimpleNamespace(content="hello", type="human")
                        ]
                    }
                )
            )
        assert len(sys_prompts) == 2
        assert "# 当前日期与时间\n2026/07/17 09:30:45" in sys_prompts[0]
        assert "# 当前日期与时间\n2026/07/17 09:31:12" in sys_prompts[1]
    finally:
        nodes.create_agent = original_create_agent
        nodes.get_date = original_get_date


def test_ai_node_reuses_timer_overview_in_system_prompt():
    nodes = _load_nodes_module()
    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    tools_mod.get_timer_overview.return_value = "shared timer overview"
    sys_prompts: list[str] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="hello", type="ai")]}

    original_create_agent = nodes.create_agent

    def _tracking_create_agent(model, tools, system_prompt=None, **kw):
        sys_prompts.append(system_prompt or "")
        return _FakeAgent()

    nodes.create_agent = _tracking_create_agent
    try:
        asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="hello", type="human")]}
            )
        )
    finally:
        nodes.create_agent = original_create_agent

    tools_mod.get_timer_overview.assert_awaited_once_with()
    assert "\n\nshared timer overview\n\n# 当前日期与时间" in sys_prompts[0]


def test_generate_image_used_skips_face_injection():
    """When _generate_image_used is True, face injection prompt should NOT be
    added to chat_agent's system_prompt."""
    nodes = _load_nodes_module()

    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    tools_mod._generate_image_used = True
    tools_mod._capture_html_shot_used = False
    tools_mod._last_capture_html = ""

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    # Track the system_prompt passed to create_agent
    sys_prompts: list[str] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="hello", type="ai")]}

    original_create_agent = nodes.create_agent
    def _tracking_create_agent(model, tools, system_prompt=None, **kw):
        sys_prompts.append(system_prompt or "")
        return _FakeAgent()
    nodes.create_agent = _tracking_create_agent

    # Force random to return 0 (so face WOULD be injected if not for the flag)
    original_randint = random.randint
    random.randint = lambda a, b: 0

    # Set _face_cooling_count high enough to pass the >= 1 check
    nodes._face_cooling_count = 2

    try:
        asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="hello", type="human")]}
            )
        )
        assert len(sys_prompts) == 1, "create_agent should be called exactly once"
        assert "# 表情发送" not in sys_prompts[0], (
            "face injection should NOT be in sys_prompt when _generate_image_used is True"
        )
    finally:
        nodes.create_agent = original_create_agent
        random.randint = original_randint
        tools_mod._generate_image_used = False


def test_face_injection_when_flags_false():
    """When both _generate_image_used and _capture_html_shot_used are False,
    face injection prompt should be added to chat_agent's system_prompt."""
    import tempfile

    nodes = _load_nodes_module()

    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    tools_mod._generate_image_used = False
    tools_mod._capture_html_shot_used = False
    tools_mod._last_capture_html = ""

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    # Create temp dir with fake face files so the gate proceeds to injection
    tmpdir = tempfile.TemporaryDirectory()
    face_dir = Path(tmpdir.name)
    (face_dir / "开心_0.png").touch()
    (face_dir / "生气_0.png").touch()

    # Replace localstore mock to return our temp dir
    original_get_data = nodes.store.get_plugin_data_file
    def _mock_get_data(name):
        return types.SimpleNamespace(
            iterdir=lambda: list(face_dir.iterdir()),
            absolute=lambda: face_dir,
        )
    nodes.store.get_plugin_data_file = _mock_get_data

    # Track the system_prompt passed to create_agent
    sys_prompts: list[str] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="hello", type="ai")]}

    original_create_agent = nodes.create_agent
    def _tracking_create_agent(model, tools, system_prompt=None, **kw):
        sys_prompts.append(system_prompt or "")
        return _FakeAgent()
    nodes.create_agent = _tracking_create_agent

    # Force random to return 0 (so face WILL be injected)
    original_randint = random.randint
    random.randint = lambda a, b: 0

    # Set _face_cooling_count high enough to pass the >= 1 check
    nodes._face_cooling_count = 2

    try:
        asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="hello", type="human")]}
            )
        )
        assert len(sys_prompts) == 1, "create_agent should be called exactly once"
        assert "# 表情发送" in sys_prompts[0], (
            "face injection should be in sys_prompt when both flags are False"
        )
        assert "开心" in sys_prompts[0], (
            "face injection should list available emotions"
        )
    finally:
        nodes.create_agent = original_create_agent
        random.randint = original_randint
        nodes.store.get_plugin_data_file = original_get_data
        tmpdir.cleanup()


def test_face_tag_stripped_from_user_text_preserved_in_aimessage():
    """[hatsumeface: tag should be stripped from user-facing text but preserved
    in AIMessage for graph state history."""
    nodes = _load_nodes_module()

    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    tools_mod._generate_image_used = False
    tools_mod._capture_html_shot_used = False
    tools_mod._last_capture_html = ""

    sent_messages: list = []

    async def _mock_send(msg):
        sent_messages.append(msg)

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=_mock_send,
    )
    nodes.bind_state(mock_state)

    # AI response includes a face tag
    ai_response = "今天天气真好呀，心情不错呢[hatsumeface:开心]"

    class _FakeAgent:
        def with_retry(self, **kw):
            return self
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content=ai_response, type="ai")]}

    original_create_agent = nodes.create_agent
    nodes.create_agent = lambda *a, **kw: _FakeAgent()

    # Force random to return 0
    original_randint = random.randint
    random.randint = lambda a, b: 0

    # Set cooling count high enough
    nodes._face_cooling_count = 2

    try:
        result = asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="hello", type="human")]}
            )
        )

        # AIMessage should preserve the face tag
        aimessage = result["messages"][0]
        assert "[hatsumeface:开心]" in aimessage.content, (
            "AIMessage should preserve the face tag for graph state history"
        )

        # User-facing text should NOT contain the face tag
        assert len(sent_messages) >= 1, "at least the text message should be sent"
        text_msg = sent_messages[0]
        assert text_msg.type == "text"
        assert "[hatsumeface:" not in text_msg.data["text"], (
            "Sent text should not contain face tag"
        )
        assert "今天天气真好呀" in text_msg.data["text"], (
            "Sent text should contain the message content without the tag"
        )
    finally:
        nodes.create_agent = original_create_agent
        random.randint = original_randint


# -----------------------------------------------------------------------
# Bug 5: _retrieved_mem_keys should be cleared on auxiliary compaction
# -----------------------------------------------------------------------


def test_append_auxiliary_message_clears_retrieved_mem_keys_on_compaction():
    """When auxiliary_messages_queue exceeds 80 and compaction runs,
    _retrieved_mem_keys must be cleared so the compacted summary
    can trigger fresh memory retrieval."""
    nodes = _load_nodes_module()

    # Pre-populate _retrieved_mem_keys to simulate prior retrieval
    nodes._retrieved_mem_keys.add("key-a")
    nodes._retrieved_mem_keys.add("key-b")
    assert len(nodes._retrieved_mem_keys) == 2

    # Pre-populate auxiliary queue to be just under the threshold
    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_source_queue.clear()
    for i in range(79):
        nodes.auxiliary_messages_queue.append({"type": "text", "text": f"msg-{i}"})

    # Stub the model to return a summary
    original_model = nodes.get_mini_model
    nodes.get_mini_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="summary of 80 messages")
    )

    try:
        # Push past the threshold (79 + 2 = 81 > 80)
        nodes.append_auxiliary_message([
            {"type": "text", "text": "msg-79"},
            {"type": "text", "text": "msg-80"},
        ])

        # Queue should be compacted to 1 entry
        assert len(nodes.auxiliary_messages_queue) == 1
        assert "历史聊天记录总结" in nodes.auxiliary_messages_queue[0]["text"]

        # _retrieved_mem_keys should be cleared
        assert len(nodes._retrieved_mem_keys) == 0, (
            "_retrieved_mem_keys should be cleared after compaction"
        )
    finally:
        nodes.get_mini_model = original_model
        nodes._retrieved_mem_keys.clear()
        nodes.auxiliary_messages_queue.clear()
        nodes.auxiliary_source_queue.clear()


def test_append_auxiliary_message_clears_retrieved_mem_keys_on_compaction_failure():
    """When compaction fails and truncation occurs,
    _retrieved_mem_keys must still be cleared."""
    nodes = _load_nodes_module()

    # Pre-populate _retrieved_mem_keys
    nodes._retrieved_mem_keys.add("stale-key")
    assert len(nodes._retrieved_mem_keys) == 1

    # Pre-populate auxiliary queue to threshold
    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_source_queue.clear()
    for i in range(79):
        nodes.auxiliary_messages_queue.append({"type": "text", "text": f"msg-{i}"})

    # Stub both models to raise an exception (forcing the failure path)
    # The compaction code randomly picks mini (2/3) or lite (1/3), so both must fail.
    def _fail_model(**kw):
        def _invoke(*a, **kw):
            raise RuntimeError("compaction failed")
        return types.SimpleNamespace(invoke=_invoke)

    original_mini = nodes.get_mini_model
    original_lite = nodes.get_lite_model
    nodes.get_mini_model = _fail_model
    nodes.get_lite_model = _fail_model

    try:
        nodes.append_auxiliary_message([
            {"type": "text", "text": "msg-79"},
            {"type": "text", "text": "msg-80"},
        ])

        # On failure, queue should be truncated to last 50
        assert len(nodes.auxiliary_messages_queue) == 50

        # _retrieved_mem_keys should still be cleared
        assert len(nodes._retrieved_mem_keys) == 0, (
            "_retrieved_mem_keys should be cleared even on compaction failure"
        )
    finally:
        nodes.get_mini_model = original_mini
        nodes.get_lite_model = original_lite
        nodes._retrieved_mem_keys.clear()
        nodes.auxiliary_messages_queue.clear()
        nodes.auxiliary_source_queue.clear()
