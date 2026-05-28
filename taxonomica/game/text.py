"""Text chunking helpers for progressive game reveals."""

from __future__ import annotations

import re


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences for progressive reveal."""
    pattern = r"(?<=[.!?])\s+(?=[A-Z])"
    sentences = re.split(pattern, text)
    result = [sentence.strip() for sentence in sentences if sentence.strip()]

    if not result and text.strip():
        result = [text.strip()]

    return result


def split_into_lines(text: str, line_width: int = 90) -> list[str]:
    """Split text into wrapped lines for progressive reveal."""
    words = text.split()
    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_len = len(word)
        if current_length + word_len + (1 if current_line else 0) > line_width:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_length = word_len
        else:
            current_line.append(word)
            current_length += word_len + (1 if len(current_line) > 1 else 0)

    if current_line:
        lines.append(" ".join(current_line))

    return lines
