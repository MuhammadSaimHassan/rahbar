"""Schema-constrained generation through a compatible hosted Chat Completions API."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from ...config import Settings
from ...routes.metrics import record_tokens
from ...schemas import Answer, Passage
from .prompt import messages, strict_schema


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        settings = self.settings
        endpoint = urlsplit(settings.hosted_base_url)
        if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username
                or endpoint.password or endpoint.query or endpoint.fragment
                or not settings.llm_api_key.strip()):
            raise ValueError("Hosted generation requires an HTTPS base URL and API key")
        response = httpx.post(
            settings.hosted_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": messages(question, passages),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "rahbar_answer", "strict": True, "schema": strict_schema()},
                },
                "temperature": settings.temperature,
                "stream": False,
            },
            timeout=settings.generation_timeout,
            trust_env=False,
            follow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("usage") or {}, dict):
            raise ValueError("Invalid hosted response envelope")
        for kind, key in (("prompt", "prompt_tokens"), ("completion", "completion_tokens")):
            count = (data.get("usage") or {}).get(key)
            record_tokens(kind, count)
        return Answer.model_validate_json(data["choices"][0]["message"]["content"], strict=True)
