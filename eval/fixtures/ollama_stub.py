"""Deterministic Ollama substitute for fictional fixture tests only."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOPICS = (
    ("hostel",),
    ("academic warning", "cgpa falls below"),
    ("attendance", "attend at least"),
    ("repeat", "grade capped"),
    ("tuition", "fee per credit hour"),
)
ANSWERS = (
    ("", ""),
    ("falls below 2.00", "The academic warning threshold is a CGPA below 2.00."),
    ("at least 80 percent", "Students must attend at least 80 percent of lectures."),
    ("most recent attempt", "The grade from the most recent attempt counts."),
    ("10,000", "The BS tuition fee is PKR 10,000 per credit hour."),
)


def topic(text: str) -> int:
    # The chunker's first line identifies the section. Only use body keywords
    # when the heading itself gives no topic.
    text = text.casefold()
    for line in (text.splitlines()[0] if text else "", text):
        for number, terms in enumerate(TOPICS):
            if any(term in line for term in terms):
                return number
    return len(TOPICS)


def vector(text: str) -> list[float]:
    index = topic(text)
    if text.startswith("3.2 ") and "ignore all previous instructions" in text.casefold():
        index = 2  # Deliberately retrieve the poisoned chunk on attendance questions.
    result = [0.0] * 768
    result[index] = 1.0
    # Give primary clauses a small edge over secondary clauses of the same topic.
    if re.match(r"^\d+\.[2-9]\s", text):
        result[len(TOPICS) + 1] = 0.5
    return result


def chat(body: dict) -> dict:
    system, user = body["messages"]
    if system["role"] != "system" or "untrusted" not in system["content"]:
        raise ValueError("missing evidence boundary")
    if not isinstance(body["format"], dict) or user["role"] != "user":
        raise ValueError("missing structured output")
    prompt = json.loads(user["content"])
    number = topic(prompt["question"])
    answer = {"reasoning": "", "answer": "", "citations": [],
              "answered_from_context": False, "confidence": "low"}
    if 0 < number < len(ANSWERS):
        fact, response = ANSWERS[number]
        if number == 2 and "august 2023" in prompt["question"].casefold():
            fact, response = "at least 75 percent", "Students must attend at least 75 percent of lectures."
        for passage in prompt["evidence"]:
            if fact not in passage["text"].casefold():
                continue
            source, section = passage["source"], passage["section"]
            answer.update(
                answer=f"{response} [{source} / {section}]",
                citations=[{"source": source, "section": section, "page": passage["page"]}],
                answered_from_context=True, confidence="high",
            )
            break
    return {"message": {"content": json.dumps(answer)}}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/embed" and body.get("model") == "fixture-embed":
                payload = {"model": "fixture-embed",
                           "embeddings": [vector(text) for text in body["input"]]}
            elif self.path == "/api/chat" and body.get("model") == "fixture-chat":
                payload = chat(body)
            else:
                self.send_error(404)
                return
        except (KeyError, TypeError, ValueError):
            self.send_error(400)
            return
        result = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 11434), Handler).serve_forever()
