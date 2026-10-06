"""Small shared helpers for TypeSafe-compatible System One requests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_systemone_body(
    model_name: str,
    state: Any,
    questions: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the stable request body accepted by the System One endpoint."""
    return {"model": model_name, "state": state, "questions": dict(questions)}


async def post_systemone(
    model: Any,
    state: Any,
    questions: Mapping[str, Any],
) -> Any:
    """Send all typed questions in one System One forward pass."""
    return await model.root_async_client.post(
        "/decisions",
        cast_to=object,
        body=build_systemone_body(
            getattr(model, "model_name", ""), state, questions
        ),
    )


def get_choice_answer(response: Any, question_id: str) -> Mapping[str, Any] | None:
    """Extract a typed answer from mapping, SDK, or HTTP-style responses."""
    answers = (
        response.get("answers")
        if isinstance(response, Mapping)
        else getattr(response, "answers", None)
    )
    if not isinstance(answers, Mapping):
        return None
    answer = answers.get(question_id)
    if isinstance(answer, Mapping):
        return answer
    model_dump = getattr(answer, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, Mapping) else None
    answer_dict = getattr(answer, "__dict__", None)
    return answer_dict if isinstance(answer_dict, Mapping) else None
