"""Render outgoing bot message segments into stored record text.

Kept free of heavy imports so it can be unit-tested in isolation and imported
eagerly by the dialogue handler.
"""

from __future__ import annotations

from typing import Any


def _segment_type(seg: Any) -> str | None:
    return getattr(seg, "type", None)


def build_bot_record_content(
    segments: list[Any],
    image_paths: list[str | None],
) -> str:
    """Render sent segments into record text with inline image paths.

    Text segments are concatenated; image segments become
    ``![图片](sandbox_path)`` markdown using the cached path when one was
    available; video segments become a ``[视频]`` placeholder. Segments whose
    type is not recorded (at, face, reply, ...) are skipped.
    """
    parts: list[str] = []
    image_index = 0
    for segment in segments:
        segment_type = _segment_type(segment)
        if segment_type == "image":
            path = (
                image_paths[image_index]
                if image_index < len(image_paths)
                else None
            )
            image_index += 1
            if path:
                parts.append(f" ![图片]({path}) ")
            continue
        if segment_type == "text":
            data = getattr(segment, "data", None)
            if isinstance(data, dict):
                parts.append(str(data.get("text", "")))
            continue
        if segment_type == "video":
            parts.append("[视频]")
    return "".join(parts).strip()
