"""Bounded, read-only dependency checks used at startup and by readiness."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx
import redis

from ..config import Settings
from .index_catalog import resolve_index

log = logging.getLogger("rahbar.api.health")


class DependencyHealth:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_checks: dict[str, str] | None = None

    def check(self) -> dict[str, str]:
        """Return explicit dependency failures; never create or change the index."""
        settings = self.settings
        checks: dict[str, str] = {}
        active = resolve_index(settings.collection, None)
        try:
            connection = redis.Redis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=settings.dependency_timeout,
                socket_timeout=settings.dependency_timeout,
            )
            try:
                if not connection.ping():
                    raise ConnectionError("PING failed")
                value = connection.get(f"rahbar:index:{settings.collection}:active")
                if value is not None and not isinstance(value, str):
                    raise ValueError("catalog must be a decoded JSON string")
                active = resolve_index(settings.collection, value)
                checks["redis"] = "ok"
                if settings.retriever == "chroma" and active.generation == "bootstrap":
                    checks["index_catalog"] = "no published index generation"
            finally:
                connection.close()
        except Exception as exc:
            checks["redis"] = f"unavailable or invalid catalog ({type(exc).__name__})"
        try:
            with httpx.Client(
                base_url=f"http://{settings.chroma_host}:{settings.chroma_port}",
                timeout=settings.dependency_timeout,
                trust_env=False,
            ) as client:
                base = "/api/v2/tenants/default_tenant/databases/default_database/collections"
                response = client.get(f"{base}/{quote(active.collection, safe='')}")
                response.raise_for_status()
                collection = response.json()
                metadata = collection.get("metadata") or {}
                model = metadata.get("embed_model")
                dimension = metadata.get("dimension")
                if model != settings.embed_model or dimension != settings.embed_dimension:
                    checks["embedding_pin"] = (
                        f"mismatch: API model={settings.embed_model}, "
                        f"dimension={settings.embed_dimension}; "
                        f"collection model={model}, dimension={dimension}"
                    )
                else:
                    checks["embedding_pin"] = "ok"
                if active.generation != "bootstrap":
                    checks["index_catalog"] = (
                        "ok" if metadata.get("generation") == active.generation
                        else "collection generation differs from catalog"
                    )
                count = client.get(f"{base}/{quote(collection['id'], safe='')}/count")
                count.raise_for_status()
                checks["chroma"] = "ok" if int(count.json()) > 0 else "collection is empty"
        except Exception as exc:
            # Log only the exception type: dependency URLs may carry credentials.
            checks["chroma"] = f"collection unavailable ({type(exc).__name__})"
        if checks != self._last_checks:
            if all(value == "ok" for value in checks.values()):
                log.info("dependencies ready", extra={"checks": checks})
            else:
                log.warning("dependencies not ready", extra={"checks": checks})
            self._last_checks = checks.copy()
        return checks
