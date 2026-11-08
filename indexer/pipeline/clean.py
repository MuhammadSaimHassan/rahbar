"""Stage 2: Clean. Remove artefacts without destroying structure."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from .models import Document, Page


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\u00ad", "").replace("\u200b", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"(?<=\w)-\n(?=\w)", "-", text)
    for ligature, letters in {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}.items():
        text = text.replace(ligature, letters)
    return "\n".join(re.sub(r"[\t\xa0 ]+", " ", line).strip() for line in text.splitlines())


def _margin_key(line: str) -> str:
    return re.sub(r"^#+\s*", "", line).strip().casefold()


def clean(doc: Document) -> Document:
    """Strip headers and footers that repeat on every page; keep headings and
    section boundaries, because chunking and citations depend on them."""
    texts = [_normalise(page.text) for page in doc.pages]
    margins: Counter[str] = Counter()
    for text in texts:
        lines = [line for line in text.splitlines() if line]
        margins.update({_margin_key(line) for line in lines[:2] + lines[-2:]})
    threshold = max(3, math.ceil(sum(bool(t.strip()) for t in texts) / 2))
    repeated = {line for line, count in margins.items() if count >= threshold}
    pages = []
    for page, text in zip(doc.pages, texts):
        lines = text.splitlines()
        nonempty = [i for i, line in enumerate(lines) if line]
        edges = set(nonempty[:2] + nonempty[-2:])
        kept = []
        for i, line in enumerate(lines):
            number = re.fullmatch(r"(?:page\s+)?(\d+)(?:\s+of\s+\d+)?", line, re.I)
            page_number = bool(number and 1 <= int(number.group(1)) <= len(doc.pages))
            page_number = page_number or bool(re.fullmatch(r"[ivxlcdm]+", line, re.I))
            structured = line.startswith(("|", "- ", "•")) or re.match(r"^\d+\.\d+", line)
            if i in edges and not structured and (page_number or _margin_key(line) in repeated):
                # Repeated mixed-case headings remain useful section boundaries.
                boilerplate = re.search(r"handbook|academic rules and regulations|national university|www\.", line, re.I)
                if not (line.startswith("#") and not line.lstrip("# ").isupper()
                        and not page_number and not boilerplate):
                    continue
            kept.append(line)
        # Join wrapped prose; leave headings, tables and numbered/list boundaries visible.
        blocks: list[str] = []
        prose: list[str] = []
        for line in kept + [""]:
            boundary = not line or line.startswith(("#", "|", "- ", "•")) or re.match(r"^\d+(?:\.\d+)*[.)]?\s", line)
            if boundary and prose:
                blocks.append(" ".join(prose))
                prose = []
            if not line:
                continue
            if line.startswith(("#", "|")):
                blocks.append(line)
            else:
                prose.append(line)
        result = "\n\n".join(blocks)
        # Adjacent table rows stay a single structured block.
        result = re.sub(r"(?<=\|)\n\n(?=\|)", "\n", result)
        pages.append(Page(page.source, page.page, result.strip(), page.ocr))
    return Document(doc.source, doc.doc_version, doc.superseded, pages)
