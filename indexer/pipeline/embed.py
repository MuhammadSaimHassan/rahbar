"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import math
import time

import httpx

from .config import IndexerSettings


def validate_vectors(vectors: object, count: int, dimension: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("embedding response has the wrong vector count")
    result = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimension:
            raise ValueError(f"embedding dimension does not match pin {dimension}")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
               for x in vector):
            raise ValueError("embedding contains a non-finite or non-numeric value")
        values = [float(x) for x in vector]
        norm = math.hypot(*values)
        if norm == 0 or not math.isfinite(norm):
            raise ValueError("embedding must have a finite, non-zero norm")
        result.append([x / norm for x in values])
    return result


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed with settings.embed_model and nothing else.

    With Ollama: POST {ollama_url}/api/embed with {"model": ..., "input": [texts]}
    returns {"embeddings": [[...], ...]}. Batch the calls; one request per chunk is slow.
    """
    if any(not text.strip() for text in texts):
        raise ValueError("cannot embed blank text")
    vectors: list[list[float]] = []
    prefix = "search_document: " if settings.embed_model.split(":")[0] == "nomic-embed-text" else ""
    with httpx.Client(base_url=settings.ollama_url, timeout=settings.embed_timeout,
                      trust_env=False) as client:
        for offset in range(0, len(texts), settings.embed_batch_size):
            batch = texts[offset:offset + settings.embed_batch_size]
            for attempt in range(3):
                try:
                    response = client.post("/api/embed", json={
                        "model": settings.embed_model, "input": [prefix + text for text in batch],
                        "truncate": False,
                    })
                    response.raise_for_status()
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    transient = not isinstance(exc, httpx.HTTPStatusError) or (
                        exc.response.status_code == 429 or exc.response.status_code >= 500
                    )
                    if not transient or attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            body = response.json()
            actual = body.get("model")
            expected = settings.embed_model
            if not isinstance(actual, str) or (
                actual if ":" in actual else actual + ":latest"
            ) != (expected if ":" in expected else expected + ":latest"):
                raise ValueError(f"embedding provider model mismatch: {actual!r} != {expected!r}")
            vectors.extend(validate_vectors(body.get("embeddings"), len(batch), settings.embed_dimension))
    return vectors
