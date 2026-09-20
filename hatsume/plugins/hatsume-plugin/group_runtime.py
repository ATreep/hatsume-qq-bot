"""Per-group runtime ownership and task-local binding."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, overload

from .state import ConversationState


def validate_group_id(group_id: int) -> int:
    """Return a normalized positive QQ group ID."""
    if isinstance(group_id, bool) or not isinstance(group_id, int):
        raise ValueError("group_id must be a positive integer")
    if group_id <= 0:
        raise ValueError("group_id must be a positive integer")
    return group_id


@dataclass(slots=True)
class GroupRuntime:
    """All mutable conversation and tool state owned by one QQ group."""

    group_id: int
    conversation: ConversationState = field(init=False)
    bot: Any = None
    graph_start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    auxiliary_messages_queue: list[dict] = field(default_factory=list)
    auxiliary_source_queue: list[dict] = field(default_factory=list)
    last_was_auxiliary_only: bool = False
    last_was_system_trigger: bool = False

    generate_video_used: bool = False
    send_image_count: int = 0
    send_video_count: int = 0

    character_proxy: Any = None
    character_proxy_termination_handle: asyncio.TimerHandle | None = None
    skill_manager: Any = None
    agent_tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    is_video_rate_limited_callback: Any = None
    update_video_time_callback: Any = None
    is_generate_image_rate_limited_callback: Any = None
    update_generate_image_time_callback: Any = None
    end_conversation_callback: Any = None

    def __post_init__(self) -> None:
        self.group_id = validate_group_id(self.group_id)
        self.conversation = ConversationState(group_id=self.group_id)
        self.reset_tool_callbacks()

    def reset_tool_callbacks(self) -> None:
        state = self.conversation
        self.is_video_rate_limited_callback = state.is_video_rate_limited
        self.update_video_time_callback = state.update_video_time
        self.is_generate_image_rate_limited_callback = (
            state.is_generate_image_rate_limited
        )
        self.update_generate_image_time_callback = state.update_generate_image_time
        self.end_conversation_callback = state.request_end_conversation


_current_runtime: ContextVar[GroupRuntime | None] = ContextVar(
    "hatsume_current_group_runtime",
    default=None,
)


@contextmanager
def bind_group_runtime(runtime: GroupRuntime) -> Iterator[GroupRuntime]:
    """Bind a runtime for the current synchronous/async task context."""
    token: Token[GroupRuntime | None] = _current_runtime.set(runtime)
    try:
        yield runtime
    finally:
        _current_runtime.reset(token)


def set_current_group_runtime(runtime: GroupRuntime | None) -> None:
    """Compatibility setter for tests and legacy synchronous entry points."""
    _current_runtime.set(runtime)


@overload
def get_current_group_runtime(*, required: Literal[True] = True) -> GroupRuntime: ...


@overload
def get_current_group_runtime(*, required: Literal[False]) -> GroupRuntime | None: ...


def get_current_group_runtime(*, required: bool = True) -> GroupRuntime | None:
    runtime = _current_runtime.get()
    if runtime is None and required:
        raise RuntimeError("group runtime is not bound")
    return runtime


@overload
def get_current_group_id(*, required: Literal[True] = True) -> int: ...


@overload
def get_current_group_id(*, required: Literal[False]) -> int | None: ...


def get_current_group_id(*, required: bool = True) -> int | None:
    runtime = get_current_group_runtime(required=required)
    return runtime.group_id if runtime is not None else None


class GroupRuntimeRegistry:
    """Own the stable process-local runtime for every observed QQ group."""

    def __init__(self) -> None:
        self._runtimes: dict[int, GroupRuntime] = {}
        self._group_bots: dict[int, Any] = {}

    def get_or_create(self, group_id: int) -> GroupRuntime:
        normalized = validate_group_id(group_id)
        runtime = self._runtimes.get(normalized)
        if runtime is None:
            runtime = GroupRuntime(normalized)
            runtime.bot = self._group_bots.get(normalized)
            self._runtimes[normalized] = runtime
        return runtime

    def bind_bot(self, group_id: int, bot: Any) -> GroupRuntime:
        """Remember the connected Bot that can deliver to one group."""
        normalized = validate_group_id(group_id)
        self._group_bots[normalized] = bot
        runtime = self.get_or_create(normalized)
        runtime.bot = bot
        return runtime

    def get_bot(self, group_id: int) -> Any:
        """Return the Bot explicitly associated with the target group."""
        normalized = validate_group_id(group_id)
        runtime = self._runtimes.get(normalized)
        if runtime is not None and runtime.bot is not None:
            return runtime.bot
        bot = self._group_bots.get(normalized)
        if bot is None:
            raise LookupError(f"no connected bot is registered for group {normalized}")
        return bot

    async def discover_bot_groups(self, bot: Any) -> tuple[int, ...]:
        """Refresh group-to-Bot routes from OneBot's group list."""
        try:
            groups = await bot.get_group_list()
        except Exception as exc:
            print(f"Unable to discover groups for connected bot: {exc}")
            return ()

        if isinstance(groups, dict):
            groups = groups.get("data", [])
        discovered: list[int] = []
        for group in groups if isinstance(groups, list) else []:
            raw_group_id = (
                group.get("group_id")
                if isinstance(group, dict)
                else getattr(group, "group_id", None)
            )
            if raw_group_id is None:
                continue
            try:
                group_id = validate_group_id(int(raw_group_id))
            except (TypeError, ValueError):
                continue
            self._group_bots[group_id] = bot
            runtime = self._runtimes.get(group_id)
            if runtime is not None:
                runtime.bot = bot
            discovered.append(group_id)
        return tuple(discovered)

    def unbind_bot(self, bot: Any) -> tuple[int, ...]:
        """Remove and return routes owned by a disconnected Bot."""
        group_ids = [
            group_id
            for group_id, registered in self._group_bots.items()
            if registered is bot
        ]
        for group_id in group_ids:
            self._group_bots.pop(group_id, None)
            runtime = self._runtimes.get(group_id)
            if runtime is not None and runtime.bot is bot:
                runtime.bot = None
        return tuple(sorted(group_ids))

    def get_existing(self, group_id: int) -> GroupRuntime | None:
        return self._runtimes.get(validate_group_id(group_id))

    def routed_group_ids(self) -> tuple[int, ...]:
        """Return group IDs that currently have an explicit Bot route."""
        return tuple(sorted(self._group_bots))

    def values(self) -> tuple[GroupRuntime, ...]:
        return tuple(self._runtimes.values())

    async def shutdown(self) -> None:
        graph_tasks: list[asyncio.Task[Any]] = []
        for runtime in self.values():
            state = runtime.conversation
            if state._debounce_cancel is not None:
                state._debounce_cancel.set()
                state._debounce_cancel = None
            if runtime.character_proxy_termination_handle is not None:
                runtime.character_proxy_termination_handle.cancel()
                runtime.character_proxy_termination_handle = None
            task = state._graph_task
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                graph_tasks.append(task)

        if graph_tasks:
            await asyncio.gather(*graph_tasks, return_exceptions=True)

        try:
            from .graph.agents import shutdown_all_agents

            await shutdown_all_agents()
        except Exception as exc:
            print(f"Group runtime Agent shutdown failed: {exc}")

        try:
            from .infra import shutdown_all_containers

            await shutdown_all_containers()
        except Exception as exc:
            print(f"Group runtime container shutdown failed: {exc}")
        finally:
            self._runtimes.clear()
            self._group_bots.clear()
            set_current_group_runtime(None)

    def clear_for_tests(self) -> None:
        """Drop registry entries after tests have cleaned their tasks."""
        self._runtimes.clear()
        self._group_bots.clear()
        set_current_group_runtime(None)


group_runtime_registry = GroupRuntimeRegistry()
