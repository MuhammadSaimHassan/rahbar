from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl renderer unavailable")
@pytest.mark.parametrize("overlay", ["real-indexer", "real-query"])
def test_real_overlay_keeps_inference_policies_in_application_namespace(overlay):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["kubectl", "kustomize", str(root / "k8s/overlays" / overlay)],
                            check=True, capture_output=True, text=True)
    objects = list(yaml.safe_load_all(result.stdout))
    policies = set()
    for obj in objects:
        if obj["kind"] == "Namespace":
            continue
        assert obj["metadata"].get("namespace") == "rahbar", obj["metadata"]
        if obj["kind"] == "NetworkPolicy":
            policies.add(obj["metadata"]["name"])
    assert "indexer-to-ollama" in policies
    if overlay == "real-query":
        assert "api-to-ollama" in policies
