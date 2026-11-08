"""Prometheus metrics at /metrics (section 4.8).

Track HTTP requests and query stages without question or document content in labels.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

router = APIRouter()

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)


RETRIEVAL = Histogram("rahbar_retrieval_seconds", "Evidence retrieval latency")
GENERATION = Histogram("rahbar_generation_seconds", "Answer generation latency")
CACHE = Counter("rahbar_cache_total", "Semantic cache lookups", ["outcome"])
ABSTENTIONS = Counter("rahbar_abstentions_total", "Insufficient-evidence answers")
FALLBACKS = Counter("rahbar_fallbacks_total", "Safe fallback answers", ["stage"])
TOKENS = Counter("rahbar_tokens_total", "Tokens reported by the model", ["kind"])


token_usage_var: ContextVar[dict[str, int] | None] = ContextVar("token_usage", default=None)


def record_tokens(kind: str, count: object) -> None:
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return
    TOKENS.labels(kind).inc(count)
    usage = token_usage_var.get()
    if usage is not None:
        usage[kind] = usage.get(kind, 0) + count


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
