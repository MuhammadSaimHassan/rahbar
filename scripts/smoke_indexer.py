"""Run the real five stages on CI fixtures with synthetic embeddings and real stores."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path

from smoke_stack import docker


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    network = "rahbar-indexer-" + uuid.uuid4().hex[:10]
    containers: list[str] = []
    security = ("--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
                "--tmpfs", "/tmp:rw,size=128m", "--network", network)

    def start(*args: str) -> str:
        container = docker("run", "-d", *security, *args)
        containers.append(container)
        return container

    def in_api(code: str) -> str:
        return docker("exec", api, "python", "-c", code)

    def index() -> None:
        try:
            docker("run", "--rm", *security, "--mount",
                   f"type=bind,source={root / 'eval' / 'fixtures'},target=/corpus,readonly",
                   "-e", "CORPUS_DIR=/corpus", "-e", "EMBED_MODEL=fixture-embed",
                   "-e", "OLLAMA_URL=http://ollama:11434", "rahbar-indexer:dev")
        except subprocess.CalledProcessError as exc:
            print(exc.stdout, exc.stderr, flush=True)
            raise

    docker("network", "create", "--internal", network)
    try:
        start("--network-alias", "chroma", "--user", "10001:10001",
              "--tmpfs", "/data:rw,uid=10001,gid=10001,size=256m", "chromadb/chroma:1.0.12")
        start("--network-alias", "redis", "--user", "999:999",
              "--tmpfs", "/data:rw,uid=999,gid=999,size=64m", "--entrypoint", "redis-server",
              "redis:7.4.2-bookworm", "--dir", "/data")
        embedding_server = start("--network-alias", "ollama", "--mount",
              f"type=bind,source={root / 'eval' / 'fixtures' / 'ollama_stub.py'},target=/app/ollama_stub.py,readonly",
              "rahbar-indexer:dev", "python", "/app/ollama_stub.py")
        api = start("-e", "EMBED_MODEL=fixture-embed", "rahbar-api:dev")
        for attempt in range(60):
            try:
                in_api("import httpx; httpx.get('http://chroma:8000/api/v2/heartbeat').raise_for_status()")
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError("Chroma did not start")
        try:
            in_api("import httpx; httpx.post('http://ollama:11434/api/embed', "
                   "json={'model':'fixture-embed','input':['probe']},timeout=10).raise_for_status()")
        except subprocess.CalledProcessError:
            print(docker("logs", embedding_server), flush=True)
            raise
        index()
        old = json.loads(in_api("""
import json, httpx, redis
r = redis.Redis(host='redis', decode_responses=True)
catalog = json.loads(r.get('rahbar:index:rahbar:active'))
assert httpx.get('http://127.0.0.1:8000/readyz').status_code == 200
r.set('rahbar:cache:rahbar:' + catalog['generation'] + ':test', 'old answer')
print(json.dumps(catalog))
"""))
        print("PASS five-stage fixture index published; API follows the catalog", flush=True)
        monitor = """
import json, time, httpx
from pathlib import Path
statuses=[]
with httpx.Client(timeout=10) as client:
    while not Path('/tmp/stop-monitor').exists():
        statuses.append(client.get('http://127.0.0.1:8000/readyz').status_code)
        time.sleep(0.1)
Path('/tmp/readiness-observed.json').write_text(json.dumps(statuses))
"""
        docker("exec", "-d", api, "python", "-c", monitor)
        index()
        in_api("from pathlib import Path; Path('/tmp/stop-monitor').touch()")
        observed = None
        for attempt in range(30):
            try:
                observed = json.loads(in_api(
                    "from pathlib import Path; print(Path('/tmp/readiness-observed.json').read_text())",
                ))
                break
            except subprocess.CalledProcessError:
                time.sleep(0.2)
        assert observed and all(status == 200 for status in observed), observed
        new = json.loads(in_api("""
import json, redis
r=redis.Redis(host='redis',decode_responses=True)
print(r.get('rahbar:index:rahbar:active'))
"""))
        assert old["generation"] != new["generation"]
        verification = f"""
import httpx, redis
r=redis.Redis(host='redis')
assert not r.exists('rahbar:cache:rahbar:{old['generation']}:test')
base='http://chroma:8000/api/v2/tenants/default_tenant/databases/default_database/collections/'
for name in [{old['collection']!r}, {new['collection']!r}]:
    response=httpx.get(base+name); response.raise_for_status()
    meta=response.json()['metadata']
    assert meta['embed_model']=='fixture-embed' and meta['dimension']==768
print('old and new collections retained; old cache removed')
"""
        in_api(verification)
        print(f"PASS re-index: {len(observed)} readiness checks stayed 200", flush=True)
        print("PASS old index retained; generation changed; previous cache invalidated", flush=True)
        print("Embeddings were synthetic test vectors; this is not a retrieval-quality result.", flush=True)
    finally:
        for container in reversed(containers):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
