"""Chinese text tokenization with POS tagging for BM25 indexing."""

from __future__ import annotations

import jieba.posseg as pseg

POS_WEIGHT: dict[str, float] = {
    "n": 3.0, "v": 2.0, "vn": 2.5, "a": 1.0, "f": 2.5,
    "g": 2.0, "h": 2.0, "i": 2.0, "j": 2.5, "k": 2.0,
    "l": 2.0, "m": 2.3, "nr": 3.0, "ns": 3.0, "nt": 3.0,
    "nz": 3.0, "s": 2.0, "t": 2.3, "x": 2.5, "z": 2.5, "un": 2.5,
}

KEEP_POS: set[str] = set(POS_WEIGHT.keys())


def tokenize_with_pos(text: str) -> list[tuple[str, str]]:
    """Tokenize text using jieba POS tagging.

    Returns (word, pos_tag) pairs, filtering for meaningful POS tags
    and words longer than 1 character.
    """
    return [
        (w.word, w.flag)
        for w in pseg.cut(text)
        if w.flag[0] in KEEP_POS and len(w.word.strip()) > 1
    ]
