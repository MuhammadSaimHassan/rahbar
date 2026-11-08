"""Deterministic lexical token accounting shared by chunking and reports.

These tokens are words/punctuation, not the embedding model's BPE tokens.
Ollama is asked to reject context overflow rather than silently truncate.
"""

from __future__ import annotations

import re

TOKEN = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]", re.UNICODE)


def token_count(text: str) -> int:
    return len(TOKEN.findall(text))


def token_slice(text: str, start: int, end: int | None = None) -> str:
    spans = list(TOKEN.finditer(text))
    selected = spans[start:end]
    return text[selected[0].start():selected[-1].end()] if selected else ""
