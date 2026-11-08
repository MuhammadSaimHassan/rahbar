"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import dataclass, field
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .models import Document, Page


def table_text(rows: list[list[Any]]) -> str:
    """Keep cells in their original row/column relationships."""
    normal = [[" ".join(str(cell if cell is not None else "").split()).replace("|", "\\|")
               for cell in row] for row in rows]
    normal = [row for row in normal if any(row)]
    if not normal:
        return ""
    width = max(map(len, normal))
    lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in normal]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def _pdf_text(page: Any) -> str:
    tables = page.find_tables()
    boxes = [table.bbox for table in tables]

    def outside_tables(obj: dict) -> bool:
        if obj.get("object_type") != "char":
            return True
        x = (obj["x0"] + obj["x1"]) / 2
        y = (obj["top"] + obj["bottom"]) / 2
        return not any(left <= x <= right and top <= y <= bottom
                       for left, top, right, bottom in boxes)

    sizes = [char["size"] for char in page.chars if char.get("text", "").strip()]
    body_size = statistics.median(sizes) if sizes else 10
    segments = []
    for line in page.filter(outside_tables).extract_text_lines():
        text = line["text"].strip()
        if not text:
            continue
        chars = line.get("chars", [])
        size = statistics.median([c["size"] for c in chars]) if chars else body_size
        bold = chars and sum("bold" in c.get("fontname", "").lower() for c in chars) > len(chars) / 2
        heading = len(text.split()) <= 16 and (
            size >= body_size * 1.18 or (bold and not text.endswith((".", ";", ":")))
        ) and not re.search(r"www\.|https?://|@", text, re.I)
        segments.append((line["top"], line["bottom"], f"## {text}" if heading else text))
    for table in tables:
        text = table_text(table.extract())
        if text:
            segments.append((table.bbox[1], table.bbox[3], text))
    lines: list[str] = []
    last_bottom = 0.0
    for top, bottom, text in sorted(segments):
        if lines and (top - last_bottom > body_size * 0.7 or text.startswith(("#", "|"))):
            lines.append("")
        lines.append(text)
        if text.startswith(("#", "|")):
            lines.append("")
        last_bottom = bottom
    return "\n".join(lines)


@lru_cache(maxsize=16)
def _source_digest(path: str, modified_ns: int, size: int) -> str:
    # File metadata is part of the cache key; large scans are hashed once per run.
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ocr_page(path: Path, page: int, cache_dir: str | None) -> str:
    from pdf2image import convert_from_path
    import pytesseract

    cached = None
    if cache_dir:
        stat = path.stat()
        digest = _source_digest(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        root = Path(cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        cached = root / f"{digest}-p{page}-eng-200dpi-v1.txt"
        if cached.exists():
            return cached.read_text(encoding="utf-8")
    images = convert_from_path(
        str(path), first_page=page, last_page=page, dpi=200, grayscale=True, thread_count=1,
        timeout=120,
    )
    try:
        text = str(pytesseract.image_to_string(images[0], lang="eng", timeout=120))
    finally:
        for image in images:
            image.close()
    if cached:
        cached.write_text(text, encoding="utf-8")
    return text


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[Any] = field(default_factory=list)


class HTMLDocument(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _descendants(node: Node, tags: set[str]) -> list[Node]:
    return [child for child in node.children if isinstance(child, Node) for child in
            ([child] if child.tag in tags else _descendants(child, tags))]


def _html_render(node: Node | str) -> str:
    if isinstance(node, str):
        return " ".join(node.split()) + " " if node.strip() else ""
    classes = set((node.attrs.get("class") or "").split())
    if node.tag in {"head", "script", "style", "noscript", "nav", "header", "footer", "aside", "form"}:
        return ""
    if classes & {"navbar", "navbar-nav", "breadcrumb", "footer"}:
        return ""
    if node.tag == "table":
        rows = [[" ".join(_html_render(cell).split()) for cell in _descendants(row, {"th", "td"})]
                for row in _descendants(node, {"tr"})]
        return "\n\n" + table_text(rows) + "\n\n"
    text = "".join(_html_render(child) for child in node.children)
    if re.fullmatch(r"h[1-6]", node.tag):
        return f"\n\n{'#' * int(node.tag[1])} {text.strip()}\n\n"
    if node.tag == "li":
        return f"\n- {text.strip()}\n"
    if node.tag == "br":
        return "\n"
    return f"\n\n{text}\n\n" if node.tag in {"p", "div", "section", "article", "main"} else text


def extract(
    path: str, doc_version: str, superseded: bool, *,
    ocr_enabled: bool = True, ocr_cache_dir: str | None = None,
) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    The OCR libraries need system packages in your Dockerfile (tesseract-ocr,
    poppler-utils), not only pip packages.
    """
    source = Path(path)
    document = Document(source.name, doc_version, superseded)
    if source.suffix.lower() == ".pdf":
        import pdfplumber

        with pdfplumber.open(source) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                try:
                    text = _pdf_text(page)
                    ocr = not text.strip() and ocr_enabled
                    if ocr:
                        text = _ocr_page(source, number, ocr_cache_dir)
                    document.pages.append(Page(source.name, number, text, ocr))
                finally:
                    page.close()
    elif source.suffix.lower() in {".html", ".htm"}:
        parser = HTMLDocument()
        parser.feed(source.read_text(encoding="utf-8"))
        main = _descendants(parser.root, {"main", "article"})
        text = _html_render(main[0] if main else parser.root)
        document.pages.append(Page(source.name, 1, text))
    elif source.suffix.lower() in {".md", ".txt"}:
        text = source.read_text(encoding="utf-8")
        if source.suffix.lower() == ".md":
            text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
        document.pages.append(Page(source.name, 1, text))
    else:
        raise ValueError(f"unsupported document type: {source.suffix}")
    return document
