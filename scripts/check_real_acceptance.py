"""Real-corpus Ingress acceptance; never substitutes fictional fixture output."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import httpx

QUESTION = "What minimum CGPA avoids academic warning under the June 2026 rules?"
ABSENT = "What are the current Islamabad shuttle departure times?"
SOURCE = "academic-rules-handbook-jun-2026.pdf"


def validate_grounded(body: dict, headers: dict, expected_hash: str) -> None:
    if body.get("provider") != "ollama" or headers.get("x-answer-outcome") != "grounded":
        raise ValueError("Expected genuine Ollama grounding, not stub, fallback or abstention")
    if body.get("answered_from_context") is not True:
        raise ValueError("Supported question was not answered from context")
    if not re.search(r"\b2(?:\.0+)?\b", body.get("answer", "")):
        raise ValueError("CGPA answer does not contain the source-authored 2.00 fact")
    retrieved = {(x.get("source"), x.get("section"), x.get("page"))
                 for x in body.get("retrieved", [])}
    citations = body.get("citations", [])
    if not citations or any((x.get("source"), x.get("section"), x.get("page"))
                            not in retrieved for x in citations):
        raise ValueError("A citation does not match retrieved evidence")
    if not any(x.get("source") == SOURCE for x in citations):
        raise ValueError("Current-policy answer lacks a current academic-rules citation")
    if headers.get("x-index-chunks-sha256") != expected_hash:
        raise ValueError("Fresh index does not reproduce the frozen 400/50 fingerprint")
    if not headers.get("x-index-generation"):
        raise ValueError("No published index generation was reported")


def validate_abstention(body: dict, headers: dict) -> None:
    if (headers.get("x-answer-outcome") != "abstained"
            or body.get("answered_from_context") is not False or body.get("citations")):
        raise ValueError("Absent topic did not correctly abstain; fallback is not abstention")
    if body.get("provider") != "ollama":
        raise ValueError("Absent-topic check used the wrong provider")


class Cluster:
    def __init__(self, context: str) -> None:
        if not context.startswith("rahbar-real-"):
            raise ValueError("Use an explicitly named ephemeral real acceptance context")
        self.context = context

    def run(self, *args: str) -> str:
        result = subprocess.run(
            ["kubectl", "--context", self.context, "-n", "rahbar", *args],
            check=True, capture_output=True, text=True, timeout=360,
        )
        return result.stdout

    def pods(self) -> list[dict]:
        return json.loads(self.run("get", "pods", "-l", "app=api", "-o", "json"))["items"]

    def ready(self) -> list[dict]:
        return [p for p in self.pods() if not p["metadata"].get("deletionTimestamp")
                and any(c.get("type") == "Ready" and c.get("status") == "True"
                        for c in p.get("status", {}).get("conditions", []))]


def writer_measurements(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"RAHBAR_INDEXER_REPORT_START\s*(.*?)\s*RAHBAR_INDEXER_REPORT_END",
                      text, re.S)
    if match is None:
        raise ValueError("Missing measured production indexer report")
    report = json.loads(match.group(1))
    peak = re.search(r"RAHBAR_INDEXER_CGROUP_PEAK_BYTES=(\d+)", text)
    report["whole_container_peak_bytes"] = int(peak.group(1)) if peak else None
    report["memory_limit_bytes"] = 1024 ** 3
    if report.get("mode") != "published" or report.get("chunk_count") != 950:
        raise ValueError("Expected a genuinely published 950-chunk real index")
    if report.get("embed_model") != "nomic-embed-text" or report.get("dimension") != 768:
        raise ValueError("Production indexer did not use the shared Nomic/768 pin")
    if len(report.get("documents", [])) != 9:
        raise ValueError("Expected all nine verified real sources")
    return report


def run(args: argparse.Namespace) -> dict:
    cluster = Cluster(args.context)
    expected_hash = json.loads(
        (Path(__file__).resolve().parents[1] / "eval/relevance.current.json")
        .read_text(encoding="utf-8")
    )["chunks_sha256"]
    report: dict = {"passed": False, "context": args.context, "api": args.api,
                    "provider": "ollama", "source": "fresh verified real corpus",
                    "requests_during_pod_replacement": []}
    stopped = threading.Event()
    started = threading.Event()
    worker = None

    def ask(client: httpx.Client, question: str) -> dict:
        before = time.monotonic()
        response = client.post("/api/ask", json={"question": question})
        response.raise_for_status()
        return {"seconds": round(time.monotonic() - before, 3),
                "http_status": response.status_code,
                "headers": {name: response.headers.get(name) for name in (
                    "x-answer-outcome", "x-cache", "x-index-generation",
                    "x-index-chunks-sha256")}, "response": response.json()}

    def sampler() -> None:
        with httpx.Client(base_url=args.api, headers={"Host": "rahbar.local"},
                          timeout=300, trust_env=False) as client:
            started.set()
            while not stopped.is_set():
                try:
                    row = ask(client, QUESTION)
                    validate_grounded(row["response"], row["headers"], expected_hash)
                    row["ok"] = True
                except Exception as exc:
                    row = {"ok": False, "error": str(exc)}
                report["requests_during_pod_replacement"].append(row)
                stopped.wait(0.5)

    try:
        report["indexer"] = writer_measurements(args.indexer_log)
        with httpx.Client(base_url=args.api, headers={"Host": "rahbar.local"},
                          timeout=300, trust_env=False) as client:
            ui = client.get("/")
            ui.raise_for_status()
            if "RAHBAR" not in ui.text:
                raise ValueError("Ingress did not serve the actual UI")
            report["ui_status"] = ui.status_code
            row = ask(client, QUESTION)
            report["supported_question"] = row
            validate_grounded(row["response"], row["headers"], expected_hash)
            absent = ask(client, ABSENT)
            report["absent_question"] = absent
            validate_abstention(absent["response"], absent["headers"])
            warm = ask(client, QUESTION)
            report["warm_supported_question"] = warm
            validate_grounded(warm["response"], warm["headers"], expected_hash)
            ready = cluster.ready()
            if len(ready) < 3:
                raise ValueError("Fewer than three ready API replicas before replacement")
            slices = json.loads(cluster.run(
                "get", "endpointslices", "-l", "kubernetes.io/service-name=api", "-o", "json",
            ))
            addresses = {address for item in slices["items"] for endpoint in item["endpoints"]
                         if endpoint.get("conditions", {}).get("ready") is True
                         for address in endpoint["addresses"]}
            if len(addresses) < 3:
                raise ValueError("Fewer than three ready Service endpoint addresses")
            report["ready_endpoint_addresses"] = sorted(addresses)
            deleted = ready[0]["metadata"]
            report["deleted_pod_uid"] = deleted["uid"]
            worker = threading.Thread(target=sampler, daemon=True)
            worker.start()
            if not started.wait(10):
                raise RuntimeError("Traffic sampler did not start")
            cluster.run("delete", "pod", deleted["name"], "--wait=true", "--timeout=360s")
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                ready = cluster.ready()
                if (len(ready) >= 3
                        and deleted["uid"] not in {p["metadata"]["uid"] for p in ready}):
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Replacement replica did not become ready")
            report["replacement_ready_pods"] = [p["metadata"]["name"] for p in ready]
            row = ask(client, QUESTION)
            report["after_pod_replacement"] = row
            validate_grounded(row["response"], row["headers"], expected_hash)
            stopped.set()
            worker.join(timeout=310)
            if worker.is_alive():
                raise RuntimeError("Traffic sampler did not finish")
            rows = report["requests_during_pod_replacement"]
            if not rows or any(not row["ok"] for row in rows):
                raise ValueError("A sampled request failed during API Pod replacement")
            report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        stopped.set()
        if worker is not None and worker.is_alive():
            worker.join(timeout=310)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--indexer-log", type=Path, required=True)
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({"passed": report["passed"],
                      "traffic_samples": len(report["requests_during_pod_replacement"])}))


if __name__ == "__main__":
    main()
