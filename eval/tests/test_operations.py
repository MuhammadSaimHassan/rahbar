from __future__ import annotations

import argparse
import json
import subprocess

import pytest

from scripts.operational_demo import demo


@pytest.mark.parametrize("failure", ["rollout", "endpoints"])
def test_operational_failure_restores_image_hpa_and_replicas(tmp_path, monkeypatch, failure) -> None:
    commands = []
    calls = []

    class FakeCluster:
        def get(self, resource, *args):
            if resource == "deployment":
                return {"spec": {
                    "replicas": 2, "strategy": {"type": "RollingUpdate"},
                    "template": {"spec": {"containers": [{"name": "api", "image": "api:original"}]}},
                }}
            if resource == "hpa":
                return {"items": [{"metadata": {"name": "api"}, "spec": {
                    "scaleTargetRef": {"kind": "Deployment", "name": "api"},
                    "minReplicas": 2, "maxReplicas": 5,
                }}]}
            return {"items": []}

        def run(self, *args):
            commands.append(args)
            return ""

        def rollout(self, deployment):
            calls.append(deployment)
            if failure == "rollout" and len(calls) == 1:
                raise subprocess.CalledProcessError(1, ["kubectl", "rollout"])

    monkeypatch.setattr("scripts.operational_demo.Cluster", lambda *args: FakeCluster())
    path = tmp_path / "report.json"
    args = argparse.Namespace(
        context="lab", namespace="rahbar", deployment="api", container="api", service="api",
        image="api:new", out=path, request_timeout=1,
    )
    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        demo(args)
    assert ("set", "image", "deployment/api", "api=api:original") in commands
    assert ("scale", "deployment/api", "--replicas=2") in commands
    restored = [json.loads(command[-1]) for command in commands
                if command[:3] == ("patch", "hpa", "api")]
    assert restored[-1]["spec"]["minReplicas"] == 2
    assert restored[-1]["spec"]["maxReplicas"] == 5
    report = json.loads(path.read_text())
    assert not report["passed"]
    assert not report["restore_errors"]
