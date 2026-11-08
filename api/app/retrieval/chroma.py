"""Retrieve evidence from one immutable Chroma index generation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx
import redis

from ..config import Settings
from ..schemas import Passage
from ..services.index_catalog import resolve_index

COLLECTIONS = "/api/v2/tenants/default_tenant/databases/default_database/collections"


def edition(question: str) -> str | None:
    if re.search(r"\b(?:aug(?:ust)?\s+2023|2023-08|2023\s+(?:academic\s+)?rules)\b",
                 question, re.I):
        return "2023-08"
    if re.search(r"\b(?:jun(?:e)?\s+2026|2026-06|2026\s+(?:academic\s+)?rules)\b",
                 question, re.I):
        return "2026-06"
    return None


@dataclass
class Evidence:
    passages: list[Passage]
    vector: list[float]
    generation: str
    chunks_sha256: str | None = None


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis = redis.Redis.from_url(
            settings.redis_url, decode_responses=True,
            socket_timeout=settings.dependency_timeout,
            socket_connect_timeout=settings.dependency_timeout,
        )

    def retrieve(self, question: str, k: int) -> list[Passage]:
        return self.search(question, k, edition(question)).passages

    def search(self, question: str, k: int, version: str | None) -> Evidence:
        settings = self.settings
        raw = self.redis.get(f"rahbar:index:{settings.collection}:active")
        if not isinstance(raw, str):
            raise ValueError("No published index catalog")
        active = resolve_index(settings.collection, raw)
        with httpx.Client(
            base_url=f"http://{settings.chroma_host}:{settings.chroma_port}",
            timeout=settings.dependency_timeout, trust_env=False,
        ) as client:
            response = client.get(f"{COLLECTIONS}/{quote(active.collection, safe='')}")
            response.raise_for_status()
            collection = response.json()
            metadata = collection["metadata"]
            if (metadata.get("embed_model"), metadata.get("dimension"),
                metadata.get("generation")) != (
                settings.embed_model, settings.embed_dimension, active.generation,
            ):
                raise ValueError("Index metadata does not match the active catalog and embedding pin")
            vector = self.embed(question)
            where: dict[str, str | bool] = (
                {"doc_version": version} if version else {"superseded": False}
            )
            response = client.post(
                f"{COLLECTIONS}/{quote(collection['id'], safe='')}/query",
                json={
                    "query_embeddings": [vector], "where": where, "n_results": k,
                    "include": ["documents", "metadatas", "distances"],
                },
            )
            response.raise_for_status()
            result = response.json()
        passages = [
            Passage(chunk_id=chunk_id, text=document, source=meta["source"],
                    section=meta["section"], page=meta.get("page"), score=1 - distance)
            for chunk_id, document, meta, distance in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0],
                result["distances"][0], strict=True,
            )
        ]
        return Evidence(passages, vector, active.generation, metadata.get("chunks_sha256"))

    def embed(self, question: str) -> list[float]:
        settings = self.settings
        model = settings.embed_model
        query = f"search_query: {question}" if model.split(":")[0] == "nomic-embed-text" else question
        response = httpx.post(
            f"{settings.ollama_url.rstrip('/')}/api/embed",
            json={"model": model, "input": [query], "truncate": False},
            timeout=settings.generation_timeout, trust_env=False,
        )
        response.raise_for_status()
        result = response.json()
        actual = result["model"]
        if not isinstance(actual, str) or actual.removesuffix(":latest") != model.removesuffix(":latest"):
            raise ValueError("Unexpected embedding model")
        vector: list[float] = result["embeddings"][0]
        if (len(vector) != settings.embed_dimension
                or any(isinstance(value, bool) or not isinstance(value, (float, int))
                       or not math.isfinite(value) for value in vector)):
            raise ValueError("Invalid query embedding")
        norm = math.hypot(*vector)
        if norm == 0:
            raise ValueError("Zero query embedding")
        return [component / norm for component in vector]
