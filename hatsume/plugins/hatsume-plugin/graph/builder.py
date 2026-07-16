"""Construct and compile the LangGraph conversation state machine."""

from __future__ import annotations

from langgraph.graph import START, END, StateGraph, MessagesState

from .nodes import ai_node, human_node, chat_end_detect_node, finish_conversation_node
from .nodes import _last_was_auxiliary_only


def _human_condition(state: MessagesState) -> str:
    if state["messages"][-1].content == "__end__":
        return "__end__"
    return "continue"


def _chat_end_detect_condition(state: MessagesState) -> str:
    if state["messages"][-1].content == "__end__":
        return "__end__"
    if _last_was_auxiliary_only:
        return "auxiliary_only"
    return "continue"


def build_graph():
    builder = StateGraph(MessagesState)

    builder.add_node("chat_llm", ai_node)
    builder.add_node("human", human_node)
    builder.add_node("chat_end_detect", chat_end_detect_node)
    builder.add_node("finish", finish_conversation_node)

    builder.add_edge(START, "human")
    builder.add_conditional_edges(
        "human",
        _human_condition,
        {"continue": "chat_end_detect", "__end__": "finish"},
    )
    builder.add_conditional_edges(
        "chat_end_detect",
        _chat_end_detect_condition,
        {"continue": "chat_llm", "auxiliary_only": "chat_llm", "__end__": "finish"},
    )
    builder.add_edge("chat_llm", "human")
    builder.add_edge("finish", END)

    return builder.compile()


graph = build_graph()
