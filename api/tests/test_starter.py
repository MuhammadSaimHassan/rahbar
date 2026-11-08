"""Starter tests: they pin down the contract the UI and eval script rely on.

They run with the stub retriever and stub provider: no cluster, no model, no
network. Keep them passing, and add your own next to them (section 6).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    # Contract tests stay offline; dependency behavior has its own focused tests.
    monkeypatch.setattr("app.services.health.DependencyHealth.check", lambda self: {
        "chroma": "ok", "embedding_pin": "ok", "redis": "ok",
    })
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_liveness_answers_without_dependencies(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


def test_ask_returns_the_response_contract(client: TestClient) -> None:
    from app.schemas import AskResponse

    r = client.post("/api/ask", json={"question": "What is the attendance requirement?"})
    assert r.status_code == 200
    body = AskResponse(**r.json())          # raises if any field is missing or mistyped
    assert body.provider == "stub"
    assert len(body.retrieved) == 3


def test_every_citation_names_a_retrieved_passage(client: TestClient) -> None:
    r = client.post("/api/ask", json={"question": "What does the stub say?"}).json()
    retrieved = {(p["source"], p["section"]) for p in r["retrieved"]}
    assert r["citations"]
    for c in r["citations"]:
        assert (c["source"], c["section"]) in retrieved


def test_request_id_is_echoed(client: TestClient) -> None:
    r = client.post("/api/ask", json={"question": "Echo my id please"},
                    headers={"X-Request-ID": "test-123"})
    assert r.headers["X-Request-ID"] == "test-123"
    assert r.json()["request_id"] == "test-123"


@pytest.mark.parametrize("question", ["hi", "x" * 501, "   ", " a "])
def test_question_length_is_enforced(client: TestClient, question: str) -> None:
    r = client.post("/api/ask", json={"question": question})
    assert r.status_code == 422


def test_metrics_count_requests_by_route(client: TestClient) -> None:
    client.post("/api/ask", json={"question": "Count this request"})
    text = client.get("/metrics").text
    assert 'rahbar_requests_total{path="/api/ask",status="200"}' in text


def test_token_usage_is_logged_per_request_without_leaking_to_the_next(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routes.metrics import record_tokens

    records = []
    provider = client.app.state.provider
    original = provider.generate

    def generate(question, passages):
        record_tokens("prompt", 3)
        record_tokens("completion", 7)
        return original(question, passages)

    monkeypatch.setattr(provider, "generate", generate)
    monkeypatch.setattr("app.main.log.info",
                        lambda message, **kwargs: records.append((message, kwargs)))
    client.post("/api/ask", json={"question": "What is attendance?"})
    monkeypatch.setattr(provider, "generate", original)
    client.post("/api/ask", json={"question": "What is attendance?"})
    requests = [item[1]["extra"] for item in records if item[0] == "request"]
    assert [(item["tokens_in"], item["tokens_out"]) for item in requests] == [(3, 7), (0, 0)]
