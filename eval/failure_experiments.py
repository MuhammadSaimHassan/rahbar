"""Measure four controlled failures without modifying a deployed index.

Run with PYTHONPATH=api:indexer and the normal API dependency settings.
Extraction and chunking run locally. Pin and source cases read an existing
index using the real retriever and embedding service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.retrieval.chroma import COLLECTIONS, ChromaRetriever, edition
from app.services.index_catalog import resolve_index


def extraction(args: argparse.Namespace) -> dict:
    from pipeline.extract import extract
    from pipeline.text import token_count

    baseline = extract(str(args.scanned_pdf), "experiment", False,
                       ocr_enabled=True, ocr_cache_dir=args.ocr_cache)
    broken = extract(str(args.scanned_pdf), "experiment", False,
                     ocr_enabled=False, ocr_cache_dir=args.ocr_cache)
    normal_tokens = sum(token_count(page.text) for page in baseline.pages)
    lost_tokens = sum(token_count(page.text) for page in broken.pages)
    return {
        "stage": "extraction", "source": args.scanned_pdf.name,
        "baseline_tokens": normal_tokens, "without_ocr_tokens": lost_tokens,
        "baseline_ocr_pages": [page.page for page in baseline.pages if page.ocr],
        "without_ocr_empty_pages": [page.page for page in broken.pages if not page.text.strip()],
        "failure_observed": normal_tokens > lost_tokens,
        "remedy": "Enable OCR and verify page coverage before publication.",
    }


def chunking(args: argparse.Namespace) -> dict:
    import yaml

    from pipeline.chunk import chunk
    from pipeline.clean import clean
    from pipeline.extract import extract
    from pipeline.models import Chunk
    from pipeline.run import discover
    from pipeline.text import token_count, token_slice
    from prepare_golden import GOLDEN, project

    normal: list[Chunk] = []
    broken: list[Chunk] = []
    for path, version, superseded in discover(str(args.corpus)):
        document = clean(extract(str(path), version, superseded,
                                 ocr_enabled=True, ocr_cache_dir=args.ocr_cache))
        normal.extend(chunk(document, 400, 50))
        for page in document.pages:
            for offset in range(0, token_count(page.text), 100):
                text = token_slice(page.text, offset, offset + 100)
                identity = hashlib.sha256(
                    f"{document.source}:{page.page}:{offset}:{text}".encode()
                ).hexdigest()[:32]
                broken.append(Chunk(identity, text, document.source, "Fixed window",
                                    page.page, version, superseded))
    questions = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["questions"]
    results = {}
    with tempfile.TemporaryDirectory() as scratch:
        for label, chunks in (("baseline", normal), ("fixed_100_no_overlap", broken)):
            export = Path(scratch) / f"{label}.jsonl"
            export.write_text("".join(c.export_line() for c in chunks), encoding="utf-8")
            projection = project(questions, export)
            units = [unit for group in projection["questions"].values() for unit in group]
            mapped = sum(bool(unit["chunk_ids"]) for unit in units)
            results[label] = {
                "chunks": len(chunks), "mapped_evidence_units": mapped, "evidence_units": len(units),
                "unmapped": projection["unmapped"], "chunks_sha256": projection["chunks_sha256"],
            }
    return {
        "stage": "chunking", **results,
        "measurement": "Source evidence mapping coverage before ranked retrieval.",
        "remedy": "Restore structure-aware 400/50 chunking and rerun the live recall sweep.",
    }


def pin(args: argparse.Namespace) -> dict:
    settings = get_settings()
    retriever = ChromaRetriever(settings)
    broken = ChromaRetriever(replace(settings, embed_model=settings.embed_model + ":wrong-pin"))
    try:
        baseline = retriever.retrieve(args.question, settings.top_k)
        try:
            broken.retrieve(args.question, settings.top_k)
        except ValueError as exc:
            failure = str(exc)
        else:
            raise RuntimeError("the model mismatch was not rejected")
        restored = retriever.retrieve(args.question, settings.top_k)
        return {
            "stage": "retrieval", "baseline_hits": len(baseline), "mismatched_model_hits": 0,
            "failure": failure, "restored_hits": len(restored),
            "remedy": "Restore the API embedding pin to match the published index.",
        }
    finally:
        retriever.redis.close()
        broken.redis.close()


def source(args: argparse.Namespace) -> dict:
    settings = get_settings()
    retriever = ChromaRetriever(settings)
    try:
        # This validates the pin before the deliberately unfiltered read below.
        evidence = retriever.search(args.question, settings.top_k, edition(args.question))
        value = retriever.redis.get(f"rahbar:index:{settings.collection}:active")
        if not isinstance(value, str):
            raise ValueError("missing active catalog")
        active = resolve_index(settings.collection, value)
        if active.generation != evidence.generation:
            raise ValueError("index changed during the source experiment")
        with httpx.Client(
            base_url=f"http://{settings.chroma_host}:{settings.chroma_port}",
            timeout=settings.dependency_timeout, trust_env=False,
        ) as client:
            reply = client.get(f"{COLLECTIONS}/{quote(active.collection, safe='')}")
            reply.raise_for_status()
            identity = reply.json()["id"]
            reply = client.get(f"{COLLECTIONS}/{identity}/count")
            reply.raise_for_status()
            count = min(10, int(reply.json()))
            observations = {}
            for label, where in (("baseline", {"superseded": False}), ("without_version_filter", None)):
                payload = {"query_embeddings": [evidence.vector], "n_results": count,
                           "include": ["metadatas", "distances"]}
                if where:
                    payload["where"] = where
                reply = client.post(f"{COLLECTIONS}/{identity}/query", json=payload)
                reply.raise_for_status()
                result = reply.json()
                hits = [
                    {"chunk_id": chunk_id, **metadata}
                    for chunk_id, metadata in zip(result["ids"][0], result["metadatas"][0], strict=True)
                ]
                observations[label] = {
                    "hits": hits, "superseded_hits": sum(bool(hit["superseded"]) for hit in hits),
                }
        return {
            "stage": "source", "generation": evidence.generation, **observations,
            "remedy": "Keep the superseded filter and scope explicit historical questions by edition.",
        }
    finally:
        retriever.redis.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["extraction", "chunking", "pin", "source"])
    parser.add_argument("--scanned-pdf", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--ocr-cache")
    parser.add_argument("--question", default="What is the minimum attendance for the final exam?")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "extraction" and args.scanned_pdf is None:
        parser.error("extraction requires --scanned-pdf")
    if args.stage == "chunking" and args.corpus is None:
        parser.error("chunking requires --corpus")
    actions = {"extraction": extraction, "chunking": chunking, "pin": pin, "source": source}
    result = actions[args.stage](args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
