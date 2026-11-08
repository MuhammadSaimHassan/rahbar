"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .config import IndexerSettings
from .embed import validate_vectors
from .models import Chunk


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def get_redis(settings: IndexerSettings) -> Any:
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True,
                                socket_timeout=5, socket_connect_timeout=5)


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count."""
    if not chunks:
        raise ValueError("refusing to publish an empty index")
    if len({c.id for c in chunks}) != len(chunks):
        raise ValueError("duplicate chunk ids")
    if any(not all((c.id, c.text.strip(), c.source, c.section, c.doc_version))
           or c.page < 1 or not isinstance(c.superseded, bool) for c in chunks):
        raise ValueError("invalid chunk content or metadata")
    vectors = validate_vectors(vectors, len(chunks), settings.embed_dimension)
    connection = get_redis(settings)
    logical = settings.collection
    active_key = f"rahbar:index:{logical}:active"
    lock = connection.lock(f"rahbar:index:{logical}:writer", timeout=120, blocking_timeout=0)
    acquired = False
    try:
        acquired = lock.acquire(blocking=False)
        if not acquired:
            raise RuntimeError("another indexer is publishing; retry after it finishes")
        client = get_client(settings)
        generation = uuid.uuid4().hex
        name = f"{logical}-v-{generation}"
        digest = hashlib.sha256()
        for chunk in chunks:
            digest.update(chunk.export_line().encode("utf-8"))
        collection = client.create_collection(name=name, metadata={
            "chunks_sha256": digest.hexdigest(),
            "hnsw:space": "cosine", "embed_model": settings.embed_model,
            "dimension": settings.embed_dimension, "generation": generation,
            "logical_collection": logical, "chunk_count": len(chunks),
            "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
            "token_unit": "lexical-v1",
        })
        for offset in range(0, len(chunks), settings.store_batch_size):
            lock.extend(120, replace_ttl=True)
            batch = chunks[offset:offset + settings.store_batch_size]
            collection.add(ids=[c.id for c in batch], documents=[c.text for c in batch],
                           embeddings=vectors[offset:offset + len(batch)],
                           metadatas=[c.metadata() for c in batch])
        count = int(collection.count())
        if count != len(chunks):
            raise RuntimeError(f"staged index count mismatch: {count} != {len(chunks)}")
        if not lock.owned():
            raise RuntimeError("index writer lease expired before publication")
        previous = connection.get(active_key)
        old_generation = json.loads(previous)["generation"] if previous else "bootstrap"
        keys = list(connection.scan_iter(match=f"rahbar:cache:{logical}:{old_generation}:*"))
        catalog = json.dumps({
            "collection": name, "generation": generation, "embed_model": settings.embed_model,
            "dimension": settings.embed_dimension, "chunk_count": count,
        })
        lock.extend(120, replace_ttl=True)
        # One atomic Redis transaction publishes the complete index and removes the
        # prior generation's cache. In-flight old requests remain isolated by generation.
        with connection.pipeline(transaction=True) as transaction:
            transaction.watch(lock.name)
            if not lock.owned():
                raise RuntimeError("index writer lease lost before publication")
            transaction.multi()
            transaction.set(active_key, catalog)
            for offset in range(0, len(keys), 500):
                transaction.unlink(*keys[offset:offset + 500])
            transaction.execute()
        return count
    finally:
        # Never delete a collection on a timeout: the publish may have committed.
        # Unpublished staging collections and prior generations are retained for review.
        try:
            if acquired and lock.owned():
                lock.release()
        finally:
            connection.close()
