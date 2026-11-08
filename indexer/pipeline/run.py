"""The indexer Job's entry point. It runs once and exits (section 4.2).

    python -m pipeline.run --dummy    # week 1: three fake chunks, no model needed
    python -m pipeline.run            # the real pipeline: extract, clean, chunk, embed, store

Exit code 0 means the index was written; anything else fails the Job, and
Kubernetes retries it up to the Job's backoffLimit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

from .config import IndexerSettings, get_settings
from .models import Chunk


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer", "msg": msg, **fields}), flush=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "logger": record.name, "level": record.levelname,
                           "msg": record.getMessage()})


def _front_matter(path: Path) -> dict[str, str]:
    """Read `key: value` lines between leading '---' markers (used by eval/fixtures)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    """List (path, doc_version, superseded) for every document to index.

    corpus/fetch.py writes _index.json next to the files it downloads; use it when
    present. Otherwise read Markdown front matter (the CI fixtures work this way).
    """
    root = Path(corpus_dir)
    index = root / "_index.json"
    if index.exists():
        entries = json.loads(index.read_text(encoding="utf-8"))
        documents = []
        seen = set()
        for entry in entries:
            path = (root / entry["file"]).resolve()
            if not path.is_relative_to(root.resolve()) or path.name in seen:
                raise ValueError("corpus index contains an unsafe or duplicate path")
            seen.add(path.name)
            if not isinstance(entry.get("superseded", False), bool):
                raise ValueError("superseded must be a boolean")
            if not path.is_file():
                raise ValueError(f"corpus file is missing: {path.name}")
            if entry.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(f"corpus hash mismatch: {path.name}")
            documents.append((path, str(entry.get("doc_version", "unknown")),
                              entry.get("superseded", False)))
        return documents
    found = []
    for path in sorted(root.glob("*")):
        if path.suffix.lower() not in {".pdf", ".md", ".html", ".txt"}:
            continue
        if path.name.lower().startswith("readme"):
            continue
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        found.append((path, meta.get("doc_version", "unknown"),
                      meta.get("superseded", "false").lower() == "true"))
    return found


def run_pipeline(
    settings: IndexerSettings, *, dry_run: bool = False,
    report_path: str | None = None, chunks_path: str | None = None,
) -> int:
    from .chunk import chunk
    from .clean import clean
    from .embed import embed
    from .extract import extract
    from .store import store
    from .text import token_count

    documents = discover(settings.corpus_dir)
    if not documents:
        raise SystemExit(f"no documents found in {settings.corpus_dir}")
    if not dry_run:
        # Fail fast on a missing model or bad pin before paying for document OCR.
        embed(["index compatibility probe"], settings)
    all_chunks: list[Chunk] = []
    report: dict = {"mode": "dry-run" if dry_run else "published", "token_unit": "lexical-v1",
                    "embed_model": settings.embed_model, "dimension": settings.embed_dimension,
                    "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
                    "documents": []}
    original_tokens = cleaned_tokens = 0
    for path, doc_version, superseded in documents:
        log("extracting", source=path.name)
        extracted = extract(str(path), doc_version, superseded, ocr_enabled=settings.ocr_enabled,
                            ocr_cache_dir=settings.ocr_cache_dir)
        doc = clean(extracted)
        pieces = chunk(doc, settings.chunk_size, settings.chunk_overlap)
        before = sum(token_count(page.text) for page in extracted.pages)
        after = sum(token_count(page.text) for page in doc.pages)
        original_tokens += before
        cleaned_tokens += after
        report["documents"].append({
            "source": path.name, "doc_version": doc_version, "superseded": superseded,
            "pages": len(doc.pages), "ocr_pages": [p.page for p in doc.pages if p.ocr],
            "empty_pages": [p.page for p in doc.pages if not p.text.strip()],
            "extracted_tokens": before, "cleaned_tokens": after, "chunks": len(pieces),
        })
        log("chunked", source=path.name, chunks=len(pieces))
        all_chunks.extend(pieces)
    if not all_chunks:
        raise ValueError("extraction/chunking produced no usable content")
    stored_tokens = sum(token_count(c.text) for c in all_chunks)
    report.update(chunk_count=len(all_chunks), extracted_tokens=original_tokens,
                  cleaned_tokens=cleaned_tokens, stored_tokens=stored_tokens,
                  storage_amplification=round(stored_tokens / max(1, original_tokens), 4),
                  overlap_amplification=round(stored_tokens / max(1, cleaned_tokens), 4))
    if not dry_run:
        vectors = embed([c.text for c in all_chunks], settings)
        store(all_chunks, vectors, settings)
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["process_peak_rss_bytes"] = usage if sys.platform == "darwin" else usage * 1024
    except ImportError:
        report["process_peak_rss_bytes"] = None
    if chunks_path:
        target = Path(chunks_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(c.export_line() for c in all_chunks), encoding="utf-8")
    if report_path:
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    log("pipeline summary", chunks=len(all_chunks), dry_run=dry_run,
        storage_amplification=report["storage_amplification"])
    return len(all_chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RAHBAR index, then exit.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dummy", action="store_true", help="write three fake chunks")
    mode.add_argument("--dry-run", action="store_true", help="extract/clean/chunk without network")
    parser.add_argument("--report", help="write measured processing statistics as JSON")
    parser.add_argument("--chunks-out", help="write chunk JSONL for source review (keep ignored)")
    args = parser.parse_args()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    settings = get_settings()
    log("indexer starting", dummy=args.dummy, embed_model=settings.embed_model,
        collection=settings.collection, chroma=f"{settings.chroma_host}:{settings.chroma_port}",
        pod=os.environ.get("HOSTNAME", "-"))
    started = time.perf_counter()
    try:
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
        else:
            count = run_pipeline(settings, dry_run=args.dry_run, report_path=args.report,
                                 chunks_path=args.chunks_out)
    except Exception as exc:
        log("indexer failed", error_type=type(exc).__name__, error=str(exc))
        return 1
    log("indexer finished", chunks=count, seconds=round(time.perf_counter() - started, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
