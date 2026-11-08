"""Stage 3: Chunk. Structure-aware, with overlap."""

from __future__ import annotations

import hashlib
import json
import re

from .models import Chunk, Document
from .text import token_count, token_slice


def _heading(block: str, ocr: bool) -> str | None:
    markdown = re.fullmatch(r"#{1,6}\s+([^\n]+)", block)
    candidate = markdown.group(1) if markdown else block
    if re.search(r"www\.|https?://|@", candidate, re.I) or not re.search(r"[A-Za-z]", candidate):
        return None
    if markdown:
        return candidate
    if re.search(r"\d", block) and not re.match(r"^\d+[.)]\s+", block):
        return None  # Numeric table/threshold rows are evidence, not fontless headings.
    if not ocr or "\n" in block or len(block) > 100 or block.endswith((".", ";", "!", "?")):
        return None
    if re.match(r"^\d+[.)]\s+", block) and len(block.split()) <= 14:
        return block
    words = [word for word in re.findall(r"[A-Za-z]+", block)
             if word.lower() not in {"of", "and", "the", "for", "in", "to", "a", "an", "on", "with", "from", "under", "as"}]
    if words and len(words) <= 10 and sum(word[0].isupper() for word in words) / len(words) >= 0.8:
        return block.rstrip(":")
    return None


def _pieces(block: str, limit: int) -> list[str]:
    if token_count(block) <= limit:
        return [block]
    if block.startswith("|") and "\n" in block:
        rows = block.splitlines()
        header = "\n".join(rows[:2])
        room = limit - token_count(header)
        if room >= 8:
            result = []
            current = header
            for row in rows[2:]:
                if token_count(row) > room:
                    # A single oversized row cannot be kept intact under the hard cap.
                    if current != header:
                        result.append(current)
                    result.extend(header + "\n" + token_slice(row, i, i + room)
                                  for i in range(0, token_count(row), room))
                    current = header
                elif token_count(current + "\n" + row) > limit:
                    result.append(current)
                    current = header + "\n" + row
                else:
                    current += "\n" + row
            if current != header:
                result.append(current)
            return result
    result = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", block):
        count = token_count(sentence)
        result.extend(token_slice(sentence, i, i + limit) for i in range(0, count, limit))
    return result


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk under
    `size` tokens, with `overlap` tokens shared between neighbours. Every chunk keeps
    the section heading it sits under, its page, doc_version and superseded."""
    if size < 16 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be >= 16 and 0 <= overlap < size")
    chunks: list[Chunk] = []
    parent = "Document"
    for page in doc.pages:
        groups: list[tuple[str, list[str]]] = []
        section = parent
        for block in re.split(r"\n\s*\n", page.text):
            block = block.strip()
            if not block:
                continue
            heading = _heading(block, page.ocr)
            if heading:
                parent = heading
                section = parent
                continue
            clause = re.match(r"^(\d+\.\d+(?:\.\d+)*)\s+", block)
            if clause:
                section = f"{clause.group(1)} {parent}"
            if not groups or groups[-1][0] != section:
                groups.append((section, []))
            groups[-1][1].append(block)
        for title, blocks in groups:
            title = token_slice(title, 0, min(40, size // 4))
            prefix = title + "\n\n"
            budget = size - token_count(prefix)
            shared = min(overlap, budget // 2)
            current = ""

            def emit(text: str) -> None:
                content = prefix + text
                identity = json.dumps([
                    doc.source, doc.doc_version, page.page, title, len(chunks), content,
                ], ensure_ascii=False)
                identifier = hashlib.sha256(identity.encode()).hexdigest()[:32]
                chunks.append(Chunk(identifier, content, doc.source, title, page.page,
                                    doc.doc_version, doc.superseded))

            for block in blocks:
                for piece in _pieces(block, max(1, budget - shared)):
                    candidate = (current + "\n\n" + piece).strip()
                    if current and token_count(candidate) > budget:
                        emit(current)
                        tail = token_slice(current, -shared) if shared else ""
                        while tail and token_count(tail + "\n\n" + piece) > budget:
                            tail = token_slice(tail, 1)
                        current = (tail + "\n\n" + piece).strip()
                    else:
                        current = candidate
            if current:
                emit(current)
    return chunks
