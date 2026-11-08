"""Exercise readiness against isolated real Chroma/Redis containers, without a cluster."""

from __future__ import annotations

import subprocess
import time
import uuid


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=120,
    )
    return result.stdout.strip()


def main() -> None:
    network = f"rahbar-check-{uuid.uuid4().hex[:10]}"
    containers: list[str] = []
    security = (
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--network", network,
    )

    def start(*args: str) -> str:
        container = docker("run", "-d", *security, *args)
        containers.append(container)
        return container

    def expect(api: str, status: int, failed: str | None = None) -> None:
        code = f"""
import httpx
client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=10)
assert client.get('/healthz').status_code == 200
response = client.get('/readyz')
assert response.status_code == {status}, response.text
body = response.json()
failed = {failed!r}
if failed:
    assert body['checks'][failed] != 'ok', body
print(response.text)
"""
        deadline = time.monotonic() + 60
        while True:
            try:
                docker("exec", api, "python", "-c", code)
                return
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    print(docker("logs", api))
                    raise
                time.sleep(1)

    docker("network", "create", "--internal", network)
    try:
        start("--network-alias", "chroma", "--user", "10001:10001",
              "--tmpfs", "/data:rw,uid=10001,gid=10001,size=256m",
              "chromadb/chroma:1.0.12")
        redis = start("--network-alias", "redis", "--user", "999:999",
                      "--tmpfs", "/data:rw,uid=999,gid=999,size=64m",
                      "--entrypoint", "redis-server", "redis:7.4.2-bookworm",
                      "--appendonly", "yes", "--dir", "/data")
        api = start("-e", "EMBED_MODEL=dummy-768", "rahbar-api:dev")
        expect(api, 503, "chroma")
        print("PASS empty/missing index: readiness 503; liveness 200", flush=True)
        # Wait for Chroma itself before submitting the one-shot writer.
        docker("exec", api, "python", "-c", """
import time
import httpx
for attempt in range(60):
    try:
        response = httpx.get('http://chroma:8000/api/v2/heartbeat', timeout=2)
        response.raise_for_status()
        break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError('Chroma did not start')
""")
        docker("run", "--rm", *security, "-e", "EMBED_MODEL=dummy-768",
               "rahbar-indexer:dev", "python", "-m", "pipeline.run", "--dummy")
        expect(api, 200)
        print("PASS dummy index: same API process becomes ready", flush=True)
        mismatch = start("-e", "EMBED_MODEL=wrong-model", "rahbar-api:dev")
        expect(mismatch, 503, "embedding_pin")
        assert "wrong-model" in docker("logs", mismatch)
        print("PASS embedding mismatch: readiness 503 and conflict logged", flush=True)
        docker("stop", "--time", "5", redis)
        expect(api, 503, "redis")
        print("PASS Redis outage: readiness 503; liveness 200", flush=True)
        docker("start", redis)
        expect(api, 200)
        print("PASS Redis recovery: readiness returns to 200", flush=True)
    finally:
        for container in reversed(containers):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
