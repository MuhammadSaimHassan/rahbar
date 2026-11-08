"""Measure rollout, rollback, replica readiness and pod replacement on a named lab deployment.

Requires an explicit kubectl context, namespace, reachable API URL, and alternate
image reference. Saves observations even on failure and restores changed settings.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

import httpx


class Cluster:
    def __init__(self, context: str, namespace: str) -> None:
        self.prefix = ["kubectl", "--context", context, "--namespace", namespace]

    def run(self, *args: str) -> str:
        return subprocess.run(
            [*self.prefix, *args], check=True, capture_output=True, text=True, timeout=360,
        ).stdout

    def get(self, *args: str) -> dict:
        return json.loads(self.run("get", *args, "-o", "json"))

    def rollout(self, deployment: str) -> None:
        self.run("rollout", "status", f"deployment/{deployment}", "--timeout=300s")


def demo(args: argparse.Namespace) -> dict:
    cluster = Cluster(args.context, args.namespace)
    deployment = cluster.get("deployment", args.deployment)
    containers = deployment["spec"]["template"]["spec"]["containers"]
    original = next(container["image"] for container in containers if container["name"] == args.container)
    replicas = deployment["spec"].get("replicas", 1)
    if original == args.image:
        raise ValueError("--image must differ from the current image reference")
    if deployment["spec"].get("strategy", {}).get("type") != "RollingUpdate":
        raise ValueError("demonstration requires a RollingUpdate deployment")
    hpas = [
        hpa for hpa in cluster.get("hpa")["items"]
        if hpa["spec"]["scaleTargetRef"].get("name") == args.deployment
        and hpa["spec"]["scaleTargetRef"].get("kind") == "Deployment"
    ]
    hpa_specs = [(hpa["metadata"]["name"], hpa["spec"]) for hpa in hpas]
    report: dict = {"context": args.context, "namespace": args.namespace,
                    "original_image": original, "alternate_image": args.image, "requests": []}
    stopped = threading.Event()

    def monitor() -> None:
        with httpx.Client(timeout=args.request_timeout, trust_env=False) as client:
            while not stopped.is_set():
                started = time.monotonic()
                row: dict = {}
                try:
                    response = client.post(
                        args.api.rstrip("/") + "/api/ask", headers={"Host": args.host},
                        json={"question": args.question},
                    )
                    row["stage"] = report.get("stage", "baseline")
                    row["status"] = response.status_code
                    response.raise_for_status()
                    body = response.json()
                    row["ok"] = (isinstance(body.get("answer"), str) and bool(body["answer"])
                                 and response.headers.get("X-Answer-Outcome") != "fallback")
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    row.update(ok=False, error=type(exc).__name__)
                row["seconds"] = round(time.monotonic() - started, 3)
                report["requests"].append(row)
                stopped.wait(0.25)

    worker = threading.Thread(target=monitor)
    try:
        for name, spec in hpa_specs:
            patch = {"spec": {"minReplicas": max(3, replicas),
                              "maxReplicas": max(3, replicas)}}
            cluster.run("patch", "hpa", name, "--type=merge", "-p", json.dumps(patch))
        cluster.run("scale", f"deployment/{args.deployment}", f"--replicas={max(3, replicas)}")
        cluster.rollout(args.deployment)
        slices = cluster.get("endpointslices", "-l", f"kubernetes.io/service-name={args.service}")
        addresses = {
            address for item in slices["items"] for endpoint in item.get("endpoints", [])
            if endpoint.get("conditions", {}).get("ready") is True
            for address in endpoint.get("addresses", [])
        }
        report["ready_endpoint_addresses"] = sorted(addresses)
        if len(addresses) < 3:
            raise RuntimeError("fewer than three ready Service endpoints")

        worker.start()
        deadline = time.monotonic() + args.request_timeout + 5
        while not report["requests"] and time.monotonic() < deadline:
            time.sleep(0.1)
        if not report["requests"] or not report["requests"][0]["ok"]:
            raise RuntimeError("baseline traffic did not succeed")

        report["stage"] = "rollout"
        cluster.run("set", "image", f"deployment/{args.deployment}", f"{args.container}={args.image}")
        cluster.rollout(args.deployment)
        report["rollout_image"] = next(
            c["image"] for c in cluster.get("deployment", args.deployment)["spec"]["template"]
            ["spec"]["containers"] if c["name"] == args.container
        )
        report["stage"] = "rollback"
        cluster.run("rollout", "undo", f"deployment/{args.deployment}")
        cluster.rollout(args.deployment)
        report["rollback_image"] = next(
            c["image"] for c in cluster.get("deployment", args.deployment)["spec"]["template"]
            ["spec"]["containers"] if c["name"] == args.container
        )
        if report["rollback_image"] != original:
            raise RuntimeError("rollback did not restore the previous image")

        selector = ",".join(
            f"{key}={value}" for key, value in deployment["spec"]["selector"]["matchLabels"].items()
        )
        pods = cluster.get("pods", "-l", selector)["items"]
        victim = next(
            p for p in pods if not p["metadata"].get("deletionTimestamp")
            and any(c["type"] == "Ready" and c["status"] == "True"
                    for c in p.get("status", {}).get("conditions", []))
        )
        report["stage"] = "pod-replacement"
        cluster.run("delete", "pod", victim["metadata"]["name"], "--wait=false")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            current = cluster.get("pods", "-l", selector)["items"]
            ready = [
                p for p in current if not p["metadata"].get("deletionTimestamp")
                and any(c["type"] == "Ready" and c["status"] == "True"
                        for c in p.get("status", {}).get("conditions", []))
            ]
            if (len(ready) >= max(3, replicas)
                    and all(p["metadata"]["uid"] != victim["metadata"]["uid"] for p in current)):
                break
            time.sleep(1)
        else:
            raise RuntimeError("replacement pod did not become ready")
        report["deleted_pod_uid"] = victim["metadata"]["uid"]
        report["replacement_ready_pods"] = [p["metadata"]["name"] for p in ready]
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                report["top_pods"] = cluster.run("top", "pods")
                report["hpa"] = cluster.run("get", "hpa")
                if "<unknown>" not in report["hpa"]:
                    break
            except subprocess.CalledProcessError:
                pass  # Metrics-server may not have sampled the replacement yet.
            time.sleep(2)
        else:
            raise RuntimeError("resource metrics did not become available after pod replacement")
        report["operations_completed"] = True
    except (subprocess.SubprocessError, RuntimeError, ValueError, KeyError, httpx.HTTPError) as exc:
        report["error"] = str(exc)
        raise
    finally:
        stopped.set()
        if worker.ident is not None:
            worker.join(timeout=args.request_timeout + 2)
        # Restore the exact image/replica settings even after a failed rollout.
        errors = []
        for command in [
            ("set", "image", f"deployment/{args.deployment}", f"{args.container}={original}"),
            *[("patch", "hpa", name, "--type=merge", "-p", json.dumps({"spec": spec}))
              for name, spec in hpa_specs],
            ("scale", f"deployment/{args.deployment}", f"--replicas={replicas}"),
        ]:
            try:
                cluster.run(*command)
            except subprocess.SubprocessError as exc:
                errors.append(str(exc))
        try:
            cluster.rollout(args.deployment)
        except subprocess.SubprocessError as exc:
            errors.append(str(exc))
        report["restore_errors"] = errors
        report["passed"] = (
            report.get("operations_completed", False) and not errors
            and bool(report["requests"]) and all(row["ok"] for row in report["requests"])
        )
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if errors:
            raise RuntimeError("deployment restoration failed; inspect restore_errors")
    failures = [row for row in report["requests"] if not row["ok"]]
    if failures:
        raise RuntimeError(f"{len(failures)} user-visible request failures during the demonstration")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--deployment", default="api")
    parser.add_argument("--container", default="api")
    parser.add_argument("--service", default="api")
    parser.add_argument("--host", default="rahbar.local")
    parser.add_argument("--question", default="What is the attendance requirement?")
    parser.add_argument("--request-timeout", type=float, default=15)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.namespace in {"default", "kube-system", "kube-public", "kube-node-lease"}:
        parser.error("choose a dedicated application namespace")
    if args.request_timeout <= 0:
        parser.error("request timeout must be positive")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    demo(args)
    print(f"Operational measurements saved to {args.out}")


if __name__ == "__main__":
    main()
