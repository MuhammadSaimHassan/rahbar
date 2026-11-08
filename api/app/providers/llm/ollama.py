"""Schema-constrained answers from host or in-cluster Ollama."""

from __future__ import annotations

import httpx

from ...config import Settings
from ...routes.metrics import record_tokens
from ...schemas import Answer, Passage
from .prompt import messages


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        settings = self.settings
        options: dict[str, float | bool] = {"temperature": settings.temperature}
        if settings.ollama_use_mmap:
            options["use_mmap"] = True
        response = httpx.post(
            f"{settings.ollama_url.rstrip('/')}/api/chat",
            json={
                "model": settings.llm_model,
                "messages": messages(question, passages),
                "format": Answer.model_json_schema(),
                "options": options,
                "stream": False,
            },
            timeout=settings.generation_timeout, trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid Ollama response envelope")
        for kind, key in (("prompt", "prompt_eval_count"), ("completion", "eval_count")):
            count = data.get(key)
            record_tokens(kind, count)
        return Answer.model_validate_json(data["message"]["content"], strict=True)
