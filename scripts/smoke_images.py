"""Check local images without a cluster, model or published host ports.

Run after building the images: python3 scripts/smoke_images.py
"""

from __future__ import annotations

import argparse
import subprocess
import time


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=90,
    )
    return result.stdout.strip()


SECURITY = (
    "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
    "--network", "none",
)


def service(image: str, probe: list[str]) -> None:
    container = docker("run", "--rm", "-d", *SECURITY, image)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                output = docker("exec", container, *probe)
                print(f"PASS {image}: {output}")
                return
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    print(docker("logs", container))
                    raise
                time.sleep(0.5)
    finally:
        docker("stop", "--time", "5", container)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="dev")
    args = parser.parse_args()
    api_probe = """
import os
import httpx
assert os.getuid() != 0
with httpx.Client(base_url='http://127.0.0.1:8000', timeout=5) as client:
    health = client.get('/healthz')
    assert health.status_code == 200, health.text
    response = client.post('/api/ask', json={'question': 'What is in the handbook?'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['provider'] == 'stub', body
    assert len(body['retrieved']) == 3, body
    assert body['citations'], body
    assert all(any(all(c[key] == r[key] for key in ('source', 'section', 'page'))
                   for r in body['retrieved']) for c in body['citations']), body
    assert client.post('/api/ask', json={'question': 'x'}).status_code == 422
print('non-root; health, stub answer, citations and input validation passed')
"""
    service(f"rahbar-api:{args.tag}", ["python", "-c", api_probe])
    service(f"rahbar-ui:{args.tag}", [
        "sh", "-c",
        'test "$(id -u)" != 0 && '
        'wget -qO- http://127.0.0.1:8080/healthz && '
        'wget -qO /dev/null http://127.0.0.1:8080/',
    ])
    indexer = f"rahbar-indexer:{args.tag}"
    docker("run", "--rm", *SECURITY, indexer, "python", "-c",
           "import os; assert os.getuid() != 0")
    docker("run", "--rm", *SECURITY, indexer, "python", "-m", "pipeline.run", "--help")
    docker("run", "--rm", *SECURITY, indexer, "tesseract", "--version")
    docker("run", "--rm", *SECURITY, indexer, "pdftoppm", "-v")
    print(f"PASS {indexer}: non-root; CLI, Tesseract and Poppler available")


if __name__ == "__main__":
    main()
