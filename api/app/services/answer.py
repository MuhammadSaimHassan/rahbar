"""Retrieve, validate, and return grounded answers."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping

import httpx
import redis

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..retrieval.chroma import ChromaRetriever, edition
from ..routes.metrics import ABSTENTIONS, CACHE, FALLBACKS, GENERATION, RETRIEVAL
from ..schemas import Answer, AskResponse, Passage, RetrievedRef
from .cache import AnswerCache

log = logging.getLogger("rahbar.answer")

ABSTAIN = "The retrieved university sources do not cover this question."
FALLBACK = "I couldn't verify an answer against the university sources. Please try again."
FOLLOW_UP = re.compile(
    r"^(?:and\b|even if\b|what about\b|how about\b|(?:what|why|how|when|where|can|does|is|do)\b"
    r".{0,45}\b(?:it|that|this|they|those|them)\b)", re.I,
)


def ungrounded(message: str) -> Answer:
    return Answer(reasoning="", answer=message, citations=[],
                  answered_from_context=False, confidence="low")


def valid_grounding(answer: Answer, passages: list[Passage], inline: bool) -> bool:
    available = {(p.source, p.section, p.page) for p in passages}
    cited = {(c.source, c.section, c.page) for c in answer.citations}
    if not answer.answered_from_context:
        return not cited
    if not answer.answer.strip() or not cited or not cited <= available:
        return False
    if not inline:
        return True
    markers = {f"[{source} / {section}]" for source, section, _ in cited}
    pattern = "|".join(re.escape(marker) for marker in sorted(markers))
    lines = [line.strip() for line in answer.answer.splitlines() if line.strip()]
    seen: set[str] = set()
    for line in lines:
        suffix = re.search(rf"(?:\s*(?:{pattern}))+\s*$", line)
        if suffix is None:
            return False
        claim = line[:suffix.start()].strip()
        if not claim or "[" in claim or "]" in claim or re.search(r"[.!?]\s+\w", claim):
            return False
        seen.update(re.findall(pattern, suffix.group()))
    return seen == markers


def generate(
    question: str, passages: list[Passage], provider: LLMProvider,
) -> tuple[Answer, bool]:
    with GENERATION.time():
        for retry in range(2):
            try:
                answer = provider.generate(question, passages)
                if provider.name != "stub" and answer.answered_from_context:
                    claim = answer.answer.strip()
                    if (claim and not re.search(r"[\[\]\r\n]|[.!?]\s+\w", claim)
                            and valid_grounding(answer, passages, inline=False)):
                        markers = dict.fromkeys(
                            f"[{citation.source} / {citation.section}]"
                            for citation in answer.citations
                        )
                        answer = answer.model_copy(update={"answer": " ".join([claim, *markers])})
                if valid_grounding(answer, passages, inline=provider.name != "stub"):
                    if answer.answered_from_context:
                        return answer.model_copy(update={"reasoning": ""}), retry == 0
                    return ungrounded(ABSTAIN), False
            except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, NotImplementedError):
                continue
    FALLBACKS.labels("generation").inc()
    return ungrounded(FALLBACK), False


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings,
    previous_question: str | None = None,
    response_headers: MutableMapping[str, str] | None = None,
) -> tuple[AskResponse, str]:
    follow_up = bool(FOLLOW_UP.search(question))
    version = edition(question)
    query = question
    if follow_up and previous_question:
        version = version or edition(previous_question)
        query = f"Previous question: {previous_question}\nFollow-up question: {question}"

    cache = None
    passages: list[Passage] = []
    evidence = None
    answer = None
    outcome = "BYPASS"
    try:
        with RETRIEVAL.time():
            if isinstance(retriever, ChromaRetriever):
                evidence = retriever.search(query, settings.top_k, version)
                passages = evidence.passages
            else:
                passages = retriever.retrieve(query, k=settings.top_k)
    except (httpx.HTTPError, redis.RedisError, ValueError, TypeError, KeyError, IndexError):
        FALLBACKS.labels("retrieval").inc()
        answer = ungrounded(FALLBACK)

    eligible = [passage for passage in passages if passage.score >= settings.relevance_floor]
    if answer is None and not eligible:
        answer = ungrounded(ABSTAIN)
    if (answer is None and evidence is not None and isinstance(retriever, ChromaRetriever)
            and not follow_up and provider.name in {"ollama", "hosted"}):
        cache = AnswerCache(retriever.redis, settings, evidence, eligible, version, question)
        candidate = cache.get()
        if candidate and candidate.answered_from_context and valid_grounding(
            candidate, eligible, inline=True,
        ):
            answer = candidate
            outcome = "HIT"
        else:
            outcome = "MISS"
        CACHE.labels(outcome.lower()).inc()
    if answer is None:
        answer, cacheable = generate(query, eligible, provider)
        if cacheable and cache is not None:
            cache.put(answer)
    if answer.answer == ABSTAIN:
        ABSTENTIONS.inc()
    if response_headers is not None:
        response_headers["X-Answer-Outcome"] = (
            "abstained" if answer.answer == ABSTAIN else
            "fallback" if answer.answer == FALLBACK else "grounded"
        )
        if evidence is not None:
            response_headers["X-Index-Generation"] = evidence.generation
            if isinstance(evidence.chunks_sha256, str) and re.fullmatch(
                r"[0-9a-f]{64}", evidence.chunks_sha256,
            ):
                response_headers["X-Index-Chunks-SHA256"] = evidence.chunks_sha256
    log.info(
        "answered",
        extra={
            "retriever": retriever.name,
            "provider": provider.name,
            "top_k": settings.top_k,
            "chunk_ids": [p.chunk_id for p in passages],
            "scores": [round(p.score, 4) for p in passages],
            "answered_from_context": answer.answered_from_context,
            "generation": evidence.generation if evidence else None,
            "cache": outcome,
            "follow_up": follow_up,
        },
    )
    return AskResponse(
        request_id=request_id_var.get(),
        answer=answer.answer,
        citations=answer.citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=[
            RetrievedRef(
                chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page, score=p.score,
            )
            for p in passages
        ],
        provider=provider.name,
    ), outcome
