"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    checks = request.app.state.dependency_health.check()
    ready = all(value == "ok" for value in checks.values())
    response.status_code = 200 if ready else 503
    return {"status": "ready" if ready else "not_ready", "checks": checks}
