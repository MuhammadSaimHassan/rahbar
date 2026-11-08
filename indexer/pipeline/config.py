"""Indexer configuration, from the same ConfigMap the API reads (section 4.1)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexerSettings:
    embed_model: str        # EMBED_MODEL: must equal the API's value (section 4.4)
    chroma_host: str
    chroma_port: int
    collection: str
    corpus_dir: str         # where the documents and _index.json sit inside the Job's pod
    chunk_size: int
    chunk_overlap: int
    ollama_url: str
    embed_dimension: int = 768
    embed_batch_size: int = 16
    embed_timeout: float = 120.0
    store_batch_size: int = 128
    redis_url: str = "redis://redis:6379/0"
    ocr_enabled: bool = True
    ocr_cache_dir: str | None = None

    def __post_init__(self) -> None:
        if self.chunk_size < 16 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("invalid chunk size/overlap")
        if min(self.embed_dimension, self.embed_batch_size, self.store_batch_size) < 1:
            raise ValueError("dimensions and batch sizes must be positive")
        if self.embed_timeout <= 0:
            raise ValueError("embedding timeout must be positive")


def get_settings() -> IndexerSettings:
    return IndexerSettings(
        embed_model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
        chroma_host=os.environ.get("CHROMA_HOST", "chroma"),
        chroma_port=int(os.environ.get("CHROMA_PORT", 8000)),
        collection=os.environ.get("CHROMA_COLLECTION", "rahbar"),
        corpus_dir=os.environ.get("CORPUS_DIR", "/corpus"),
        chunk_size=int(os.environ.get("CHUNK_SIZE", 400)),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", 50)),
        ollama_url=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"),
        embed_dimension=int(os.environ.get("EMBED_DIMENSION", 768)),
        embed_batch_size=int(os.environ.get("EMBED_BATCH_SIZE", 16)),
        embed_timeout=float(os.environ.get("EMBED_TIMEOUT", 120)),
        store_batch_size=int(os.environ.get("STORE_BATCH_SIZE", 128)),
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        ocr_enabled=os.environ.get("OCR_ENABLED", "true").lower() == "true",
        ocr_cache_dir=os.environ.get("OCR_CACHE_DIR") or None,
    )
