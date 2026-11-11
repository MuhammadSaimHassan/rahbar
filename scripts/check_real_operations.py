"""Controlled real operations, restricted to an explicitly owned acceptance context."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import threading
import time
from pathlib import Path

import httpx

from scripts.check_real_acceptance import Cluster, QUESTION, validate_grounded


def validate_denial(control: int, returncode: int, output: str) -> None:
    if control != 0 or returncode == 0 or "timed out" not in output.lower():
        raise ValueError("Denial needs a working client and an actual network timeout")


def validate_pin(probe: dict) -> None:
    if (probe.get("live") != 200 or probe.get("ready") != 503
            or "mismatch:" not in probe.get("checks", {}).get("embedding_pin", "")):
        raise ValueError("Pin probe must be live but explicitly unready for a model mismatch")


class Lab(Cluster):
    def get(self, *args: str) -> dict:
        return json.loads(self.run("get", *args, "-o", "json"))

    def apply(self, document: dict) -> None:
        subprocess.run(["kubectl", "--context", self.context, "-n", "rahbar", "apply", "-f", "-"],
                       input=json.dumps(document), text=True, check=True, timeout=60,
                       capture_output=True)

    def code(self, source: str, target: str = "deployment/api") -> dict:
        return json.loads(self.run("exec", target, "--", "python", "-c", source))

    def snapshot(self) -> dict:
        return self.code("""
import os,json,redis,httpx
from urllib.parse import quote
r=redis.Redis.from_url(os.environ['REDIS_URL'],decode_responses=True)
catalog=json.loads(r.get('rahbar:index:rahbar:active'))
base='http://chroma:8000/api/v2/tenants/default_tenant/databases/default_database/collections'
with httpx.Client(timeout=10,trust_env=False) as c:
 a=c.get(base+'/'+quote(catalog['collection'],safe=''));a.raise_for_status();item=a.json()
 b=c.get(base+'/'+item['id']+'/count');b.raise_for_status()
 print(json.dumps({'catalog':catalog,'count':b.json(),'metadata':item['metadata'],
 'cache_keys':list(r.scan_iter(match='rahbar:cache:rahbar:*'))}))
""")

    def wait_job(self, name: str, timeout: int = 2400) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get("job", name)
            conditions = {c["type"] for c in job.get("status", {}).get("conditions", [])
                          if c.get("status") == "True"}
            if "Complete" in conditions:
                return
            if conditions.intersection({"Failed", "FailureTarget"}):
                raise RuntimeError(f"{name} failed: {conditions}")
            time.sleep(3)
        raise RuntimeError(f"{name} exceeded {timeout}s")


def run(args: argparse.Namespace) -> dict:
    lab = Lab(args.context)
    result: dict = {"passed": False, "context": args.context, "traffic": []}
    expected = json.loads(Path("eval/relevance.current.json").read_text())["chunks_sha256"]
    stopped = threading.Event()
    worker = None
    canary_created = False
    args.out.parent.mkdir(parents=True, exist_ok=True)

    def ask(client: httpx.Client) -> dict:
        before = time.monotonic()
        response = client.post("/api/ask", json={"question": QUESTION})
        response.raise_for_status()
        validate_grounded(response.json(), response.headers, expected)
        return {"ok": True, "seconds": round(time.monotonic()-before, 3),
                "generation": response.headers["x-index-generation"],
                "cache": response.headers.get("x-cache"), "status": response.status_code}

    def sampler() -> None:
        with httpx.Client(base_url=args.api, headers={"Host": "rahbar.local"},
                          trust_env=False, timeout=300) as client:
            while not stopped.is_set():
                try:
                    row = ask(client)
                except Exception as exc:
                    row = {"ok": False, "error": str(exc)}
                result["traffic"].append(row)
                stopped.wait(2)

    try:
        # Same tool's local positive control rules out missing/broken wget.
        positive = subprocess.run(["kubectl", "--context", args.context, "-n", "rahbar",
                                   "exec", "deployment/ui", "--", "wget", "-T", "5", "-q", "-O-",
                                   "http://127.0.0.1:8080/healthz"], capture_output=True, text=True,
                                  timeout=30)
        allowed = lab.code("import httpx,json; r=httpx.get('http://chroma:8000/api/v2/heartbeat',timeout=10,trust_env=False); r.raise_for_status(); print(json.dumps({'status':r.status_code}))")
        ip = lab.get("pod", "chroma-0")["status"]["podIP"]
        blocked = subprocess.run(["kubectl", "--context", args.context, "-n", "rahbar", "exec",
                                  "deployment/ui", "--", "wget", "-T", "5", "-q", "-O-",
                                  f"http://{ip}:8000/api/v2/heartbeat"], capture_output=True,
                                 text=True, timeout=30)
        validate_denial(positive.returncode, blocked.returncode, blocked.stdout+blocked.stderr)
        result["network_policy"] = {"api_positive_control": allowed, "ui_local_control": positive.returncode,
                                    "ui_to_chroma_returncode": blocked.returncode,
                                    "ui_to_chroma_output": blocked.stdout+blocked.stderr}
        print("Real Calico denial and positive controls passed", flush=True)

        before = lab.snapshot()
        old_pod = lab.get("pod", "chroma-0")["metadata"]["uid"]
        pvc = lab.get("pvc", "data-chroma-0")["metadata"]["uid"]
        lab.run("delete", "pod", "chroma-0", "--wait=true", "--timeout=120s")
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            try:
                pod = lab.get("pod", "chroma-0")
                if (pod["metadata"]["uid"] != old_pod and any(c["type"] == "Ready" and c["status"] == "True"
                        for c in pod.get("status", {}).get("conditions", []))):
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(3)
        else:
            raise RuntimeError("Chroma replacement did not become ready")
        after = lab.snapshot()
        if (pvc != lab.get("pvc", "data-chroma-0")["metadata"]["uid"]
                or before["catalog"] != after["catalog"] or before["metadata"] != after["metadata"]
                or after["count"] != 950):
            raise RuntimeError("PVC replacement did not preserve the published real index")
        result["pvc_persistence"] = {"before": before, "after": after, "pvc_uid": pvc,
                                     "old_pod_uid": old_pod, "new_pod_uid": pod["metadata"]["uid"]}
        print("Real Chroma PVC persistence passed", flush=True)

        template = copy.deepcopy(lab.get("deployment", "api")["spec"]["template"])
        spec = template["spec"]
        spec["restartPolicy"] = "Never"
        spec["containers"][0].setdefault("env", []).append({"name": "EMBED_MODEL", "value": "wrong-model-for-pin-probe"})
        lab.apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "real-pin-probe",
                   "namespace": "rahbar", "labels": {"app": "api", "purpose": "pin-probe"}}, "spec": spec})
        canary_created = True
        probe_source = """
import httpx,json
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=20,trust_env=False) as c:
 live=c.get('/healthz');ready=c.get('/readyz')
 print(json.dumps({'live':live.status_code,'ready':ready.status_code,'checks':ready.json()['checks']}))
"""
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            try:
                probe = lab.code(probe_source, "pod/real-pin-probe")
                validate_pin(probe)
                break
            except (subprocess.CalledProcessError, ValueError):
                time.sleep(3)
        else:
            raise RuntimeError("Live model-pin mismatch was not demonstrated")
        result["pin_probe"] = probe
        result["pin_probe_logs"] = lab.run("logs", "real-pin-probe", "--tail=30")
        lab.run("delete", "pod", "real-pin-probe", "--wait=true", "--timeout=120s")
        canary_created = False
        print("Live pin-mismatch readiness and liveness passed", flush=True)

        with httpx.Client(base_url=args.api, headers={"Host": "rahbar.local"},
                          trust_env=False, timeout=300) as client:
            # Recover API ready endpoints after the brief singleton Chroma outage.
            lab.run("rollout", "status", "deployment/api", "--timeout=300s")
            result["before_reindex_answer"] = ask(client)
            before = lab.snapshot()
            old_generation = before["catalog"]["generation"]
            if not any(f":{old_generation}:" in k for k in before["cache_keys"]):
                ask(client)
                before = lab.snapshot()
            if not any(f":{old_generation}:" in k for k in before["cache_keys"]):
                raise RuntimeError("Reindex continuity requires a genuinely warmed old cache")
            job = json.loads(lab.run("create", "job", "real-reindex", "--from=cronjob/reindex",
                                     "--dry-run=client", "-o", "json"))
            worker = threading.Thread(target=sampler, daemon=True)
            worker.start()
            lab.apply(job)
            lab.wait_job("real-reindex")
            after = lab.snapshot()
            new_generation = after["catalog"]["generation"]
            if (new_generation == old_generation or after["count"] != 950
                    or after["metadata"].get("chunks_sha256") != expected
                    or after["catalog"]["embed_model"] != "nomic-embed-text"
                    or after["catalog"]["dimension"] != 768):
                raise RuntimeError("Reindex failed to publish a complete same-pin new generation")
            row = ask(client)
            if row["generation"] != new_generation:
                raise RuntimeError("Answer did not move to the newly published generation")
            result["after_reindex_answer"] = row
            stopped.set()
            worker.join(timeout=310)
            if worker.is_alive() or not result["traffic"] or any(not r["ok"] for r in result["traffic"]):
                raise RuntimeError("A sampled grounded request failed during real reindexing")
            result["reindex"] = {"before": before, "after": after,
                                 "job": "real-reindex", "traffic_kind": "warmed supported question; publication may cause a miss"}
        result["passed"] = True
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        stopped.set()
        if worker is not None and worker.is_alive():
            worker.join(timeout=310)
        if canary_created:
            try:
                lab.run("delete", "pod", "real-pin-probe", "--wait=false")
            except subprocess.SubprocessError:
                pass
        try:
            result["reindex_logs"] = lab.run("logs", "job/real-reindex", "--tail=50")
        except subprocess.SubprocessError:
            pass
        args.out.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args)
    print("Real runtime checks passed")


if __name__ == "__main__":
    main()
