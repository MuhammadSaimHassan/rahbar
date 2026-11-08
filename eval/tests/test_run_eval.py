from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.run_eval import GOLDEN, HERE, gate, load_golden, load_projection, summarise


def test_alternative_chunk_ids_count_as_one_evidence_unit() -> None:
    questions = load_golden(GOLDEN)
    units = load_projection(HERE / "relevance.current.json", GOLDEN, questions)["questions"]["o01"]
    first, second = units[0]["chunk_ids"]
    retrieved = [{"chunk_id": "irrelevant", "source": "other", "section": "other"}] * 3 + [
        {"chunk_id": first, "source": "actual", "section": "display heading", "page": 24},
        {"chunk_id": second, "source": "actual", "section": "display heading", "page": 25},
    ]
    result = summarise([{
        "id": "o01", "type": "ordinary", "relevant": units, "must_abstain": False,
        "response": {
            "retrieved": retrieved, "answered_from_context": True,
            "citations": [
                {"source": "actual", "section": "display heading", "page": 24},
                {"source": "actual", "section": "display heading", "page": 99},
            ],
        },
    }])
    assert result["recall@3"] == 0
    assert result["recall@5"] == 1
    assert result["citation_validity"] == 0.5
    assert result["by_type"]["ordinary"]["recall@5"] == 1


def test_fallback_does_not_pass_abstention() -> None:
    result = summarise([{
        "id": "a01", "type": "abstain", "relevant": [], "must_abstain": True,
        "outcome": "fallback",
        "response": {"retrieved": [], "citations": [], "answered_from_context": False},
    }])
    assert result["recall@5"] is None
    assert result["abstention_correctness"] == 0
    assert len(gate(result, None)) == 3


def test_gate_accepts_exact_boundary_and_rejects_larger_drop() -> None:
    baseline = {"recall@5": 0.9, "golden_sha256": "fixed"}
    results = {"recall@5": 0.85, "citation_validity": 0.95,
               "abstention_correctness": 1.0, "golden_sha256": "fixed"}
    assert not gate(results, baseline)
    assert "fell" in gate(results | {"recall@5": 0.849}, baseline)[0]
    assert "different golden set" in gate(results | {"golden_sha256": "other"}, baseline)[0]


def test_projection_rejects_wrong_golden_hash(tmp_path: Path) -> None:
    path = tmp_path / "projection.json"
    data = json.loads((HERE / "relevance.current.json").read_text(encoding="utf-8"))
    path.write_text(json.dumps(data | {"golden_sha256": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_projection(path, GOLDEN, load_golden(GOLDEN))


def test_evaluator_rejects_a_different_live_chunk_export(monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    import httpx

    from eval.run_eval import evaluate

    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"provider": "ollama"},
            headers={"X-Index-Chunks-SHA256": "0" * 64},
        )

    client = httpx.Client(transport=httpx.MockTransport(reply))
    monkeypatch.setattr("eval.run_eval.httpx.Client", lambda **kwargs: client)
    with pytest.raises(ValueError, match="live index chunk hash"):
        evaluate(argparse.Namespace(
            golden=GOLDEN, projection=None, host=None, api="http://fixture.local", timeout=300, checkpoint=None,
        ))


@pytest.mark.parametrize("decline", [True, False])
def test_cli_updates_baseline_only_when_gates_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decline: bool,
) -> None:
    import sys

    import httpx

    from eval.run_eval import main

    golden = HERE / "fixtures" / "golden.fixture.yaml"
    questions = {q["question"]: q for q in load_golden(golden)}
    baseline = tmp_path / "baseline.json"
    output = tmp_path / "results.json"

    def reply(request: httpx.Request) -> httpx.Response:
        question = questions[json.loads(request.content)["question"]]
        passages = [dict(unit, page=1) for unit in question.get("relevant", [])]
        return httpx.Response(200, json={
            "retrieved": passages, "citations": passages,
            "answered_from_context": bool(passages) or not decline,
        })

    client = httpx.Client(transport=httpx.MockTransport(reply))
    monkeypatch.setattr("eval.run_eval.httpx.Client", lambda **kwargs: client)
    monkeypatch.setattr(sys, "argv", [
        "run_eval.py", "--api", "http://fixture.local", "--golden", str(golden),
        "--baseline", str(baseline), "--out", str(output), "--update-baseline",
    ])
    assert main() == (0 if decline else 1)
    assert output.is_file()
    assert baseline.exists() is decline


def test_checkpoint_resumes_from_the_next_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import argparse

    import httpx

    from eval.run_eval import evaluate

    projection = json.loads((HERE / "relevance.current.json").read_text(encoding="utf-8"))
    fingerprint = projection["chunks_sha256"]
    questions = load_golden(GOLDEN)
    checkpoint = tmp_path / "partial.json"
    queries: list[str] = []
    fail_second = True

    def reply(request: httpx.Request) -> httpx.Response:
        question = json.loads(request.content)["question"]
        queries.append(question)
        chunk_hash = "0" * 64 if fail_second and len(queries) == 2 else fingerprint
        return httpx.Response(
            200,
            json={"provider": "ollama", "retrieved": [], "citations": [],
                  "answered_from_context": False},
            headers={"X-Index-Chunks-SHA256": chunk_hash, "X-Index-Generation": "a" * 32},
        )

    make_client = httpx.Client
    monkeypatch.setattr(
        "eval.run_eval.httpx.Client", lambda **kwargs: make_client(transport=httpx.MockTransport(reply)),
    )
    args = argparse.Namespace(
        golden=GOLDEN, projection=None, host=None, api="http://fixture.local",
        timeout=300, checkpoint=checkpoint,
    )
    with pytest.raises(ValueError, match="live index chunk hash"):
        evaluate(args)
    assert [row["id"] for row in json.loads(checkpoint.read_text())["rows"]] == ["o01"]
    fail_second = False
    queries.clear()
    assert evaluate(args)["questions"] == 20
    assert queries == [q["question"] for q in questions[1:]]
