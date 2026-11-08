from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.config import Settings
from app.providers.llm.hosted import HostedProvider
from app.schemas import Answer, Citation, Passage
from app.services.answer import FALLBACK, generate


def evidence() -> Passage:
    return Passage(chunk_id="rule", source="rules.pdf", section="Attendance", page=1,
                   text="Attendance is mandatory.", score=0.9)


def test_hosted_requests_a_closed_schema_and_validates_provenance(monkeypatch) -> None:
    settings = Settings(llm_provider="hosted", hosted_base_url="https://model.example/v1",
                        llm_api_key="test-token")
    answer = Answer(reasoning="", answer="Attendance is mandatory.", answered_from_context=True,
                    confidence="high", citations=[Citation(source="rules.pdf", section="Attendance", page=1)])

    def post(url, *, headers, json, **kwargs):
        assert url == "https://model.example/v1/chat/completions"
        assert headers == {"Authorization": "Bearer test-token"}
        assert kwargs["follow_redirects"] is False
        schema = json["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        citation = schema["schema"]["$defs"]["Citation"]
        assert citation["additionalProperties"] is False
        assert set(citation["required"]) == {"source", "section", "page"}
        assert "default" not in citation["properties"]["page"]
        assert "untrusted" in json["messages"][0]["content"]
        return httpx.Response(
            200, request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": answer.model_dump_json()}}],
                  "usage": {"prompt_tokens": 12, "completion_tokens": 8}},
        )

    monkeypatch.setattr(httpx, "post", post)
    result, cacheable = generate("Is attendance mandatory?", [evidence()], HostedProvider(settings))
    assert result.answer.endswith("[rules.pdf / Attendance]")
    assert cacheable


@pytest.mark.parametrize("payload", [
    [], {"choices": []}, {"usage": 12}, {"choices": [{"message": {"content": "not JSON"}}]},
])
def test_malformed_hosted_output_retries_then_falls_back(monkeypatch, payload) -> None:
    calls = []
    settings = Settings(hosted_base_url="https://model.example/v1", llm_api_key="test-token")

    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url), json=payload)

    monkeypatch.setattr(httpx, "post", post)
    result, cacheable = generate("Is attendance mandatory?", [evidence()], HostedProvider(settings))
    assert len(calls) == 2
    assert result.answer == FALLBACK
    assert not cacheable


def test_hosted_rejects_missing_credentials_before_sending(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("request must not be sent")

    monkeypatch.setattr(httpx, "post", unexpected)
    settings = Settings(hosted_base_url="https://model.example/v1")
    for config in (settings, replace(settings, hosted_base_url="http://model.example", llm_api_key="x")):
        with pytest.raises(ValueError):
            HostedProvider(config).generate("What is the rule?", [evidence()])
