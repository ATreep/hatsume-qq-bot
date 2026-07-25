"""Conversation state and shared type definitions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from .config import (
    CONTEXT_QUEUE_OVERLAP_LEN,
    VIDEO_RATE_LIMIT_SECONDS,
    GENERATE_IMAGE_RATE_LIMIT_SECONDS,
)




# ---------------------------------------------------------------------------
# Conversation state
# ---------------------------------------------------------------------------
@dataclass
class ConversationState:
    """Encapsulates all mutable conversation state."""

    is_chatting: bool = False
    chat_peers: set[str] = field(default_factory=set)
    end_requested: bool = False

    # Message queues
    idle_queue: list[dict] = field(default_factory=list)
    idle_source_queue: list[dict] = field(default_factory=list)
    pending_queue: list[dict] = field(default_factory=list)
    pending_source_queue: list[dict] = field(default_factory=list)
    human_queue: list[dict] = field(default_factory=list)
    human_source_queue: list[dict] = field(default_factory=list)

    # Timing
    last_video_time: float = 0
    last_generate_image_time: float = 0

    # Debounce
    _debounce_cancel: asyncio.Event | None = None

    # Graph state
    is_graph_running: bool = False
    _graph_task: Any = None  # asyncio.Task | None — set in start_new_conversation
    face_cooling_count: int = 0
    current_query_user_id: int | None = None

    # Memory recording
    transcript: list[dict] = field(default_factory=list)
    source_map: dict[str, list[dict]] = field(default_factory=dict)
    # Callbacks (set by handlers)
    ai_answer: Callable[..., Coroutine[Any, Any, None]] | None = None

    def activate_chat(self, session_id: str | None = None) -> None:
        """Mark the conversation as active — sets the is_chatting flag and
        registers the peer. Does NOT start LangGraph execution; callers that
        need to actually run the AI must use start_new_conversation() instead."""
        self.is_chatting = True
        self.end_requested = False
        if session_id:
            self.chat_peers.add(session_id)

    def end_conversation(self) -> None:
        self.is_chatting = False
        self.chat_peers.clear()
        self.end_requested = False

    def request_end_conversation(self) -> None:
        """Stop message delivery and ask the running graph to finish."""
        self.end_conversation()
        self.end_requested = True

    def is_video_rate_limited(self) -> bool:
        return time.time() - self.last_video_time < VIDEO_RATE_LIMIT_SECONDS

    def is_generate_image_rate_limited(self) -> bool:
        return time.time() - self.last_generate_image_time < GENERATE_IMAGE_RATE_LIMIT_SECONDS

    def flush_idle_to_auxiliary(self) -> tuple[list[dict], list[dict]]:
        messages = self.idle_queue.copy()
        sources = self.idle_source_queue.copy()
        self.idle_queue = self.idle_queue[-CONTEXT_QUEUE_OVERLAP_LEN:]
        self.idle_source_queue = self.idle_source_queue[-CONTEXT_QUEUE_OVERLAP_LEN:]
        return messages, sources

    def flush_pending(self) -> tuple[list[dict], list[dict]]:
        messages = self.pending_queue.copy()
        sources = self.pending_source_queue.copy()
        self.pending_queue.clear()
        self.pending_source_queue.clear()
        return messages, sources
