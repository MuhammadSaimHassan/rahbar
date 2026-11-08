"""Inspect the downloaded corpus without indexing or changing source documents.

Run with the indexer image, which supplies pypdf and Poppler. Detailed output and text
are written under ignored corpus/raw/; commit only reviewed evidence summaries.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []
        self.tables = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "table":
            self.tables += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(" ".join(data.split()))


def audit_html(path: Path, text_dir: Path) -> dict:
    parser = VisibleText()
    parser.feed(path.read_text(encoding="utf-8"))
    text = "\n".join(parser.parts)
    (text_dir / f"{path.stem}.review.txt").write_text(text, encoding="utf-8")
    return {
        "file": path.name, "kind": "html", "pages": None,
        "tables": parser.tables, "text_characters": len(text),
    }


def audit() -> None:
    raw = HERE / "raw"
    entries = json.loads((raw / "_index.json").read_text(encoding="utf-8"))
    text_dir = raw / "text"
    text_dir.mkdir(exist_ok=True)
    results = []
    for entry in entries:
        path = raw / entry["file"]
        if path.suffix != ".pdf":
            results.append(audit_html(path, text_dir))
            continue
        reader = PdfReader(path)
        pages = []
        text_parts = []
        duplicate_pages: dict[str, list[int]] = {}
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            pages.append({"page": number, "text_characters": len(text.strip())})
            text_parts.append(f"\n--- PDF PAGE {number} ---\n{text}")
            normalised = " ".join(text.split())
            if normalised:
                duplicate_pages.setdefault(normalised, []).append(number)
        fonts = subprocess.run(
            ["pdffonts", str(path)], check=True, capture_output=True, text=True,
        ).stdout
        (text_dir / f"{path.stem}.txt").write_text("\n".join(text_parts), encoding="utf-8")
        result = {
            "file": path.name, "kind": "pdf", "pages": len(pages),
            "pages_without_text": [p["page"] for p in pages if p["text_characters"] == 0],
            "total_text_characters": sum(p["text_characters"] for p in pages),
            "font_rows": max(0, len(fonts.strip().splitlines()) - 2),
            "pdffonts": fonts, "page_details": pages,
            "duplicate_text_page_groups": [
                numbers for numbers in duplicate_pages.values() if len(numbers) > 1
            ],
        }
        results.append(result)
        print(
            f"{path.name}: {len(pages)} pages; "
            f"{len(result['pages_without_text'])} without text; "
            f"{result['font_rows']} font rows", flush=True,
        )
    (raw / "audit.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"PDF pages: {sum(r['pages'] or 0 for r in results)}", flush=True)


def ocr_missing_pages() -> None:
    """Diagnostic OCR for source review; production extraction is a separate stage."""
    raw = HERE / "raw"
    records = json.loads((raw / "audit.json").read_text(encoding="utf-8"))
    results = []
    for record in records:
        if record["kind"] != "pdf":
            continue
        path = raw / record["file"]
        target = raw / "ocr" / path.stem
        target.mkdir(parents=True, exist_ok=True)
        for page in record["pages_without_text"]:
            output = target / f"page-{page}.txt"
            if output.exists():
                continue
            with tempfile.TemporaryDirectory() as temporary:
                prefix = str(Path(temporary) / "page")
                subprocess.run([
                    "pdftoppm", "-f", str(page), "-l", str(page), "-scale-to", "2000",
                    "-singlefile", "-png", str(path), prefix,
                ], check=True, capture_output=True, timeout=120)
                text = subprocess.run([
                    "tesseract", prefix + ".png", "stdout", "-l", "eng",
                ], check=True, capture_output=True, text=True, timeout=120).stdout
            output.write_text(text, encoding="utf-8")
            print(f"OCR {path.name} page {page}: {len(text.strip())} characters", flush=True)
        original = (raw / "text" / f"{path.stem}.txt").read_text(encoding="utf-8")
        sections = re.split(r"--- PDF PAGE (\d+) ---", original)
        merged = []
        for number, text in zip(sections[1::2], sections[2::2]):
            ocr = target / f"page-{number}.txt"
            content = ocr.read_text(encoding="utf-8") if ocr.exists() else text
            merged.append(f"--- PDF PAGE {number} ---\n{content}")
        (raw / "text" / f"{path.stem}.review.txt").write_text(
            "\n".join(merged), encoding="utf-8",
        )
        results.append({"file": path.name, "ocr_pages": record["pages_without_text"]})
    (raw / "ocr-audit.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr", action="store_true", help="OCR pages flagged by the last audit")
    if parser.parse_args().ocr:
        ocr_missing_pages()
    else:
        audit()
