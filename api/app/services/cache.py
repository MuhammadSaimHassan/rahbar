"""Bounded semantic answer cache scoped to an immutable index generation."""

from __future__ import annotations

import hashlib
import json
import re

import redis

from ..config import Settings
from ..retrieval.chroma import Evidence
from ..schemas import Answer, Passage

LIMIT = 32
TTL_SECONDS = 3600


class AnswerCache:
    def __init__(
        self, connection: redis.Redis, settings: Settings, evidence: Evidence,
        passages: list[Passage], version: str | None, question: str,
    ) -> None:
        scope = [
            "prompt-v2", version, settings.llm_provider, settings.llm_model, settings.temperature,
            settings.hosted_base_url if settings.llm_provider == "hosted" else None,
            [passage.chunk_id for passage in passages],
        ]
        fingerprint = hashlib.sha256(json.dumps(scope).encode()).hexdigest()
        self.key = f"rahbar:cache:{settings.collection}:{evidence.generation}:v1:{fingerprint}"
        self.connection = connection
        self.vector = evidence.vector
        self.threshold = settings.cache_threshold
        # Numbers and polarity often change the answer despite close embeddings.
        self.anchors = re.findall(
            r"\d+(?:\.\d+)?|\b(?:not|never|no|without|except|before|after|minimum|maximum)\b",
            question.casefold(),
        )

    def get(self) -> Answer | None:
        try:
            entries = self.connection.lrange(self.key, 0, LIMIT - 1)
        except redis.RedisError:
            return None
        if not isinstance(entries, list):
            return None
        best = self.threshold
        hit = None
        for raw in entries:
            try:
                entry = json.loads(raw)
                if entry["anchors"] != self.anchors:
                    continue
                score = sum(a * b for a, b in zip(self.vector, entry["vector"], strict=True))
                if score >= best:
                    hit = Answer.model_validate(entry["answer"], strict=True)
                    best = score
            except (KeyError, TypeError, ValueError):
                continue
        return hit

    def put(self, answer: Answer) -> None:
        entry = json.dumps({
            "anchors": self.anchors,
            "vector": self.vector,
            "answer": answer.model_dump(),
        })
        try:
            with self.connection.pipeline() as pipe:
                pipe.lpush(self.key, entry)
                pipe.ltrim(self.key, 0, LIMIT - 1)
                pipe.expire(self.key, TTL_SECONDS)
                pipe.execute()
        except redis.RedisError:
            return
