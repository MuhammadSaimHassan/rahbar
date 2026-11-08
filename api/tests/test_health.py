"""Readiness fails closed and recovers without restarting the API."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.services.health import DependencyHealth


@pytest.mark.parametrize(
    ("count", "model", "dimension", "redis_up", "http_status", "failed"),
    [
        (3, "dummy-768", 768, True, 200, None),
        (0, "dummy-768", 768, True, 200, "chroma"),
        (3, "other-model", 768, True, 200, "embedding_pin"),
        (3, "dummy-768", 384, True, 200, "embedding_pin"),
        (3, "dummy-768", 768, False, 200, "redis"),
        (3, "dummy-768", 768, True, 404, "chroma"),
        (3, "dummy-768", None, True, 200, "embedding_pin"),
    ],
)
def test_dependency_failures(
    monkeypatch: pytest.MonkeyPatch, count, model, dimension, redis_up, http_status, failed,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/count"):
            return httpx.Response(200, json=count)
        return httpx.Response(http_status, json={
            "id": "collection-id", "metadata": {"embed_model": model, "dimension": dimension},
        })

    original_client = httpx.Client
    monkeypatch.setattr("app.services.health.httpx.Client", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(handle),
    ))

    class FakeRedis:
        def get(self, key):
            return None

        def ping(self):
            if not redis_up:
                raise ConnectionError("offline")
            return True

        def close(self):
            pass

    monkeypatch.setattr("app.services.health.redis.Redis.from_url", lambda *a, **kw: FakeRedis())
    checks = DependencyHealth(Settings(embed_model="dummy-768")).check()
    if failed is None:
        assert all(value == "ok" for value in checks.values())
    else:
        assert checks[failed] != "ok"
    if failed == "embedding_pin":
        assert "API model=dummy-768" in checks[failed]
        assert "collection model=" in checks[failed]


def test_readiness_recovers_and_liveness_ignores_dependencies(monkeypatch):
    checks = {"chroma": "collection is empty", "redis": "ok"}
    monkeypatch.setattr(DependencyHealth, "check", lambda self: checks.copy())
    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 503
        assert client.get("/healthz").json() == {"status": "alive"}
        checks.update(chroma="ok", embedding_pin="ok")
        assert client.get("/readyz").status_code == 200
        checks["redis"] = "unavailable"
        assert client.get("/readyz").status_code == 503
        assert client.get("/healthz").status_code == 200
